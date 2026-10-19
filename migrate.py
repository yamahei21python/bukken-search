"""properties(生) -> 正規化テーブル(buildings/units/stations/listings/costs) の再構築。

修正点:
  - 建物キーに layout/area を混ぜていた誤りを修正(address+建物名のみ)
  - costs.listing_id に units.id を入れていた FK 誤りを修正(listings.id)
  - 未定義変数 tub による NameError を除去
  - listings に存在しない列 fetched への INSERT を除去
  - favorites/viewings/contacts/notifications(利用者の履歴)は削除しない
  - has_bathtub から tub_status を復元
"""
import re
from db import connect_db
from parse_suumo import normalize_address, normalize_building_name, strip_building_name
DERIVED_TABLES = ["amenities", "costs", "stations", "listings", "units",
                  "buildings", "evidence"]
_HB_TUB = {0: "confirmed_no_tub", 1: "confirmed_tub"}


def _old_rows(con):
    cols = [c[1] for c in con.execute("PRAGMA table_info(properties)")]
    if not cols:
        return []
    normalized = [c for c in
                  ["name", "address", "station", "walk_min", "age_years",
                   "room_floor", "rent_yen", "admin_yen", "shikikin_yen",
                   "reikin_yen", "layout", "area_m2", "detail_url",
                   "equipment", "has_bathtub", "no_bathtub_evidence"]
                  if c in cols]
    rows = con.execute(
        f"SELECT {','.join(normalized)} FROM properties").fetchall()
    rows = [dict(zip(normalized, r)) for r in rows]
    return rows


def migrate(force=False):
    con = connect_db()
    n_listings = con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    if n_listings and not force:
        con.close()
        print(f"normalized tables already populated ({n_listings} listings);"
              " skip. Use --force to rebuild from properties"
              " (詳細取得済みの costs/evidence は失われます)")
        return
    old = _old_rows(con)
    if not old:
        con.close()
        print("no properties rows to migrate")
        return
    for t in DERIVED_TABLES:
        con.execute(f"DELETE FROM {t}")

    n_b = n_u = n_l = 0
    for r in old:
        name = r.get("name") or ""
        addr = r.get("address") or ""
        display = strip_building_name(name, fallback="名称不明")
        na = normalize_address(addr)
        nn = normalize_building_name(display) or normalize_building_name(name)

        b = con.execute("SELECT id FROM buildings WHERE norm_address=? AND"
                        " norm_name=?", (na, nn)).fetchone()
        if not b:
            con.execute("INSERT INTO buildings(norm_address,name,norm_name,"
                        "age_years) VALUES(?,?,?,?)",
                        (na, display, nn, r.get("age_years")))
            n_b += 1
            b = con.execute("SELECT last_insert_rowid()").fetchone()
        bid = b[0]

        area = r.get("area_m2")
        floor = r.get("room_floor")
        layout = r.get("layout")
        tub = _HB_TUB.get(r.get("has_bathtub"), "unknown")
        uid = None
        if area:
            u = con.execute(
                "SELECT id FROM units WHERE building_id=? AND layout=?"
                " AND abs(area_m2-?)<=0.2 AND (floor IS ? OR floor=?)",
                (bid, layout, area, floor, floor)).fetchone()
            if u:
                uid = u[0]
            else:
                con.execute("INSERT INTO units(building_id,floor,area_m2,"
                            "layout,tub_status) VALUES(?,?,?,?,?)",
                            (bid, floor, area, layout, tub))
                n_u += 1
                uid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        if uid:
            con.execute("INSERT OR IGNORE INTO stations(unit_id,name,line,"
                        "walk_min) VALUES(?,?,?,?)",
                        (uid, r.get("station") or "", "", r.get("walk_min") or 0))

        url = r.get("detail_url")
        lid = None
        if url:
            con.execute("INSERT OR IGNORE INTO listings(unit_id,site,url,"
                        "rent_yen,admin_yen,shikikin,reikin) VALUES"
                        "(?,?,?,?,?,?,?)",
                        (uid, "suumo", url, r.get("rent_yen"), r.get("admin_yen"),
                         str(r.get("shikikin_yen")), str(r.get("reikin_yen"))))
            n_l += 1
            lid = con.execute("SELECT id FROM listings WHERE url=?",
                              (url,)).fetchone()
            lid = lid[0] if lid else None
        if lid:
            con.execute("INSERT OR IGNORE INTO costs(listing_id,key_money_yen,"
                        "deposit_yen,fetched) VALUES(?,?,?,0)",
                        (lid, r.get("reikin_yen"), r.get("shikikin_yen")))

        if uid and r.get("equipment"):
            for a in re.split(r"[、,]", r["equipment"][:2000]):
                a = a.strip()[:40]
                if a:
                    con.execute("INSERT OR IGNORE INTO amenities VALUES(?,?)",
                                (uid, a))
        if uid and r.get("no_bathtub_evidence"):
            con.execute("INSERT INTO evidence(unit_id,tub_status,quote,url,"
                        "method,confidence) VALUES(?,?,?,?,?,?)",
                        (uid, tub, r["no_bathtub_evidence"][:500], url,
                         "migrated", 0.5))
    con.commit()
    con.close()
    print(f"migrated buildings+{n_b} units+{n_u} listings+{n_l}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="properties から正規化テーブルを再構築（レガシー取込）")
    ap.add_argument("--force", action="store_true",
                    help="正規化済みでも再構築（詳細の costs/evidence は失う）")
    migrate(force=ap.parse_args().force)

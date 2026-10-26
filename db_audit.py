"""DB監査: bukken.db の過不足を数値で洗い出す（読み取り専用）。

割安判定（cost_perf）の信頼性は母集団の質で決まるため、次を定期点検する:
  - 重複: listings.url / properties.detail_url / 建物 / 部屋 / 駅 の重複件数
  - 不足: 詳細取得率（全体と「本命候補」内）、湯船判定の unknown 率、
          費用項目ごとの NULL 率、証拠・設備のカバー率
  - 陳腐化: last_seen が古いのに active=1 のまま残っている件数
  - 混入: 賃料上限を超えた listings、対象外駅が最寄りになっている件数

使い方:
  python3 db_audit.py                      # bukken.db を人間可読で表示
  python3 db_audit.py --db path/to.db --json
  python3 db_audit.py --max-total 100000 --walk-max 10 --stale-days 7
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent / "bukken.db"
COST_COLS = ["key_money_yen", "deposit_yen", "agency_yen",
             "guarantee_first_yen", "guarantee_renew_yen", "insurance_yen",
             "key_exchange_yen", "cleaning_yen", "support_yen",
             "support_monthly_yen",
             "water_fixed_yen", "renewal_fee_yen", "renewal_admin_fee_yen",
             "free_rent_months"]


def audit(db_path, max_total=100000, walk_max=10, stale_days=7):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    def one(sql, args=()):
        try:
            return con.execute(sql, args).fetchone()[0]
        except sqlite3.Error as e:
            return f"ERR: {e}"

    def rows(sql, args=()):
        try:
            return [dict(r) for r in con.execute(sql, args)]
        except sqlite3.Error as e:
            return [f"ERR: {e}"]

    out = {}
    tables = ["buildings", "units", "listings", "properties", "costs",
              "stations", "evidence", "listing_snapshots", "amenities"]
    out["counts"] = {t: one(f"SELECT COUNT(*) FROM {t}") for t in tables}

    # --- 重複 ---
    out["duplicates"] = {
        "listings_url_groups": one(
            "SELECT COUNT(*) FROM (SELECT url FROM listings"
            " GROUP BY url HAVING COUNT(*)>1)"),
        "properties_url_groups": one(
            "SELECT COUNT(*) FROM (SELECT detail_url FROM properties"
            " GROUP BY detail_url HAVING COUNT(*)>1)"),
        "buildings_groups": one(
            "SELECT COUNT(*) FROM (SELECT 1 FROM buildings"
            " GROUP BY norm_address, norm_name HAVING COUNT(*)>1)"),
        "units_groups": one(
            "SELECT COUNT(*) FROM (SELECT 1 FROM units"
            " GROUP BY building_id, layout, area_m2, floor HAVING COUNT(*)>1)"),
        "stations_groups": one(
            "SELECT COUNT(*) FROM (SELECT 1 FROM stations"
            " GROUP BY unit_id, name, line HAVING COUNT(*)>1)"),
    }

    # --- 不足: 詳細取得 ---
    total_listings = out["counts"]["listings"] or 0
    fetched = one("SELECT COUNT(*) FROM costs WHERE fetched=1") or 0
    cand_sql = (
        "FROM listings l JOIN units u ON u.id=l.unit_id"
        " LEFT JOIN costs c ON c.listing_id=l.id"
        " WHERE l.active=1 AND l.rent_yen + l.admin_yen <= ?"
        " AND EXISTS (SELECT 1 FROM stations s WHERE s.unit_id=u.id"
        "             AND s.walk_min<=?)")
    cand_total = one(f"SELECT COUNT(*) {cand_sql}", (max_total, walk_max)) or 0
    cand_fetched = one(
        f"SELECT COUNT(*) {cand_sql} AND COALESCE(c.fetched,0)=1",
        (max_total, walk_max)) or 0
    out["detail_coverage"] = {
        "listings": total_listings,
        "fetched": fetched,
        "fetched_rate": round(fetched / total_listings, 4)
        if total_listings else None,
        "candidate_listings": cand_total,
        "candidate_fetched": cand_fetched,
        "candidate_fetched_rate": round(cand_fetched / cand_total, 4)
        if cand_total else None,
        "candidate_backlog": cand_total - cand_fetched,
    }
    out["cost_null_rate_fetched"] = {
        col: (round(one(
            f"SELECT COUNT(*) FROM costs WHERE fetched=1 AND {col} IS NULL")
            / fetched, 4) if fetched else None)
        for col in COST_COLS
    }
    out["tub_status"] = rows(
        "SELECT tub_status, COUNT(*) n FROM units GROUP BY 1 ORDER BY 2 DESC")
    n_units = out["counts"]["units"] or 0
    unknown = one("SELECT COUNT(*) FROM units WHERE tub_status='unknown'") or 0
    out["tub_unknown_rate"] = round(unknown / n_units, 4) if n_units else None
    out["properties_has_bathtub_null"] = one(
        "SELECT COUNT(*) FROM properties WHERE has_bathtub IS NULL")
    out["evidence_units"] = one(
        "SELECT COUNT(DISTINCT unit_id) FROM evidence")
    out["amenities_units"] = one(
        "SELECT COUNT(DISTINCT unit_id) FROM amenities")
    out["units_without_station"] = one(
        "SELECT COUNT(*) FROM units u LEFT JOIN stations s"
        " ON s.unit_id=u.id WHERE s.id IS NULL")

    # --- 陳腐化・混入 ---
    out["stale_active"] = one(
        "SELECT COUNT(*) FROM listings WHERE active=1"
        " AND last_seen < datetime('now',?)",
        (f"-{stale_days} days",))
    out["last_seen_by_date"] = rows(
        "SELECT date(last_seen) d, COUNT(*) n FROM listings"
        " GROUP BY 1 ORDER BY 1")
    out["rent_over_cap"] = one(
        "SELECT COUNT(*) FROM listings WHERE rent_yen > ?", (max_total,))
    out["total_over_cap"] = one(
        "SELECT COUNT(*) FROM listings"
        " WHERE rent_yen + admin_yen > ?", (max_total,))

    # --- シャワー候補（手動確認バケット） ---
    # tub_status が unknown のままの unit のうち、設備文にシャワー
    # 設備の言及があり湯船の証拠が無いもの。判定は変えず、目視で
    # 確認すべき候補として列挙する。
    from models import is_shower_candidate
    cand = {}
    for r in rows(
            "SELECT u.id unit_id, b.name building, l.url, p.equipment"
            " FROM units u JOIN listings l ON l.unit_id = u.id"
            " JOIN properties p ON p.detail_url = l.url"
            " JOIN buildings b ON b.id = u.building_id"
            " WHERE u.tub_status = 'unknown'"
            " AND p.equipment IS NOT NULL AND p.equipment != ''"):
        if r["unit_id"] in cand:
            continue
        if is_shower_candidate(r["equipment"]):
            cand[r["unit_id"]] = {"unit_id": r["unit_id"],
                                   "building": r["building"],
                                   "url": r["url"]}
    out["shower_candidates"] = list(cand.values())
    out["shower_candidate_count"] = len(cand)

    # --- 管理費の掲載ミス疑い ---
    # SUUMO 側の入力ミス（管理費が家賃の半分以上）が parser を素通り
    # して総額を押し上げ、候補から静かに脱落する。値を直すことは
    # できないため、疑いとして列挙して目視確認に回す。
    out["admin_suspect"] = rows(
        "SELECT name, rent_yen, admin_yen, total_yen, detail_url"
        " FROM properties WHERE rent_yen > 0"
        " AND admin_yen >= rent_yen * 0.5 ORDER BY admin_yen DESC")
    con.close()
    return out


def main():
    ap = argparse.ArgumentParser(description="bukken.db 監査")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--max-total", type=int, default=100000)
    ap.add_argument("--walk-max", type=int, default=10)
    ap.add_argument("--stale-days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not a.db.exists():
        print(f"DB not found: {a.db}", file=sys.stderr)
        return 1
    r = audit(a.db, a.max_total, a.walk_max, a.stale_days)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    c = r["counts"]
    print("== counts ==")
    for t, n in c.items():
        print(f"  {t}: {n}")
    print("== duplicates (0が正常) ==")
    for k, v in r["duplicates"].items():
        print(f"  {k}: {v}")
    d = r["detail_coverage"]
    print("== detail coverage ==")
    print(f"  fetched: {d['fetched']}/{d['listings']}"
          f" ({d['fetched_rate']})")
    print(f"  candidates (総額<={a.max_total}, 歩<={a.walk_max}):"
          f" {d['candidate_fetched']}/{d['candidate_listings']}"
          f" ({d['candidate_fetched_rate']}) backlog={d['candidate_backlog']}")
    print("== cost NULL rate (fetched=1) ==")
    for k, v in r["cost_null_rate_fetched"].items():
        print(f"  {k}: {v}")
    print(f"== tub unknown rate: {r['tub_unknown_rate']} ==")
    for row in r["tub_status"]:
        print(f"  {row['tub_status']}: {row['n']}")
    print(f"properties has_bathtub NULL: {r['properties_has_bathtub_null']}")
    print(f"evidence units: {r['evidence_units']},"
          f" amenities units: {r['amenities_units']},"
          f" units w/o station: {r['units_without_station']}")
    print(f"== stale active (>{a.stale_days}d): {r['stale_active']} ==")
    print(f"rent>{a.max_total}: {r['rent_over_cap']},"
          f" total>{a.max_total}: {r['total_over_cap']}")
    print(f"== shower candidates (手動確認): "
          f"{r['shower_candidate_count']} ==")
    for c in r["shower_candidates"]:
        print(f"  unit {c['unit_id']} {c['building']} {c['url']}")
    print(f"== admin suspect (管理費>=家賃の50%、SUUMO掲載ミス疑い): "
          f"{len(r['admin_suspect'])} ==")
    for s in r["admin_suspect"]:
        print(f"  {s['name']} 家賃{s['rent_yen']} 管理費{s['admin_yen']}"
              f" 総額{s['total_yen']} {s['detail_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

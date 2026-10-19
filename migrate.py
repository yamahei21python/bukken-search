"""正規化＋重複統合＋旧properties→新スキーマ移行"""
import re
import sqlite3
import unicodedata
from pathlib import Path
import yaml
DB = Path(__file__).parent / "bukken.db"
CFG = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))
BUILDING_STRIP = CFG.get("building_name_strip_patterns", [])

def strip_building_name(name):
    clean = name
    for pat in BUILDING_STRIP:
        clean = re.sub(pat, "", clean).strip()
    return clean or name

def norm_name(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("　", " ").strip()
    # 「地下鉄○○線 阿波座駅 ...」形式は建物名ではない
    if re.match(r"^(地下鉄|JR|京阪|阪急|南海|近鉄)", s) and "駅" in s:
        return ""
    # ローマ数字・表記揺れ
    s = re.sub(r"\s+", "", s)
    s = s.replace("Ⅱ", "II").replace("Ⅲ", "III")
    return s.lower()

def norm_addr(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).replace("　", " ").strip()
    s = re.sub(r"\s+", "", s)
    s = s.replace("大阪府大阪市", "").replace("大阪市", "")
    return s

def migrate():
    con = sqlite3.connect(DB)
    con.executescript(open(Path(__file__).parent / "schema.sql").read())
    try:
        old = con.execute("SELECT name,address,walk_min,age_years,room_floor,"
                          "rent_yen,admin_yen,shikikin_yen,reikin_yen,"
                          "layout,area_m2,detail_url,equipment,has_bathtub,no_bathtub_evidence "
                          "FROM properties").fetchall()
    except Exception as e:
        print("no old table:", e)
        return
    n_b = n_u = n_l = 0
    for (name, addr, walk, age, floor, rent, admin, shiki, rei,
         layout, area, url, equip, hb, ev) in old:
        nn, na = norm_name(name), norm_addr(addr)
        if not nn:
            nn = (na + (layout or "") + str(area or ""))[:40] or "unknown"
        b = con.execute("SELECT id FROM buildings WHERE norm_address=? AND norm_name=?",
                        (na, nn)).fetchone()
        if not b:
            con.execute("INSERT INTO buildings(norm_address,name,norm_name,age_years)"
                        " VALUES(?,?,?,?)", (na, strip_building_name(name), nn, age))
            n_b += 1
            b = con.execute("SELECT id FROM buildings WHERE norm_address=? AND norm_name=?",
                            (na, nn)).fetchone()
        bid = b[0]
        tub = {0: "likely_no_tub", 1: "likely_tub"}.get(hb, "unknown")
        u = None
        if area is not None:
            u = con.execute("SELECT id FROM units WHERE building_id=? AND "
                            "(floor IS ? OR floor=?) AND layout=? AND abs(area_m2-?)<=0.2",
                            (bid, floor, floor, layout, area)).fetchone()
        if not u:
            con.execute("INSERT INTO units(building_id,floor,area_m2,layout,tub_status)"
                        " VALUES(?,?,?,?,?)", (bid, floor, area, layout, tub))
            n_u += 1
            u = con.execute("SELECT last_insert_rowid()").fetchone()
        uid = u[0]
        try:
            con.execute("INSERT OR REPLACE INTO listings(unit_id,site,url,rent_yen,admin_yen,shikikin,reikin)"
                        " VALUES(?,'suumo',?,?,?,?,?)",
                        (uid, url, rent, admin,
                         str(shiki) if shiki is not None else "",
                         str(rei) if rei is not None else ""))
            n_l += 1
        except Exception:
            pass
        lid = con.execute("SELECT id FROM listings WHERE url=?", (url,)).fetchone()
        if lid:
            # costs に敷金・礼金を初期投入（一覧取得分）
            try:
                con.execute("INSERT OR REPLACE INTO costs(listing_id,key_money_yen,deposit_yen,fetched)"
                            " VALUES(?,?,?,0)", (lid[0], rei or 0, shiki or 0))
            except Exception:
                pass
        if equip:
            for a in re.split(r"[、,]", equip[:2000]):
                a = a.strip()[:40]
                if a:
                    try:
                        con.execute("INSERT OR IGNORE INTO amenities VALUES(?,?)", (uid, a))
                    except Exception:
                        pass
        if ev:
            try:
                con.execute("INSERT INTO evidence(unit_id,tub_status,quote,url,method,confidence)"
                            " VALUES(?,?,?,?,?,?)", (uid, tub, ev[:500], url, "migrated", 0.5))
            except Exception:
                pass
    con.commit(); con.close()
    print(f"migrated buildings+{n_b} units+{n_u} listings+{n_l}")

if __name__ == "__main__":
    migrate()

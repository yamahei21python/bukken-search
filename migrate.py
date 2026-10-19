"""正規化＋重複統合＋旧properties→新スキーマ移行（propertiesを単一ソースとして、関連テーブルを再構築）"""
import re
import sqlite3
import unicodedata
from pathlib import Path
import yaml

DB = Path(__file__).parent / "bukken.db"
CFG = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))
BUILDING_STRIP = CFG.get("building_name_strip_patterns", [])

def norm_name(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("　", " ").strip()
    if re.match(r"^(地下鉄|JR|京阪|阪急|南海|近鉄)", s) and "駅" in s:
        return ""
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

def strip_building_name(name):
    clean = name
    for pat in BUILDING_STRIP:
        clean = re.sub(pat, "", clean).strip()
    return clean or name

def migrate():
    con = sqlite3.connect(DB)
    try:
        old = con.execute("SELECT name,address,station,walk_min,age_years,room_floor,"
                          "rent_yen,admin_yen,shikikin_yen,reikin_yen,"
                          "layout,area_m2,detail_url,equipment,has_bathtub,no_bathtub_evidence "
                          "FROM properties").fetchall()
    except Exception as e:
        print("no old table:", e)
        return

    n_b = n_u = n_l = 0
    # migrate対象テーブルをproperties起点に再構築
    con.executescript(
        "DELETE FROM amenities;"
        "DELETE FROM costs;"
        "DELETE FROM stations;"
        "DELETE FROM listings;"
        "DELETE FROM units;"
        "DELETE FROM buildings;"
        "DELETE FROM evidence;"
        "DELETE FROM viewings;"
        "DELETE FROM favorites;"
        "DELETE FROM contacts;"
        "DELETE FROM notifications;")  # viewings/favorites/contacts/contacts は履歴として保持する場合も、先に削除して再構築はしない（必要なら残す）…

    for (name, addr, station, walk, age, floor, rent, admin, shiki, rei,
         layout, area, url, equip, hb, ev) in old:
        na = norm_addr(name)
        display_name = strip_building_name(name) or "名称不明"
        search_key = (na + (layout or "") + str(area or ""))[:40] or "unknown"

        # building（住所+建物名で同一キー）
        b = con.execute("SELECT id FROM buildings WHERE norm_address=? AND norm_name=?",
                        (na, search_key)).fetchone()
        if not b:
            con.execute("INSERT INTO buildings(norm_address,name,norm_name,age_years)"
                        " VALUES(?,?,?,?)", (na, display_name, search_key, age))
            n_b += 1
            b = con.execute("SELECT id FROM buildings WHERE norm_address=? AND norm_name=?",
                            (na, search_key)).fetchone()
        bid = b[0]

        # unit（建物の部屋）: 再ビルドではproperties 1件=1unit として作成
        if not area:
            continue
        u = con.execute("SELECT id FROM units WHERE building_id=? AND floor=? AND layout=? AND abs(area_m2-?)<=0.2",
                        (bid, floor, layout, area)).fetchone()
        if not u:
            con.execute("INSERT INTO units(building_id,floor,area_m2,layout,tub_status) VALUES(?,?,?,?,?)",
                        (bid, floor, area, layout, "unknown"))
            n_u += 1
            u = con.execute("SELECT last_insert_rowid()").fetchone()
        uid = u[0]

        # station
        con.execute("INSERT OR IGNORE INTO stations(unit_id, name, line, walk_min) VALUES(?,?,?,?)",
                    (uid, display_name, station or "", walk or 0))

        # listings
        try:
            con.execute("INSERT OR IGNORE INTO listings(unit_id,site,url,rent_yen,admin_yen,shikikin,reikin,fetched)"
                        " VALUES(?,?,?,?,?,?,?,0)",
                        (uid, 'suumo', url, rent, admin,
                         shiki if shiki is not None else '', rei if rei is not None else ''))
            n_l += 1
        except Exception:
            pass

        # costs（初期）: fetched=0（詳細取得後が1になる）
        try:
            con.execute("INSERT OR IGNORE INTO costs(listing_id,key_money_yen,deposit_yen,fetched)"
                        " VALUES(?,?,?,0)", (uid, rei or 0, shiki or 0))
        except Exception:
            pass

        # amenities, evidence
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
    con.commit()
    print(f"migrated buildings+{n_b} units+{n_u} listings+{n_l}")

if __name__ == "__main__":
    migrate()

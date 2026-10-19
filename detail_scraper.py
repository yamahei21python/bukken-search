"""詳細ページ取得: 初期費用・証拠付き湯船判定・スナップショット
低頻度・差分・リトライ3・robots配慮(連打禁止・1秒間隔)。"""
import re
import sqlite3
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from models import judge_tub
DB = Path(__file__).parent / "bukken.db"
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def fetch(url, retry=3):
    for i in range(retry):
        try:
            r = requests.get(url, headers=H, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "lxml")
        except Exception as e:
            if i == retry - 1:
                raise
            time.sleep(2 * (i + 1))

YEN = lambda s: int(float(m.group(1)) * 10000) if (m := re.search(r"([\d.]+)万円", s or "")) else (int(m.group(1)) if (m := re.search(r"(\d+)円", s or "")) else 0)

def parse_detail(soup):
    feat = ""
    for h in soup.find_all(["h2", "h3"]):
        if "部屋の特徴" in h.get_text() or "設備" in h.get_text():
            feat = h.parent.get_text(" ", strip=True)
            break
    full = soup.get_text(" ", strip=True)
    lines = soup.get_text("\n", strip=True).split("\n")

    def field_value(label):
        """「敷金: -」「礼金: 9.3万円」形式の行から厳密抽出。-は0扱いではなくNone。"""
        import unicodedata as _ud
        for ln in lines:
            s = _ud.normalize("NFKC", ln).strip()
            if s.startswith(label + ":") or s.startswith(label + " :"):
                v = s.split(":", 1)[1].strip().replace("\xa0", "")
                if v in ("-", "−", "‐", ""):
                    return None
                return v
        return None

    def grab(*keys):
        for k in keys:
            m = re.search(k + r"[^0-9]{0,10}([\d.]+万円|\d+円|なし|不要|込|無料)", full)
            if m:
                return m.group(1)
        return ""
    fv_shiki = field_value("敷金")
    fv_rei = field_value("礼金")
    costs = dict(shikikin=fv_shiki if fv_shiki is not None else "",
                 reikin=fv_rei if fv_rei is not None else "",
                 shikikin_none=fv_shiki is None,
                 reikin_none=fv_rei is None,
                 guarantee=grab("保証会社", "保証料"),
                 insurance=grab("火災保険", "損保"),
                 keyex=grab("鍵交換"), cleaning=grab("清掃費", "クリーニング", "ハウスクリーニング"),
                 support=grab("サポート", "安心サポート", "CLUB"),
                 renewal=grab("更新料"),
                 agency=grab("仲介手数料", "仲介料"),
                 regular=0 if "定期借家" in full else 1,
                 freerent=1 if "フリーレント" in full else 0)
    m = re.search(r".{0,60}(シャワー|浴槽|湯船|バス|浴室).{0,60}", feat or full)
    outline = (m.group(0)[:300] if m else (feat or full)[:300])
    photos = [img.get("src", "") for img in soup.select("img")][:10]
    return feat[:4000], costs, outline, photos

def run(limit=50, sleep=1.0, only_missing=True):
    con = sqlite3.connect(DB)
    q = ("SELECT l.id,l.url,u.id FROM listings l JOIN units u ON u.id=l.unit_id"
         " LEFT JOIN listing_snapshots s ON s.listing_id=l.id")
    if only_missing:
        q += " WHERE l.active=1 AND s.id IS NULL"
    else:
        q += (" WHERE l.active=1 AND (s.id IS NULL OR l.last_seen < "
              "datetime('now','-7 days'))")
    q += " GROUP BY l.id LIMIT ?"
    rows = con.execute(q, (limit,)).fetchall()
    print(f"detail targets: {len(rows)} (only_missing={only_missing})")
    for lid, url, uid in rows:
        if not url:
            continue
        try:
            soup = fetch(url)
            feat, costs, outline, photos = parse_detail(soup)
            status, kw, conf = judge_tub(feat)
            lid_rent = con.execute("SELECT rent_yen,admin_yen FROM listings WHERE id=?", (lid,)).fetchone()
            con.execute("INSERT INTO listing_snapshots(listing_id,rent_yen,admin_yen,active,equip_text)"
                        " VALUES(?,?,?,?,?)", (lid, lid_rent[0], lid_rent[1], 1, feat[:2000]))
            con.execute("UPDATE units SET tub_status=?,tub_confidence=? WHERE id=?", (status, conf, uid))
            con.execute("INSERT INTO evidence(unit_id,tub_status,quote,url,photo_url,method,confidence)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (uid, status, (kw + " | " + outline)[:500], url,
                         (photos[0] if photos else ""), "detail_parse", conf))
            con.execute("INSERT OR REPLACE INTO costs(listing_id,key_money_yen,deposit_yen,"
                        "agency_yen,"
                        "guarantee_first_yen,insurance_yen,key_exchange_yen,cleaning_yen,"
                        "support_yen,renewal_fee_yen,regular_lease,fetched,note)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (lid, YEN(costs["shikikin"]), YEN(costs["reikin"]), YEN(costs["agency"]),
                         YEN(costs["guarantee"]),
                         YEN(costs["insurance"]), YEN(costs["keyex"]), YEN(costs["cleaning"]),
                         YEN(costs["support"]), YEN(costs["renewal"]), costs["regular"], 1,
                         ("free-rent " if costs["freerent"] else "")
                         + ("shiki-none " if costs.get("shikikin_none") else "")
                         + ("rei-none " if costs.get("reikin_none") else "")
                         + outline[:200]))
            con.execute("UPDATE listings SET last_seen=datetime('now','localtime') WHERE id=?", (lid,))
            con.commit()
            print(lid, status, kw, outline[:60])
        except Exception as e:
            print(lid, "ERR", str(e)[:120])
            try:
                con.execute("INSERT INTO listing_snapshots(listing_id,active,equip_text)"
                            " VALUES(?,0,?)", (lid, str(e)[:200]))
                con.commit()
            except Exception:
                pass
        time.sleep(sleep)
    con.close()

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--all", action="store_true",
                    help="取得済みが7日以上古いものも再取得")
    run(ap.parse_args().limit, only_missing=not ap.parse_args().all)

"""buildings.lat/lon の充填（国土地理院 住所検索 API、キー不要）。

住所は norm_address（市区町村・丁目まで）単位で引くため、座標の
精度は丁目セントロイド（おおよそ 100〜300m）。番地レベルの精度は
求めない（元データに番地が無い）。同一住所の buildings は同じ
座標を共有する。

- 対象は lat/lon が NULL の buildings のみ（冪等）
- 返ってきた地名が「区名＋町名」を含まない場合は誤マッチとして
  採用しない
- 使い方: python3 geocode_buildings.py [db_path]
"""
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB = Path(__file__).parent / "bukken.db"
API = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
UA = {"User-Agent": "bukken-search-geocode/1.0 (personal rental search)"}
CITY_PREFIX = "大阪府大阪市"


def lookup(query):
    url = API + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def plausible(title, norm_address):
    """返却地名が問い合わせた住所（区＋町名）を含むかで誤マッチを弾く。"""
    m = re.match(r"(.+?区)(.+?)(\d+.*)?$", norm_address or "")
    if not m:
        return False
    ward, town = m.group(1), m.group(2)
    return ward in title and (not town or town in title)


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB
    con = sqlite3.connect(db_path)
    addrs = [r[0] for r in con.execute(
        "SELECT DISTINCT norm_address FROM buildings"
        " WHERE (lat IS NULL OR lon IS NULL) AND norm_address IS NOT NULL"
        " AND norm_address != '' ORDER BY norm_address")]
    print(f"target addresses: {len(addrs)}")
    hit = miss = 0
    for addr in addrs:
        query = CITY_PREFIX + addr
        try:
            res = lookup(query)
        except Exception as e:
            print(f"  ERROR {addr}: {e}")
            res = None
            time.sleep(1.0)
        filled = 0
        if res:
            f = res[0]
            title = f["properties"]["title"]
            if plausible(title, addr):
                lon, lat = f["geometry"]["coordinates"]
                cur = con.execute(
                    "UPDATE buildings SET lat=?, lon=? WHERE norm_address=?"
                    " AND (lat IS NULL OR lon IS NULL)", (lat, lon, addr))
                filled = cur.rowcount
                hit += 1
                print(f"  {addr} -> lat={lat:.6f} lon={lon:.6f}"
                      f" ({title}) buildings={filled}")
            else:
                print(f"  MISMATCH {addr}: got '{title}' — skipped")
        if not filled:
            miss += 1
        time.sleep(0.2)
    con.commit()
    total, filled_total = con.execute(
        "SELECT COUNT(*), COUNT(lat) FROM buildings").fetchone()
    con.close()
    print(f"done: addresses hit={hit} miss={miss};"
          f" buildings with lat: {filled_total}/{total}")
    return 0 if hit or not addrs else 1


if __name__ == "__main__":
    sys.exit(main())

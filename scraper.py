"""賃貸スクレイパー: SUUMO一覧 -> 正規化DB + properties へ取り込む。

旧版からの修正点:
  - 一覧 td を固定位置で読む(空セル除去による桁ズレを排除) -> parse_suumo
  - 駅はカセット内の全「路線/駅 歩N分」を取得し最寄りを採用。検索駅の固定代入を廃止
  - URL は ?bc= を除去して正規化。jnc 番号で重複排除(旧: UNIQUEが効かず重複混入)
  - properties に shikikin/reikin/direction/structure/floors 等を最初から作成
  - 正規化テーブル(buildings/units/stations/listings/costs)を直接更新

使い方:
  python3 scraper.py --rebuild --max-pages 3           # DB再作成して取得
  python3 scraper.py --stations 阿波座 本町 --max-pages 2
  python3 scraper.py --list-html path/to/list.html     # 保存済みHTMLを解析(オフライン)
"""
import argparse
import time
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from db import DB, connect_db, initialize_db
from parse_suumo import normalize_address, normalize_building_name, parse_list
from scrape_common import fetch_soup, sleep_with_jitter

BASE = "https://suumo.jp"
CFG = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))
EK_CODES = CFG["ek_codes"]

def init_db(rebuild=False):
    """互換維持用ラッパー。実体はdb.initialize_db。"""
    initialize_db(rebuild=rebuild)


def list_url(page, ek, chinryo_max):
    u = f"{BASE}/chintai/osaka/{ek}/?fr_chinryomax={chinryo_max}"
    if page > 1:
        u += f"&page={page}"
    return u


def fetch(url: str, retry: int = 3) -> BeautifulSoup:
    """一覧URL取得。429/5xxを再試行。"""
    return fetch_soup(url, retry=retry, retry_delay=5)


def _get_or_create_building(con, r):
    na = normalize_address(r["address"])
    nn = normalize_building_name(r["name"]) or r["name"]
    row = con.execute("SELECT id,age_years,structure,floors FROM buildings"
                      " WHERE norm_address=? AND norm_name=?", (na, nn)).fetchone()
    if row:
        con.execute("UPDATE buildings SET age_years=COALESCE(?,age_years),"
                    " structure=COALESCE(?,structure), floors=COALESCE(?,floors)"
                    " WHERE id=?", (r["age_years"], r.get("structure"),
                                    r["floors"], row[0]))
        return row[0]
    con.execute("INSERT INTO buildings(norm_address,name,norm_name,age_years,"
                "structure,floors) VALUES(?,?,?,?,?,?)",
                (na, r["name"], nn, r["age_years"], r.get("structure"),
                 r["floors"]))
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def _get_or_create_unit(con, bid, r):
    if not r["area_m2"]:
        return None
    row = con.execute(
        "SELECT id FROM units WHERE building_id=? AND layout=? "
        "AND abs(area_m2-?)<=0.3 AND (floor IS ? OR floor=?)",
        (bid, r["layout"], r["area_m2"], r["floor"], r["floor"])).fetchone()
    if row:
        return row[0]
    con.execute("INSERT INTO units(building_id,floor,area_m2,layout,direction)"
                " VALUES(?,?,?,?,?)",
                (bid, r["floor"], r["area_m2"], r["layout"], r.get("direction")))
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def _save_stations(con, uid, stations, nearest):
    if not uid:
        return
    seen = set()
    for s in stations or []:
        seen.add((s["name"], s["line"]))
        con.execute("INSERT OR IGNORE INTO stations(unit_id,name,line,walk_min)"
                    " VALUES(?,?,?,?)", (uid, s["name"], s["line"], s["walk"]))
    if not stations and nearest.get("name"):
        con.execute("INSERT OR IGNORE INTO stations(unit_id,name,line,walk_min)"
                    " VALUES(?,?,?,?)",
                    (uid, nearest["name"], nearest.get("line"), nearest["walk"]))


def save(rows):
    """一覧取得行を properties と正規化テーブルへ upsert。"""
    con = connect_db()
    n = 0
    for r in rows:
        if not r["url"]:
            continue
        bid = _get_or_create_building(con, r)
        uid = _get_or_create_unit(con, bid, r)
        _save_stations(con, uid, r["stations"], r["nearest"])
        rent, admin = r["rent_yen"], r["admin_yen"]
        total = (rent or 0) + (admin or 0)
        row = con.execute("SELECT id FROM listings WHERE url=?",
                          (r["url"],)).fetchone()
        if row:
            lid = row[0]
            con.execute("UPDATE listings SET unit_id=?,rent_yen=?,admin_yen=?,"
                        "shikikin=?,reikin=?,last_seen=datetime('now',"
                        "'localtime'),active=1 WHERE id=?",
                        (uid, rent, admin, str(r["shikikin_yen"]),
                         str(r["reikin_yen"]), lid))
        else:
            con.execute(
                "INSERT INTO listings(unit_id,site,url,rent_yen,admin_yen,"
                "shikikin,reikin,last_seen,active) VALUES(?,?,?,?,?,?,?,"
                "datetime('now','localtime'),1)",
                (uid, "suumo", r["url"], rent, admin,
                 str(r["shikikin_yen"]), str(r["reikin_yen"])))
            lid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute("INSERT OR IGNORE INTO costs(listing_id,key_money_yen,"
                    "deposit_yen,fetched) VALUES(?,?,?,0)",
                    (lid, r["reikin_yen"], r["shikikin_yen"]))
        con.execute(
            "INSERT OR REPLACE INTO properties(name,address,station,walk_min,"
            "age_years,room_floor,rent_yen,admin_yen,total_yen,shikikin_yen,"
            "reikin_yen,layout,area_m2,direction,structure,floors,detail_url,"
            "scraped_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "datetime('now','localtime'))",
            (r["name"], r["address"], r["nearest"]["name"],
             r["nearest"]["walk"], r["age_years"], r["floor"], rent, admin,
             total, r["shikikin_yen"], r["reikin_yen"], r["layout"],
             r["area_m2"], r.get("direction"), r.get("structure"),
             r["floors"], r["url"]))
        n += 1
    con.commit()
    con.close()
    return n


def deactivate_stale(days=7):
    """一定日数見ていない listings を active=0 にする。

    従来は active=0 への遷移が無く、募集終了した物件が母集団に
    残り続けて割安判定を汚していた。再び一覧に現れれば save() が
    active=1 に戻す。全駅を回す通常実行のときだけ呼ぶこと
    （一部駅だけの実行で他駅の物件を落とさないため）。
    """
    con = connect_db()
    cur = con.execute(
        "UPDATE listings SET active=0 WHERE active=1"
        " AND last_seen < datetime('now','localtime',?)",
        (f"-{days} days",))
    con.commit()
    n = cur.rowcount
    con.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--chinryo-max", type=int, default=12)
    ap.add_argument("--stations", nargs="*", default=None,
                    help="省略時は config.yaml の全駅")
    ap.add_argument("--rebuild", action="store_true", help="全テーブル再作成")
    ap.add_argument("--list-html", type=Path,
                    help="保存済み一覧HTMLを解析(ネットワーク不要)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=3.0,
                    help="1ページ毎の待機秒(負荷軽減)")
    ap.add_argument("--jitter", type=float, default=1.5,
                    help="待機に加えるランダム幅(秒)")
    ap.add_argument("--stale-days", type=int, default=7,
                    help="この日数見ていない listings を active=0 にする"
                         "（全駅実行時のみ）")
    a = ap.parse_args()

    init_db(rebuild=a.rebuild)

    if a.list_html:
        rows = parse_list(BeautifulSoup(a.list_html.read_text(), "lxml"))
        print(f"{a.list_html.name}: {len(rows)} rooms")
        if not a.dry_run:
            print("saved", save(rows))
        return

    targets = a.stations or list(EK_CODES)
    total = 0
    for stn in targets:
        ek = EK_CODES.get(stn)
        if not ek:
            print(f"[skip] unknown station: {stn}")
            continue
        for page in range(1, a.max_pages + 1):
            url = list_url(page, ek, a.chinryo_max)
            try:
                soup = fetch(url)
            except Exception as e:
                print(f"[list error] {stn} p{page}: {str(e)[:100]}")
                break
            rows = parse_list(soup, focus_station=stn)
            print(f"[list] {stn} p{page}: {len(rows)} rooms")
            if not rows:
                break
            if not a.dry_run:
                save(rows)
            total += len(rows)
            sleep_with_jitter(a.sleep, a.jitter)
    if not a.dry_run and not a.stations:
        n = deactivate_stale(a.stale_days)
        print(f"deactivated stale listings: {n} (>{a.stale_days} days)")
    print(f"done: {total} rooms -> {DB}")


if __name__ == "__main__":
    main()

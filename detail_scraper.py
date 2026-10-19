"""詳細ページ取得: 初期費用・設備・湯船証拠・スナップショットを取り込む。

parse_suumo.parse_detail（20物件で検証済み）を使い、
  - costs（初期費用の実額）を fetched=1 で確定
  - properties / listings / units / buildings を更新
  - listing_snapshots と evidence を追記
する。連打禁止・リトライ付き。

使い方:
  python3 detail_scraper.py --limit 100            # 未取得のみ
  python3 detail_scraper.py --all --limit 50       # 7日以上前も再取得
  python3 detail_scraper.py --detail-html FILE      # 保存済みHTMLを解析(オフライン)
"""
import argparse
import time
from pathlib import Path

from bs4 import BeautifulSoup

from models import judge_tub
from db import connect_db
from parse_suumo import canonical_url, parse_detail
from scrape_common import fetch_soup, sleep_with_jitter
_TUB_INT = {"confirmed_no_tub": 0, "likely_no_tub": 0,
            "confirmed_tub": 1, "likely_tub": 1, "unknown": -1}


def fetch(url: str, retry: int = 3) -> BeautifulSoup:
    """詳細URL取得。429/5xxと通信例外を再試行。"""
    return fetch_soup(url, retry=retry, retry_delay=2)


def targets(con, limit, only_missing):
    q = ("SELECT l.id, l.url, u.id FROM listings l JOIN units u ON u.id=l.unit_id"
         " LEFT JOIN costs c ON c.listing_id=l.id")
    q += (" WHERE l.active=1 AND (c.fetched IS NULL OR c.fetched=0)"
          if only_missing else
          " WHERE l.active=1 AND (c.fetched IS NULL OR c.fetched=0"
          " OR l.last_seen < datetime('now','-7 days'))")
    q += " GROUP BY l.id LIMIT ?"
    return con.execute(q, (limit,)).fetchall()


def _find_listing(con, url, fallback_pattern=None):
    """URL完全一致、次にLIKEで物件を検索。"""
    query = ("SELECT l.id, u.id FROM listings l JOIN units u ON u.id=l.unit_id"
             " WHERE l.url=?")
    row = con.execute(query, (url,)).fetchone()
    if not row and fallback_pattern:
        row = con.execute(query.replace("l.url=?", "l.url LIKE ?"),
                          (fallback_pattern,)).fetchone()
    return row


def _parse_and_apply_detail(con, lid, uid, url, source, include_equipment=False):
    """詳細ソースを解析・適用し、保存結果を表示。"""
    detail = parse_detail(source)
    apply_detail(con, lid, uid, url, detail)
    con.commit()
    output = (f"{lid} {detail['rent_yen']}/{detail['admin_yen']} "
              f"鍵{detail['key_exchange_yen']} 清{detail['cleaning_yen']}")
    if include_equipment:
        output += f" {detail['equipment'][:40]}"
    print(output)


def apply_detail(con, lid, uid, url, d):
    status, kw, conf = judge_tub(d["equipment"])
    hb = _TUB_INT.get(status, -1)
    note = (d.get("note") or "")
    if d.get("hoshoukin_yen") is not None:
        note += f" 保証金{d['hoshoukin_yen']}"
    if d.get("shoukyaku_yen") is not None:
        note += f" 敷引償却{d['shoukyaku_yen']}"

    con.execute("UPDATE listings SET rent_yen=COALESCE(?,rent_yen),"
                " admin_yen=COALESCE(?,admin_yen), shikikin=?, reikin=?,"
                " last_seen=datetime('now','localtime') WHERE id=?",
                (d["rent_yen"], d["admin_yen"], str(d["deposit_yen"]),
                 str(d["key_money_yen"]), lid))
    con.execute(
        "UPDATE properties SET rent_yen=COALESCE(?,rent_yen),"
        " admin_yen=COALESCE(?,admin_yen),"
        " total_yen=COALESCE(?,total_yen),"
        " shikikin_yen=COALESCE(?,shikikin_yen),"
        " reikin_yen=COALESCE(?,reikin_yen),"
        " equipment=?, has_bathtub=?, no_bathtub_evidence=?,"
        " direction=COALESCE(?,direction),"
        " structure=COALESCE(?,structure), floors=COALESCE(?,floors),"
        " scraped_at=datetime('now','localtime') WHERE detail_url=?",
        (d["rent_yen"], d["admin_yen"],
         (d["rent_yen"] or 0) + (d["admin_yen"] or 0) if d["rent_yen"] else None,
         d["deposit_yen"], d["key_money_yen"], d["equipment"], hb,
         (kw + " | " + d["equipment"])[:400], d["direction"],
         d["structure"], d["floors"], canonical_url(url)))
    con.execute("UPDATE units SET tub_status=?, tub_confidence=?,"
                " direction=COALESCE(?,direction) WHERE id=?",
                (status, conf, d["direction"], uid))
    con.execute("DELETE FROM listing_snapshots WHERE listing_id=?"
                " AND date(fetched_at)=date('now','localtime')", (lid,))
    con.execute("INSERT INTO listing_snapshots(listing_id,rent_yen,admin_yen,"
                "active,equip_text) VALUES(?,?,?,1,?)",
                (lid, d["rent_yen"], d["admin_yen"], d["equipment"][:2000]))
    con.execute("DELETE FROM evidence WHERE unit_id=? AND url=?"
                " AND method='detail_parse'", (uid, url))
    con.execute("INSERT INTO evidence(unit_id,tub_status,quote,url,method,"
                "confidence) VALUES(?,?,?,?,?,?)",
                (uid, status, (kw + " | " + d["equipment"][:400]), url,
                 "detail_parse", conf))
    con.execute(
        "INSERT OR REPLACE INTO costs(listing_id,key_money_yen,deposit_yen,"
        "guarantee_first_yen,guarantee_renew_yen,insurance_yen,key_exchange_yen,"
        "cleaning_yen,support_yen,water_fixed_yen,renewal_fee_yen,"
        "contract_months,free_rent_months,regular_lease,fetched,note) VALUES"
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        (lid, d["key_money_yen"], d["deposit_yen"], d["guarantee_first_yen"],
         d["renewal_fee_yen"], d["insurance_yen"], d["key_exchange_yen"],
         d["cleaning_yen"], d["support_yen"], d["water_fixed_yen"],
         d["renewal_fee_yen"], d["contract_months"] or 24,
         d["free_rent_months"], d["regular_lease"], note[:500]))


def run(limit=50, sleep=5.0, jitter=2.0, only_missing=True, max_seconds=0):
    con = connect_db()
    rows = targets(con, limit, only_missing)
    print(f"detail targets: {len(rows)} (only_missing={only_missing})")
    start = time.time()
    done = 0
    for lid, url, uid in rows:
        if not url:
            continue
        if max_seconds and time.time() - start > max_seconds:
            print(f"time budget reached ({max_seconds}s); stopping "
                  f"({done}/{len(rows)})")
            break
        try:
            _parse_and_apply_detail(con, lid, uid, url, fetch(url),
                                    include_equipment=True)
            done += 1
        except Exception as e:
            con.rollback()
            print(lid, "ERR", str(e)[:120])
        sleep_with_jitter(sleep, jitter)
    con.close()
    print(f"detail done: {done}/{len(rows)}")


def run_offline_dir(path: Path):
    """保存済み detail_<jnc>.html を一括でDBへ適用（ネットワーク不要）。"""
    con = connect_db()
    files = sorted(Path(path).glob("detail_*.html"))
    applied = 0
    for f in files:
        jnc = f.stem.split("_", 1)[1]
        url = f"https://suumo.jp/chintai/jnc_{jnc}/"
        row = _find_listing(con, url, f"%jnc_{jnc}%")
        if not row:
            print(jnc, "no listing match")
            continue
        lid, uid = row
        try:
            _parse_and_apply_detail(con, lid, uid, url,
                                    BeautifulSoup(f.read_text(), "lxml"))
            applied += 1
        except Exception as e:
            con.rollback()
            print(jnc, "ERR", str(e)[:120])
    con.close()
    print(f"offline detail applied: {applied}/{len(files)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--all", action="store_true",
                    help="7日以上前も再取得")
    ap.add_argument("--sleep", type=float, default=5.0,
                    help="1件毎の待機秒(負荷軽減)")
    ap.add_argument("--jitter", type=float, default=2.0,
                    help="待機に加えるランダム幅(秒)")
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="この秒数を超えたら中断(0=無制限)")
    ap.add_argument("--detail-html", type=Path,
                    help="保存済み詳細HTMLを解析して表示(DB更新なし)")
    ap.add_argument("--detail-dir", type=Path,
                    help="保存済み詳細HTML群を一括でDBへ適用(オフライン)")
    a = ap.parse_args()
    if a.detail_html:
        d = parse_detail(BeautifulSoup(a.detail_html.read_text(), "lxml"))
        for k, v in d.items():
            print(f"{k}: {v}")
        return
    if a.detail_dir:
        run_offline_dir(a.detail_dir)
        return
    run(a.limit, sleep=a.sleep, jitter=a.jitter, only_missing=not a.all,
        max_seconds=a.max_seconds)


if __name__ == "__main__":
    main()

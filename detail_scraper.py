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


def targets(con, limit, only_missing, max_total=100000, walk_max=10):
    """詳細取得の対象を「本命候補から先に」返す。

    従来は id 順（=古い順）で、総額超過や徒歩圏外の物件にも取得枠を
    使い、候補の取得率が上がらなかった。優先順位:
      1. 総額(賃料+管理費) <= max_total かつ 最寄り駅まで徒歩<=walk_max
      2. 総額 <= max_total
      3. その他
    同順位内は徒歩が近い順 → last_seen が新しい順。
    """
    q = ("SELECT l.id, l.url, u.id FROM listings l JOIN units u ON u.id=l.unit_id"
         " LEFT JOIN costs c ON c.listing_id=l.id")
    q += (" WHERE l.active=1 AND (c.fetched IS NULL OR c.fetched=0)"
          if only_missing else
          " WHERE l.active=1 AND (c.fetched IS NULL OR c.fetched=0"
          " OR l.last_seen < datetime('now','-7 days'))")
    q += (" GROUP BY l.id"
          " ORDER BY"
          " CASE WHEN l.rent_yen + l.admin_yen <= ?"
          " AND EXISTS (SELECT 1 FROM stations s WHERE s.unit_id=u.id"
          "             AND s.walk_min<=?) THEN 0"
          " WHEN l.rent_yen + l.admin_yen <= ? THEN 1 ELSE 2 END,"
          " (SELECT MIN(s2.walk_min) FROM stations s2"
          "   WHERE s2.unit_id=u.id),"
          " l.last_seen DESC"
          " LIMIT ?")
    return con.execute(q, (max_total, walk_max, max_total, limit)).fetchall()


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
    status, kw, conf = judge_tub(d)
    hb = _TUB_INT.get(status, -1)
    note = (d.get("note") or "")
    if d.get("hoshoukin_yen") is not None:
        note += f" 保証金{d['hoshoukin_yen']}"
    if d.get("shoukyaku_yen") is not None:
        note += f" 敷引償却{d['shoukyaku_yen']}"

    con.execute("UPDATE listings SET rent_yen=COALESCE(?,rent_yen),"
                " admin_yen=COALESCE(?,admin_yen), shikikin=?, reikin=?,"
                " last_seen=datetime('now') WHERE id=?",
                (d["rent_yen"], d["admin_yen"],
                 None if d["deposit_yen"] is None else str(d["deposit_yen"]),
                 None if d["key_money_yen"] is None else str(d["key_money_yen"]),
                 lid))
    # 注意: 7054c2e でこの UPDATE が壊れていた（存在しないキー
    # shikikin_yen/reikin_yen を参照し KeyError、placeholder 数も不一致、
    # WHERE id=listings.id で別物件を更新しうる）。parse_detail の
    # deposit_yen/key_money_yen を使い、detail_url で引く正しい形に戻す。
    con.execute(
        "UPDATE properties SET rent_yen=COALESCE(?,rent_yen),"
        " admin_yen=COALESCE(?,admin_yen),"
        " total_yen=COALESCE(?,total_yen),"
        " shikikin_yen=COALESCE(?,shikikin_yen),"
        " reikin_yen=COALESCE(?,reikin_yen),"
        " equipment=?, has_bathtub=?, no_bathtub_evidence=?,"
        " direction=COALESCE(?,direction),"
        " structure=COALESCE(?,structure), floors=COALESCE(?,floors),"
        " scraped_at=datetime('now') WHERE detail_url=?",
        (d["rent_yen"], d["admin_yen"],
         (d["rent_yen"] or 0) + (d["admin_yen"] or 0) if d["rent_yen"] else None,
         d["deposit_yen"], d["key_money_yen"], d["equipment"], hb,
         (kw + " | " + d["equipment"])[:400],
         d.get("direction"), d.get("structure"), d.get("floors"),
         canonical_url(url)))
    con.execute("UPDATE units SET tub_status=?, tub_confidence=?,"
                " direction=COALESCE(?,direction) WHERE id=?",
                (status, conf, d["direction"], uid))
    # バスタブは部屋（ユニット）の属性なので、同一ユニットの別掲載
    # （他仲介 listings に紐づく properties）にも同じ判定を伝える。
    # 従来は掲載ごとに判定が食い違い、参照先で割れていた（61件）。
    con.execute("UPDATE properties SET has_bathtub=? WHERE detail_url IN"
                " (SELECT url FROM listings WHERE unit_id=?)", (hb, uid))
    # 詳細側の駅情報を stations へマージする（従来は parse しても
    # 捨てていた）。詳細の徒歩は一覧より正確なことが多く、一覧に
    # 無い駅も拾える。詳細値を正として既存行も更新する。
    for s in d.get("stations") or []:
        if not s.get("name"):
            continue
        con.execute("INSERT OR IGNORE INTO stations(unit_id,name,line,"
                    "walk_min) VALUES(?,?,?,?)",
                    (uid, s["name"], s.get("line") or "", s.get("walk")))
        if s.get("walk") is not None:
            con.execute("UPDATE stations SET walk_min=? WHERE unit_id=?"
                        " AND name=? AND line=?",
                        (s["walk"], uid, s["name"], s.get("line") or ""))
    near = con.execute("SELECT name, walk_min FROM stations"
                       " WHERE unit_id=? AND walk_min IS NOT NULL"
                       " ORDER BY walk_min LIMIT 1", (uid,)).fetchone()
    if near:
        con.execute("UPDATE properties SET station=?, walk_min=?"
                    " WHERE detail_url=?",
                    (near[0], near[1], canonical_url(url)))
    # 建物設備フラグ（言及がある場合のみ立てる。無言及は NULL のまま）
    equip = d.get("equipment") or ""
    bflags = {}
    if "オートロック" in equip:
        bflags["autolock"] = 1
    if "エレベーター" in equip:
        bflags["elevator"] = 1
    if "宅配ボックス" in equip or "宅配BOX" in equip:
        bflags["delivery_box"] = 1
    if bflags:
        bid = con.execute("SELECT building_id FROM units WHERE id=?",
                          (uid,)).fetchone()
        if bid:
            sets = ",".join(f"{k}=?" for k in bflags)
            con.execute(f"UPDATE buildings SET {sets} WHERE id=?",
                        (*bflags.values(), bid[0]))
    # 建物マスタへも構造・階数を反映する（従来は properties にしか
    # 書いておらず、buildings.structure が常時 NULL だった）
    if d.get("structure") or d.get("floors"):
        bid = con.execute("SELECT building_id FROM units WHERE id=?",
                          (uid,)).fetchone()
        if bid:
            con.execute("UPDATE buildings SET"
                        " structure=COALESCE(?,structure),"
                        " floors=COALESCE(?,floors) WHERE id=?",
                        (d.get("structure"),
                         str(d["floors"]) if d.get("floors") else None,
                         bid[0]))
    # SUUMO の実文言は「角住戸」が主流（「角部屋」だけ見ていたため
    # 該当735件のうち1件しか立っていなかった）
    if "角部屋" in equip or "角住戸" in equip:
        con.execute("UPDATE units SET corner=1 WHERE id=?", (uid,))
    con.execute("DELETE FROM listing_snapshots WHERE listing_id=?"
                " AND date(fetched_at)=date('now')", (lid,))
    con.execute("INSERT INTO listing_snapshots(listing_id,rent_yen,admin_yen,"
                "active,equip_text) VALUES(?,?,?,1,?)",
                (lid, d["rent_yen"], d["admin_yen"], d["equipment"][:2000]))
    con.execute("DELETE FROM evidence WHERE unit_id=? AND url=?"
                " AND method='detail_parse'", (uid, url))
    con.execute("INSERT INTO evidence(unit_id,tub_status,quote,url,method,"
                "confidence) VALUES(?,?,?,?,?,?)",
                (uid, status, (kw + " | " + d["equipment"][:400]), url,
                 "detail_parse", conf))
    # 設備テキストを amenities へ分解（従来は未投入で常に0件だった）
    # 設備でない長文（PR文・物件概要の塊が混入したケースがある）は
    # アメニティ名として登録しない。
    for name in (d.get("equipment") or "").replace(" ", "").split("、"):
        name = name.strip()
        if name and len(name) <= 20 and "。" not in name:
            con.execute("INSERT OR IGNORE INTO amenities(unit_id,name)"
                        " VALUES(?,?)", (uid, name))
    con.execute(
        "INSERT OR REPLACE INTO costs(listing_id,key_money_yen,deposit_yen,"
        "agency_yen,guarantee_first_yen,guarantee_renew_yen,insurance_yen,"
        "key_exchange_yen,cleaning_yen,support_yen,water_fixed_yen,"
        "renewal_fee_yen,contract_months,free_rent_months,regular_lease,"
        "fetched,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        (lid, d["key_money_yen"], d["deposit_yen"], d.get("agency_yen"),
         d["guarantee_first_yen"], d.get("guarantee_renew_yen"),
         d["insurance_yen"], d["key_exchange_yen"],
         d["cleaning_yen"], d["support_yen"], d["water_fixed_yen"],
         d["renewal_fee_yen"], d["contract_months"] or 24,
         d["free_rent_months"], d["regular_lease"], note[:500]))


def run(limit=50, sleep=5.0, jitter=2.0, only_missing=True, max_seconds=0,
        max_total=100000, walk_max=10):
    con = connect_db()
    rows = targets(con, limit, only_missing,
                   max_total=max_total, walk_max=walk_max)
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
    ap.add_argument("--max-total", type=int, default=100000,
                    help="優先取得する総額(賃料+管理費)の上限")
    ap.add_argument("--walk-max", type=int, default=10,
                    help="優先取得する最寄り駅までの徒歩分数")
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
        max_seconds=a.max_seconds, max_total=a.max_total,
        walk_max=a.walk_max)


if __name__ == "__main__":
    main()

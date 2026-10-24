"""通知: 新着/値下げ/礼金ゼロ/湯船確定/上位スコア (履歴付き・Discord)

送信に成功してから notifications へ記録する。失敗した通知は
記録されないので次回に再送される（従来は記録が先で、送信失敗が
欠落していた）。webhook 未設定時は表示のみで、記録は行う。
"""
import os
import sqlite3
from pathlib import Path
import urllib.request
import json

from models import score_unit

DB = Path(__file__).parent / "bukken.db"


def send_discord(msg):
    url = os.environ.get("DISCORD_WEBHOOK", "")
    if not url:
        print("[notify:discord unset]", msg[:200])
        return
    req = urllib.request.Request(
        url, json.dumps({"content": msg[:1800]}).encode(),
        {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def _already(con, lid, kind, msg=None):
    if msg is None:
        return con.execute(
            "SELECT 1 FROM notifications WHERE listing_id=? AND kind=?",
            (lid, kind)).fetchone()
    return con.execute(
        "SELECT 1 FROM notifications WHERE listing_id=? AND kind=?"
        " AND message=?", (lid, kind, msg)).fetchone()


def check(top_score=60):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    pending = []  # (listing_id, kind, message)

    # 新着(未通知・新しい順)
    for r in con.execute(
            "SELECT l.id, l.url, l.rent_yen FROM listings l"
            " LEFT JOIN notifications n ON n.listing_id=l.id"
            " AND n.kind='new'"
            " WHERE n.id IS NULL AND l.active=1"
            " ORDER BY l.first_seen DESC LIMIT 20"):
        pending.append((r["id"], "new", f"新着 {r['rent_yen']}円 {r['url']}"))

    # 値下げ（過去スナップショットの最高値から下がった分）
    for r in con.execute(
            """SELECT l.id, l.url, MAX(s.rent_yen) old, l.rent_yen new
               FROM listings l
               JOIN listing_snapshots s ON s.listing_id=l.id
               WHERE s.rent_yen>l.rent_yen AND l.active=1
               GROUP BY l.id LIMIT 20"""):
        msg = f"値下げ {r['old']}->{r['new']}円 {r['url']}"
        if not _already(con, r["id"], "drop", msg):
            pending.append((r["id"], "drop", msg))

    # 礼金ゼロ（詳細取得済みで礼金0が確定しているもの）
    for r in con.execute(
            """SELECT l.id, l.url FROM listings l
               JOIN costs c ON c.listing_id=l.id
               LEFT JOIN notifications n ON n.listing_id=l.id
               AND n.kind='zero'
               WHERE c.fetched=1 AND c.key_money_yen=0 AND l.active=1
               AND n.id IS NULL LIMIT 20"""):
        pending.append((r["id"], "zero", f"礼金ゼロ {r['url']}"))

    # 湯船確定
    for r in con.execute(
            """SELECT l.id, l.url FROM listings l
               JOIN units u ON u.id=l.unit_id
               LEFT JOIN notifications n ON n.listing_id=l.id
               AND n.kind='tub'
               WHERE u.tub_status='confirmed_no_tub' AND l.active=1
               AND n.id IS NULL LIMIT 20"""):
        pending.append((r["id"], "tub", f"湯船なし確定 {r['url']}"))

    # 上位スコア（rank と同じ材料で score_unit を計算）
    scored = []
    for r in con.execute(
            """SELECT l.id, l.url, l.rent_yen + l.admin_yen total,
               u.tub_status, u.area_m2 area, u.floor,
               (SELECT MIN(walk_min) FROM stations s
                WHERE s.unit_id=u.id) walk_min,
               b.autolock,
               (SELECT equip_text FROM listing_snapshots s
                WHERE s.listing_id=l.id
                ORDER BY s.fetched_at DESC LIMIT 1) equip,
               EXISTS(SELECT 1 FROM evidence e
                      WHERE e.unit_id=u.id) has_ev
               FROM listings l JOIN units u ON u.id=l.unit_id
               JOIN buildings b ON b.id=u.building_id
               WHERE l.active=1 AND l.rent_yen + l.admin_yen<=100000
               LIMIT 1000"""):
        sc, _ = score_unit(dict(
            total=r["total"], tub_status=r["tub_status"],
            walk_min=r["walk_min"], area=r["area"], floor=r["floor"],
            equip=r["equip"] or "", autolock=bool(r["autolock"]),
            missing=not r["has_ev"]))
        if sc >= top_score:
            scored.append((sc, r["id"], r["url"]))
    scored.sort(reverse=True)
    for sc, lid, url in scored[:10]:
        msg = f"高スコア {sc}点 {url}"
        if not _already(con, lid, "score", msg):
            pending.append((lid, "score", msg))
    con.close()

    # 送信できてから記録する
    con = sqlite3.connect(DB)
    sent = 0
    for lid, kind, msg in pending:
        try:
            send_discord(msg)
        except Exception as e:
            print(f"[notify send failed] {kind} listing={lid}: {e}")
            continue
        con.execute("INSERT INTO notifications(listing_id,kind,message)"
                    " VALUES(?,?,?)", (lid, kind, msg))
        sent += 1
        print(msg)
    con.commit()
    con.close()
    print(f"{sent} notifications")


if __name__ == "__main__":
    check()

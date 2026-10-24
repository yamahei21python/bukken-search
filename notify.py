"""通知: 新着/値下げ/礼金ゼロ/湯船確定/上位スコア (履歴付き・Discord/メール)"""
import os
import sqlite3
import smtplib
from email.message import EmailMessage
from pathlib import Path
import urllib.request
import json
DB = Path(__file__).parent / "bukken.db"

def send_discord(msg):
    url = os.environ.get("DISCORD_WEBHOOK", "")
    if not url:
        print("[notify:discord unset]", msg[:200])
        return
    req = urllib.request.Request(url, json.dumps({"content": msg[:1800]}).encode(),
                                 {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()

def check(top_score=60):
    con = sqlite3.connect(DB)
    out = []
    # 新着(未通知)
    for lid, url, rent in con.execute(
            "SELECT l.id,l.url,l.rent_yen FROM listings l LEFT JOIN notifications n"
            " ON n.listing_id=l.id AND n.kind='new'"
            " WHERE n.id IS NULL AND l.active=1 LIMIT 20"):
        msg = f"新着 {rent}円 {url}"
        con.execute("INSERT INTO notifications(listing_id,kind,message) VALUES(?, 'new', ?)", (lid, msg))
        out.append(msg)
    # 値下げ
    for lid, url, old, new in con.execute(
            """SELECT l.id,l.url,s.rent_yen,l.rent_yen FROM listings l
               JOIN listing_snapshots s ON s.listing_id=l.id
               WHERE s.rent_yen>l.rent_yen AND l.active=1
               GROUP BY l.id HAVING MAX(s.fetched_at) LIMIT 20"""):
        msg = f"値下げ {old}->{new}円 {url}"
        # 同じ値下げを毎回再送しない（new/tub と同じ重複防止）。
        # さらに値下がれば message が変わるので改めて通知される。
        if con.execute("SELECT 1 FROM notifications WHERE listing_id=?"
                       " AND kind='drop' AND message=?",
                       (lid, msg)).fetchone():
            continue
        con.execute("INSERT INTO notifications(listing_id,kind,message) VALUES(?, 'drop', ?)", (lid, msg))
        out.append(msg)
    # 湯船確定
    for lid, url in con.execute(
            """SELECT l.id,l.url FROM listings l JOIN units u ON u.id=l.unit_id
               LEFT JOIN notifications n ON n.listing_id=l.id AND n.kind='tub'
               WHERE u.tub_status='confirmed_no_tub' AND n.id IS NULL LIMIT 20"""):
        msg = f"湯船なし確定 {url}"
        con.execute("INSERT INTO notifications(listing_id,kind,message) VALUES(?, 'tub', ?)", (lid, msg))
        out.append(msg)
    con.commit(); con.close()
    for m in out:
        send_discord(m)
        print(m)
    print(f"{len(out)} notifications")

if __name__ == "__main__":
    check()

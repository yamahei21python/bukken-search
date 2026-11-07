"""3日以上一覧で見つからない active listing を inactive 化する。

背景: ユーザーが掲載終了済みの SUUMO ページ (jnc_000110298646) を
サイトで踏んだ。生きている物件は毎日の全駅スクレイプで全件
再確認されるため (active のほぼ全件が last_seen=今日)、3日以上
見つからないものは掲載終了と断定できる。

従来は 7日閾値だったため、最大7日間サイトに死んだリンクが残った。
- 詳細取得時は detail_scraper が掲載終了ページを検知して即 inactive 化
- 母集団 (サイト/app) は max_age_days=3 で二重に防ぐ
- この datafix で現行 DB の在庫を一括失効させる

使い方: python3 datafix/20261107-deactivate-dead/datafix.py bukken.db
idempotent: 再実行は 0 件変更。
"""
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
con = sqlite3.connect(db_path)

before = con.execute(
    "SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
cur = con.execute(
    "UPDATE listings SET active=0 WHERE active=1"
    " AND last_seen < datetime('now','-3 days')")
n = cur.rowcount
con.commit()
after = con.execute(
    "SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
print(f"before active={before} / deactivated={n} / after active={after}")

# 検証: ユーザーが踏んだ物件が inactive になっていること
row = con.execute(
    "SELECT active, last_seen FROM listings"
    " WHERE url='https://suumo.jp/chintai/jnc_000110298646/'").fetchone()
print(f"jnc_000110298646: active={row[0]} last_seen={row[1]}")
assert row[0] == 0, "指摘物件が inactive になっていない"
con.close()
print("OK")

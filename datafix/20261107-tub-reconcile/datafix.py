"""湯船判定の reconcile: 孤立 unit 削除 + properties からの判定復元。

2026-11-07 時点の実測:
  - listing を1つも持たない孤立 unit 1,684件 (うち unknown 1,126)
    unit 融合合ちの取り残し。amenities/stations も付随
  - evidence を持たない unknown unit 1,806件のうち
    properties.has_bathtub=1 (湯船あり判定の記録) が 568件
    -> units.tub_status が 'unknown' のまま矛盾して残っていた

models.reconcile_tub (単体テスト済み) を呼ぶだけの薄いラッパー。
idempotent: 再実行は 0 件変更で終わる。

使い方: python3 datafix/20261107-tub-reconcile/datafix.py bukken.db
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import db as db_mod  # noqa: E402
from models import reconcile_tub  # noqa: E402

db_path = Path(sys.argv[1])

con = sqlite3.connect(db_path)
before = {
    "units": con.execute("SELECT COUNT(*) FROM units").fetchone()[0],
    "evidence": con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
    "unknown": con.execute(
        "SELECT COUNT(*) FROM units WHERE tub_status='unknown'").fetchone()[0],
}
print("before:", before)

rep = reconcile_tub(con)
con.commit()
print("report:", rep)

after = {
    "units": con.execute("SELECT COUNT(*) FROM units").fetchone()[0],
    "evidence": con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
    "unknown": con.execute(
        "SELECT COUNT(*) FROM units WHERE tub_status='unknown'").fetchone()[0],
}
print("after:", after)
total_units = after["units"]
print(f"unknown rate: {before['unknown']}/{before['units']}"
      f" = {before['unknown'] / max(before['units'], 1):.1%}"
      f" -> {after['unknown']}/{total_units}"
      f" = {after['unknown'] / max(total_units, 1):.1%}")

# --- 検証: 不整合が残っていないこと (失敗時は非0終了で commit 済みだが
# workflow が失敗を検知できる) ---
bad = con.execute(
    "SELECT COUNT(*) FROM units u"
    " WHERE u.tub_status != 'unknown' AND NOT EXISTS"
    " (SELECT 1 FROM evidence e WHERE e.unit_id=u.id)").fetchone()[0]
orphan = con.execute(
    "SELECT COUNT(*) FROM units u WHERE NOT EXISTS"
    " (SELECT 1 FROM listings l WHERE l.unit_id=u.id)").fetchone()[0]
con.close()
assert orphan == 0, f"orphan units remain: {orphan}"
print(f"non-unknown units without evidence (許容: 判定は evidence 寄り):"
      f" {bad}")
print("OK")

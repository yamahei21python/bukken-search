"""F9: costs.renewal_admin_fee_yen の追加と既存行の backfill。

1. カラムが無ければ ALTER TABLE で追加する（db.py の _COSTS_COLUMNS と
   同じ移行。次回 scrape の initialize_db でも冪等に追加される）。
2. 詳細取得済みで備考（costs.note）に「更新事務手数料」の金額がある行は、
   パーサ本体の _labeled_yen と同じ規則（家賃×3 ガード付き）で値を埋める。
3. 検証: カラムの存在、backfill 対象全行で「保存値 == 備考からの再計算値」
   が一致すること、integrity_check。失敗時は ROLLBACK して非ゼロ終了。

Usage: python3 datafix.py <path-to-bukken.db>
冪等: 再実行では ALTER はスキップされ、UPDATE は変化なしになる。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parse_suumo import _labeled_yen  # noqa: E402

db_path = sys.argv[1]
con = sqlite3.connect(db_path, isolation_level=None)

cols = {r[1] for r in con.execute("PRAGMA table_info(costs)")}
print(f"column present before: {'renewal_admin_fee_yen' in cols}")

con.execute("BEGIN IMMEDIATE")
try:
    if "renewal_admin_fee_yen" not in cols:
        con.execute(
            "ALTER TABLE costs ADD COLUMN renewal_admin_fee_yen INTEGER")
        print("ALTER TABLE: added renewal_admin_fee_yen")
    rows = con.execute(
        "SELECT c.listing_id, c.note, l.rent_yen, c.renewal_admin_fee_yen"
        " FROM costs c JOIN listings l ON l.id = c.listing_id"
        " WHERE c.fetched = 1 AND c.note LIKE '%更新事務手数料%'").fetchall()
    changed = 0
    problems = []
    for lid, note, rent, current in rows:
        v = _labeled_yen(note or "", r"更新事務手数料", rent)
        if v is not None and rent and v > rent * 3:
            v = None
        if v is None:
            problems.append((lid, "label present but unparseable"))
            continue
        if current is None:
            con.execute(
                "UPDATE costs SET renewal_admin_fee_yen = ?"
                " WHERE listing_id = ?", (v, lid))
            changed += 1
            print(f"  backfill listing {lid}: NULL -> {v}")
        elif current != v:
            problems.append((lid, f"stored {current} != parsed {v}"))
    total = con.execute(
        "SELECT COUNT(*) FROM costs"
        " WHERE renewal_admin_fee_yen IS NOT NULL").fetchone()[0]
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"backfilled: {changed}; nonnull total: {total}; "
          f"problems: {problems}; integrity: {integrity}")
    if problems or integrity != "ok":
        con.execute("ROLLBACK")
        print("VERIFICATION FAILED — rolled back")
        sys.exit(1)
except Exception:
    con.execute("ROLLBACK")
    raise
con.execute("COMMIT")
print("DONE")

"""DB作り直し: 既存 bukken.db を安全に再構築する（データは消さない）。

やること:
  1. 元DBをタイムスタンプ付きでバックアップ
  2. スキーマ初期化（db.initialize_db）で不足テーブル/一意インデックスを補い、
     evidence / listing_snapshots の重複行を整理
  3. 陳腐化した listings を active=0 化（--stale-days、既定7日）
  4. VACUUM で肥大化したファイルを圧縮
  5. 前後の件数と監査サマリを表示（db_audit を併用）

使い方:
  python3 rebuild_db.py                 # bukken.db を再構築
  python3 rebuild_db.py --db other.db --stale-days 10
  python3 rebuild_db.py --dry-run       # バックアップも変更もしない
"""
import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from db import DB, initialize_db


def counts(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out = {}
    for t in ("buildings", "units", "listings", "properties", "costs",
              "evidence", "listing_snapshots"):
        try:
            out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error as e:
            out[t] = f"ERR: {e}"
    try:
        out["active_listings"] = con.execute(
            "SELECT COUNT(*) FROM listings WHERE active=1").fetchone()[0]
    except sqlite3.Error:
        pass
    con.close()
    return out


def main():
    ap = argparse.ArgumentParser(description="bukken.db 再構築")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--stale-days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.db.exists():
        raise SystemExit(f"DB not found: {a.db}")

    before = counts(a.db)
    size_before = a.db.stat().st_size
    print(f"before: {before} size={size_before / 1e6:.1f}MB")
    if a.dry_run:
        print("dry-run: no changes")
        return

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = a.db.with_name(f"{a.db.stem}_backup_{stamp}.db")
    # WAL の未チェックポイント分がバックアップから漏れないよう、
    # コピー前にチェックポイントを済ませる
    _con = sqlite3.connect(a.db)
    try:
        _con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        _con.commit()
    finally:
        _con.close()
    shutil.copy2(a.db, backup)
    print(f"backup: {backup}")

    # initialize_db は db.DB 固定なので、対象が別の場合は一時的に差し替える
    import db as db_mod
    orig = db_mod.DB
    db_mod.DB = a.db
    try:
        initialize_db(rebuild=False)
    finally:
        db_mod.DB = orig

    con = sqlite3.connect(a.db)
    cur = con.execute(
        "UPDATE listings SET active=0 WHERE active=1"
        " AND last_seen < datetime('now',?)",
        (f"-{a.stale_days} days",))
    print(f"deactivated stale: {cur.rowcount}")
    con.commit()
    con.execute("VACUUM")
    con.close()

    after = counts(a.db)
    size_after = a.db.stat().st_size
    print(f"after:  {after} size={size_after / 1e6:.1f}MB")


if __name__ == "__main__":
    main()

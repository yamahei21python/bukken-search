"""SQLite接続とSUUMO取込用スキーマの共通処理。"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "bukken.db"
_ROOT = Path(__file__).parent

PROPERTIES_DDL = """
CREATE TABLE IF NOT EXISTS properties(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, address TEXT, station TEXT, walk_min INTEGER,
  age_years INTEGER, room_floor INTEGER,
  rent_yen INTEGER, admin_yen INTEGER, total_yen INTEGER,
  shikikin_yen INTEGER, reikin_yen INTEGER,
  layout TEXT, area_m2 REAL, direction TEXT, structure TEXT, floors INTEGER,
  detail_url TEXT UNIQUE, equipment TEXT, has_bathtub INTEGER,
  no_bathtub_evidence TEXT,
  scraped_at TEXT DEFAULT (datetime('now','localtime')));
"""

_PROPERTY_COLUMNS = [
    ("station", "TEXT"), ("shikikin_yen", "INTEGER"),
    ("reikin_yen", "INTEGER"), ("direction", "TEXT"),
    ("structure", "TEXT"), ("floors", "INTEGER"),
]


def connect_db() -> sqlite3.Connection:
    """共通DB接続。呼び出し側がcommit/closeを管理。"""
    return sqlite3.connect(DB)


def initialize_db(rebuild: bool = False) -> None:
    """正規化テーブルと互換propertiesを初期化。"""
    con = connect_db()
    try:
        if rebuild:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                con.execute(f"DROP TABLE IF EXISTS {table}")
        con.executescript((_ROOT / "schema.sql").read_text())
        con.executescript(PROPERTIES_DDL)
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stations_uniq "
                    "ON stations(unit_id,name,line)")
        columns = {row[1] for row in con.execute("PRAGMA table_info(properties)")}
        for name, kind in _PROPERTY_COLUMNS:
            if name not in columns:
                con.execute(f"ALTER TABLE properties ADD COLUMN {name} {kind}")
        con.commit()
    finally:
        con.close()

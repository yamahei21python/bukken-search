"""Apply and verify the 2026-10-26 D3 datafix (guarantee_first tiny values).

The mutation and verification logic lives only in datafix.sql (single source
of truth). This runner:
  1. reads the APPLY statements and CHECK queries out of datafix.sql,
  2. logs the target values before,
  3. runs BEGIN IMMEDIATE -> APPLY (logging changes() per statement)
     -> every CHECK -> PRAGMA integrity_check,
  4. COMMITs only if all checks pass; on any failure it ROLLBACKs and
     exits non-zero without committing.

Usage: python3 datafix.py <path-to-bukken.db> [path-to-datafix.sql]
Idempotent: a re-run must log changes=0 for every APPLY and still pass.
"""
import re
import sqlite3
import sys
from pathlib import Path

db_path = sys.argv[1]
sql_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name("datafix.sql")
sql = sql_path.read_text(encoding="utf-8")

applies = []  # (label, statement)
for m in re.finditer(r"-- APPLY (\S+)\n(UPDATE .*?;)", sql, re.S):
    applies.append((m.group(1), m.group(2)))
checks = []  # (name, expected, query)
for m in re.finditer(r"-- CHECK (\S+) expect: (\S+)\n(SELECT .*?;)", sql, re.S):
    checks.append((m.group(1), m.group(2), m.group(3)))
if not applies or not checks:
    sys.exit("could not parse datafix.sql")


def fmt(v):
    return "NULL" if v is None else str(v)


def run_checks(con, phase):
    ok = True
    for name, expected, q in checks:
        rows = con.execute(q).fetchall()
        got = fmt(rows[0][0]) if len(rows) == 1 else f"<{len(rows)} rows>"
        status = "ok" if got == expected else "MISMATCH"
        if got != expected:
            ok = False
        print(f"  [{phase}] {name}: {got} (expect {expected}) {status}")
    return ok


con = sqlite3.connect(db_path, isolation_level=None)
print(f"== before ({db_path}) ==")
run_checks(con, "before")
print("== apply ==")
con.execute("BEGIN IMMEDIATE")
try:
    for label, stmt in applies:
        cur = con.execute(stmt)
        print(f"  {label}: changes={cur.rowcount}")
    print("== verify (in transaction) ==")
    passed = run_checks(con, "verify")
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"  integrity_check: {integrity}")
    passed = passed and integrity == "ok"
except Exception:
    con.execute("ROLLBACK")
    raise
if not passed:
    con.execute("ROLLBACK")
    print("VERIFICATION FAILED — rolled back, nothing committed")
    sys.exit(1)
con.execute("COMMIT")
print("== after (committed) ==")
run_checks(con, "after")
con.close()
print("DONE")

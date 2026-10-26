"""Final cleanup pass after the 2026-10-26 audit fixes (F1–F10 + deferred).

Does, in order:
  1. db.initialize_db — the repo's own maintenance (schema completion,
     evidence/snapshot dedup, ADD/DROP column migrations; this is what
     physically drops the dead evidence.photo_url column).
  2. Deletes station rows that violate the F7 outlier rule
     (walk > unit's minimum walk + 30) — rows the fixed parser/saver
     would never write today.
  3. Deactivates stale listings (last_seen > 7 days, rebuild_db parity).
  4. Verifies the §8 battery + spot values from D1/D2/D3/F9/geocode.
     Any failure exits non-zero BEFORE vacuum/commit, so the workflow
     does not commit a bad state.
  5. VACUUM.

Usage: python3 datafix.py <path-to-bukken.db>
Idempotent: a re-run changes nothing and still verifies clean.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import db as db_mod  # noqa: E402

db_path = Path(sys.argv[1])


def counts(con):
    out = {}
    for t in ("buildings", "units", "listings", "properties", "costs",
              "stations", "evidence"):
        out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return out


con = sqlite3.connect(db_path)
print("before:", counts(con))
con.close()

# 1. repo-standard initialization / migrations
orig = db_mod.DB
db_mod.DB = db_path
try:
    db_mod.initialize_db(rebuild=False)
finally:
    db_mod.DB = orig
print("initialize_db done (photo_url drop + dedup + column migrations)")

con = sqlite3.connect(db_path, isolation_level=None)
# 2. F7 outlier stations
rows = con.execute(
    "SELECT id, unit_id, name, walk_min FROM stations"
    " WHERE walk_min IS NOT NULL ORDER BY unit_id, walk_min").fetchall()
from collections import defaultdict
by_unit = defaultdict(list)
for r in rows:
    by_unit[r[1]].append(r)
deleted = []
con.execute("BEGIN IMMEDIATE")
for uid, ss in by_unit.items():
    if len(ss) < 2:
        continue
    mn = ss[0][3]
    for sid, _, name, w in ss:
        if w > mn + 30:
            con.execute("DELETE FROM stations WHERE id=?", (sid,))
            deleted.append((uid, name, w, mn))
con.execute("COMMIT")
for d in deleted:
    print(f"  outlier station deleted: unit {d[0]} {d[1]} {d[2]}min"
          f" (unit min {d[3]}min)")
print(f"outlier stations deleted: {len(deleted)}")

# 3. stale deactivation (rebuild_db parity)
cur = con.execute(
    "UPDATE listings SET active=0 WHERE active=1"
    " AND last_seen < datetime('now','-7 days')")
print(f"stale deactivated: {cur.rowcount}")

# 4. verification battery
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got} (expect {want})")
    if not ok:
        fails.append(label)


check("integrity", con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
check("photo_url dropped",
      "photo_url" in [r[1] for r in con.execute("PRAGMA table_info(evidence)")],
      False)
check("giant shikikin/reikin",
      con.execute("SELECT COUNT(*) FROM properties WHERE rent_yen > 0"
                  " AND (shikikin_yen > rent_yen*12"
                  "      OR reikin_yen > rent_yen*12)").fetchone()[0], 0)
check("guarantee_renew >= 100000",
      con.execute("SELECT COUNT(*) FROM costs"
                  " WHERE guarantee_renew_yen >= 100000").fetchone()[0], 0)
check("renewal_fee > rent*3",
      con.execute("SELECT COUNT(*) FROM costs c JOIN listings l"
                  " ON l.id = c.listing_id"
                  " WHERE c.renewal_fee_yen > l.rent_yen * 3").fetchone()[0], 0)
check("'None' strings",
      con.execute("SELECT (SELECT COUNT(*) FROM listings"
                  " WHERE shikikin='None' OR reikin='None')"
                  " + (SELECT COUNT(*) FROM properties"
                  " WHERE typeof(shikikin_yen)='text'"
                  "    OR typeof(reikin_yen)='text')").fetchone()[0], 0)
check("outlier stations remaining",
      con.execute(
          "SELECT COUNT(*) FROM stations s WHERE s.walk_min IS NOT NULL"
          " AND s.walk_min > 30 + (SELECT MIN(s2.walk_min) FROM stations s2"
          " WHERE s2.unit_id = s.unit_id AND s2.walk_min IS NOT NULL)"
          ).fetchone()[0], 0)
check("D1 9743 shikikin NULL",
      con.execute("SELECT shikikin_yen FROM properties"
                  " WHERE detail_url="
                  " 'https://suumo.jp/chintai/jnc_000110356595/'"
                  ).fetchone()[0], None)
check("D3 920 guarantee_first",
      con.execute("SELECT c.guarantee_first_yen FROM costs c"
                  " JOIN listings l ON l.id = c.listing_id"
                  " WHERE l.url="
                  " 'https://suumo.jp/chintai/jnc_000110459926/'"
                  ).fetchone()[0], 10000)
check("F9 renewal_admin rows",
      con.execute("SELECT COUNT(*) FROM costs"
                  " WHERE renewal_admin_fee_yen IS NOT NULL"
                  ).fetchone()[0], 35)
check("geocoded buildings",
      con.execute("SELECT COUNT(*) FROM buildings WHERE lat IS NOT NULL"
                  ).fetchone()[0],
      con.execute("SELECT COUNT(*) FROM buildings").fetchone()[0])
print("after:", counts(con))
con.close()
if fails:
    print(f"VERIFICATION FAILED: {fails} — exiting non-zero, no commit")
    sys.exit(1)

# 5. VACUUM (outside any transaction)
con = sqlite3.connect(db_path, isolation_level=None)
con.execute("VACUUM")
con.close()
print("DONE")

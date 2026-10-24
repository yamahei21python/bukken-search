"""選別クエリ: python3 filter.py --max-rent 70000 --no-bathtub --walk-max 10 --sort total"""
import argparse, sqlite3
from pathlib import Path
DB = Path(__file__).parent / "bukken.db"
ap = argparse.ArgumentParser()
ap.add_argument("--max-rent", type=int, default=70000)
ap.add_argument("--include-admin", action="store_true", help="管理費込みで判定")
ap.add_argument("--no-bathtub", action="store_true",
                help="湯船なし（likely含む。properties.has_bathtub=0 で判定）")
ap.add_argument("--no-bathtub-confirmed", action="store_true",
                help="湯船なし確定のみ（units.tub_status で判定）")
ap.add_argument("--walk-max", type=int, default=None)
ap.add_argument("--max-age", type=int, default=None)
ap.add_argument("--min-area", type=float, default=None)
ap.add_argument("--sort", default="total", choices=["total", "rent", "walk", "area", "age"])
a = ap.parse_args()
col = "total_yen" if a.include_admin else "rent_yen"
q = f"SELECT name,rent_yen,admin_yen,total_yen,layout,area_m2,walk_min,age_years,has_bathtub,detail_url FROM properties WHERE {col}<=? "
params = [a.max_rent]
if a.no_bathtub:
    q += "AND has_bathtub=0 "
if a.no_bathtub_confirmed:
    q += ("AND detail_url IN (SELECT l.url FROM listings l"
          " JOIN units u ON u.id=l.unit_id"
          " WHERE u.tub_status='confirmed_no_tub') ")
if a.walk_max is not None:
    q += "AND walk_min<=? "
    params.append(a.walk_max)
if a.max_age is not None:
    q += "AND age_years<=? "
    params.append(a.max_age)
if a.min_area is not None:
    q += "AND area_m2>=? "
    params.append(a.min_area)
sortmap = {"total": "total_yen", "rent": "rent_yen", "walk": "walk_min", "area": "area_m2 DESC", "age": "age_years"}
q += f"ORDER BY {sortmap[a.sort]} LIMIT 50"
con = sqlite3.connect(DB)
rows = con.execute(q, params).fetchall()
print(f"hit: {len(rows)}")
for r in rows:
    print(f"{r[1]/10000:.1f}万(+{r[2]}) {r[4]} {r[5]}m2 歩{r[6]}分 築{r[7]}年 bath={r[8]} | {r[0]} | {r[9]}")

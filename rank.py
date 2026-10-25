"""選別CLI: 実質月額・2年総額・スコア付きランキング"""
import argparse
import sqlite3
from pathlib import Path
from models import effective_monthly, total_2year, score_unit
DB = Path(__file__).parent / "bukken.db"
ap = argparse.ArgumentParser()
ap.add_argument("--max-total", type=int, default=100000)
ap.add_argument("--tub", nargs="*", default=["confirmed_no_tub", "likely_no_tub", "unknown"])
ap.add_argument("--walk-max", type=int, default=10)
ap.add_argument("--allow-unknown-walk", action="store_true",
                help="徒歩不明を含める(既定は除外)")
ap.add_argument("--min-area", type=float, default=0)
a = ap.parse_args()
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute(
    """SELECT b.name, b.norm_address, b.autolock, l.rent_yen rent, l.admin_yen admin,
       u.layout, u.area_m2 area, u.floor, u.tub_status,
       (SELECT MIN(walk_min) FROM stations s WHERE s.unit_id=u.id) walk_min,
       c.water_fixed_yen water, c.support_yen sup,
       c.support_monthly_yen supm, c.guarantee_renew_yen gren,
       c.renewal_fee_yen rf, c.contract_months cm,
       c.key_money_yen km, c.deposit_yen dep, c.agency_yen ag,
       c.guarantee_first_yen gf, c.insurance_yen ins, c.key_exchange_yen kx,
       c.cleaning_yen cl, c.free_rent_months fr, c.fetched fetched, l.url,
       (SELECT quote FROM evidence e WHERE e.unit_id=u.id ORDER BY e.checked_at DESC LIMIT 1) ev,
       (SELECT equip_text FROM listing_snapshots s WHERE s.listing_id=l.id
         ORDER BY s.fetched_at DESC LIMIT 1) equip
       FROM listings l JOIN units u ON u.id=l.unit_id
       JOIN buildings b ON b.id=u.building_id
       LEFT JOIN costs c ON c.listing_id=l.id WHERE l.active=1""").fetchall()
hits = []
for r in rows:
    total = (r["rent"] or 0) + (r["admin"] or 0)
    if total > a.max_total:
        continue
    if r["tub_status"] not in a.tub:
        continue
    if r["walk_min"] is None:
        if not a.allow_unknown_walk:
            continue
    elif r["walk_min"] > a.walk_max:
        continue
    if (r["area"] or 0) < a.min_area:
        continue
    nonrefund = (r["km"] or 0) + (r["ag"] or 0) + (r["gf"] or 0) \
        + (r["ins"] or 0) + (r["kx"] or 0) + (r["cl"] or 0)
    init_total = nonrefund + (r["dep"] or 0)
    fetched = r["fetched"] if "fetched" in r.keys() else 0
    eff = effective_monthly(r["rent"], r["admin"], r["water"], 0,
                            r["gren"], r["rf"], r["cm"] or 24, nonrefund,
                            support_monthly=r["supm"])
    t2 = total_2year(r["rent"], r["admin"], init_total, r["rf"],
                     r["gren"], r["fr"], support_once=r["sup"],
                     support_monthly=r["supm"], contract_months=r["cm"])
    missing = r["walk_min"] is None or not r["ev"]
    sc, reasons = score_unit(dict(total=total, tub_status=r["tub_status"],
                                  walk_min=r["walk_min"], area=r["area"],
                                  floor=r["floor"], equip=r["equip"] or "",
                                  autolock=bool(r["autolock"]),
                                  missing=missing))
    hits.append((sc, eff, dict(r) | {"total": total, "t2": t2,
                                     "init": init_total, "reasons": reasons,
                                     "fetched": fetched}))
hits.sort(key=lambda x: (x[0], -x[1]), reverse=True)
print(f"hit: {len(hits)} (*=初期未取得のため2年総額は暫定)")
for sc, eff, h in hits[:50]:
    fetched = h.get("fetched", 0) or 0
    init_str = f"初期{h['init']/10000:.1f}万" if fetched else "初期未取得"
    print(f"[{sc}点] 実質{eff/10000:.2f}万 総額{h['total']/10000:.1f}万 "
          f"{init_str} 2年{h['t2']/10000:.0f}万{'*' if not fetched else ''} "
          f"{h['layout']} {h['area']}m2 歩{h['walk_min']}分 {h['tub_status']} | {h['name']} | {h['url']}")
    print(f"   ev: {(h['ev'] or '')[:100]}")

"""阿波座＋周辺駅 賃貸スクレイパー + SQLite DB
SUUMO 複数駅(config.yaml の ek_codes)の一覧→詳細を巡回しDB化する。
使い方:
  python3 scraper.py --max-pages 3                 # configの全駅
  python3 scraper.py --stations 阿波座 本町 --max-pages 2
"""
import argparse, re, sqlite3, time
from pathlib import Path
import requests
import yaml
from bs4 import BeautifulSoup

BASE = "https://suumo.jp"
CFG = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))
EK_CODES = CFG["ek_codes"]  # {駅名: ek_xxxxx}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DB = Path(__file__).parent / "bukken.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, address TEXT, walk_min INTEGER, station TEXT,
  age_years INTEGER, room_floor INTEGER,
  rent_yen INTEGER, admin_yen INTEGER, total_yen INTEGER,
  shikikin_yen INTEGER, reikin_yen INTEGER,
  layout TEXT, area_m2 REAL,
  detail_url TEXT UNIQUE,
  equipment TEXT, has_bathtub INTEGER,
  no_bathtub_evidence TEXT,
  scraped_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

def init_db():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    # 既存DBのカラム追加（station / shikikin_yen / reikin_yen）
    cols = [c[1] for c in con.execute("PRAGMA table_info(properties)")]
    for col, typ in [("station", "TEXT"), ("shikikin_yen", "INTEGER"), ("reikin_yen", "INTEGER")]:
        if col not in cols:
            con.execute(f"ALTER TABLE properties ADD COLUMN {col} {typ}")
    con.commit(); con.close()

def parse_yen(s):
    if not s:
        return None
    s = s.strip().replace(",", "")
    m = re.search(r"([\d.]+)万円", s)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d+)円", s)
    if m:
        return int(m.group(1))
    return 0 if ("-" in s or "−" in s) else None

def list_url(page=1, chinryo_max_man=7, ek="ek_01690"):
    u = f"{BASE}/chintai/osaka/{ek}/?fr_chinryomax={chinryo_max_man}"
    if page > 1:
        u += f"&page={page}"
    return u

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")
def parse_list(soup, station="阿波座"):
    out = []
    # 徒歩分数は「○○駅 歩X分」を全て拾い、最寄り=最小のものを採用
    for cassette in soup.select(".cassetteitem"):
        head = cassette.select_one(".cassetteitem_content-title")
        name = head.get_text(strip=True) if head else ""
        # SUUMOカセットヘッダの「路線+駅+階建+築年」混入を除去
        for pat in CFG.get("building_name_strip_patterns", []):
            name = re.sub(pat, "", name).strip()
        addr = cassette.select_one(".cassetteitem_detail-col1")
        address = addr.get_text(" ", strip=True) if addr else ""
        dt = cassette.get_text(" ", strip=True)
        walks = [int(x) for x in re.findall(r"駅\s*歩(\d+)分", dt)]
        walk = min(walks) if walks else None
        ma = re.search(r"築(\d+)年", dt)
        age = int(ma.group(1)) if ma else (0 if "新築" in dt else None)
        for row in cassette.select(".cassetteitem_other tbody tr.js-cassette_link"):
            cols = [c.get_text(" ", strip=True) for c in row.select("td")]
            cols = [c for c in cols if c != ""]  # 空td除去
            durl = None
            for a in row.select("a[href]"):
                h = a.get("href", "")
                if "/chintai/jnc_" in h or "bc=" in h:
                    durl = h if h.startswith("http") else BASE + h
                    break
            fl = None
            if cols and re.search(r"(\d+)階", cols[0]):
                fl = int(re.search(r"(\d+)階", cols[0]).group(1))
            rent = parse_yen(cols[1] if len(cols) > 1 else "")
            admin = None
            if len(cols) > 1:
                ms = re.findall(r"([\d.]+万円|\d+円|-)", cols[1])
                if len(ms) >= 2:
                    admin = parse_yen(ms[1])
            # 敷金/礼金（cols[2] 例: "9.3万円 11.8万円" / "- 9.3万円"）
            shiki = rei = None
            if len(cols) > 2:
                sm = re.findall(r"([\d.]+万円|\d+円|-)", cols[2])
                if len(sm) >= 1:
                    shiki = parse_yen(sm[0])
                if len(sm) >= 2:
                    rei = parse_yen(sm[1])
            lm = re.search(r"(ワンルーム|\d[SLDK]+)", " ".join(cols))
            layout = lm.group(1) if lm else ""
            am = re.search(r"([\d.]+)m", " ".join(cols))
            area = float(am.group(1)) if am else None
            out.append(dict(name=name, address=address, walk_min=walk,
                            station=station,
                            age_years=age, room_floor=fl, rent_yen=rent,
                            admin_yen=admin, total_yen=(rent or 0) + (admin or 0),
                            shikikin_yen=shiki, reikin_yen=rei,
                            layout=layout, area_m2=area, detail_url=durl))
    return out

SHOWER_ONLY = ["シャワーのみ", "シャワールーム", "シャワーブース",
               "バスなし", "浴室なし", "湯船なし"]

def judge_bath(t):
    t = t or ""
    for kw in SHOWER_ONLY:
        if kw in t:
            return 0, kw
    for kw in ["浴槽", "湯船", "追い焚", "追焚", "バスタブ",
               "ユニットバス", "バス・トイレ別", "バストイレ別"]:
        if kw in t:
            return 1, kw
    return -1, ""

def fetch_detail(url, sleep=1.0):
    time.sleep(sleep)
    try:
        soup = fetch(url)
    except Exception as e:
        return "", -1, "fetch_error:" + str(e)[:100]
    feat = ""
    for h in soup.find_all(["h2", "h3"]):
        if "部屋の特徴" in h.get_text() or "設備" in h.get_text():
            feat = h.parent.get_text(" ", strip=True)
            break
    if not feat:
        feat = " ".join([t.get_text(" ", strip=True)
                         for t in soup.select("table")])
    hb, kw = judge_bath(feat)
    m = re.search(r".{0,60}(シャワー|浴槽|湯船|バス|浴室).{0,60}", feat)
    ev = m.group(0)[:300] if m else feat[:300]
    return feat[:4000], hb, (kw + " | " + ev)[:500]

def save(rows):
    """旧properties＋新スキーマの両方へ保存(新DBが正本)。"""
    con = sqlite3.connect(DB)
    for r in rows:
        try:
            con.execute("""INSERT OR REPLACE INTO properties
            (name,address,walk_min,station,age_years,room_floor,rent_yen,
             admin_yen,total_yen,shikikin_yen,reikin_yen,layout,area_m2,detail_url,
             equipment,has_bathtub,no_bathtub_evidence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r.get("name"), r.get("address"), r.get("walk_min"),
             r.get("station", "阿波座"),
             r.get("age_years"), r.get("room_floor"), r.get("rent_yen"),
             r.get("admin_yen"), r.get("total_yen"), r.get("shikikin_yen"),
             r.get("reikin_yen"), r.get("layout"),
             r.get("area_m2"), r.get("detail_url"),
             r.get("equipment", ""), r.get("has_bathtub", -1),
             r.get("no_bathtub_evidence", "")))
        except Exception as e:
            print("save error", e)
    con.commit(); con.close()
    try:
        import migrate as _m
        _m.migrate()
        # stations補完(旧→新でwalkが落ちた分)
        c2 = sqlite3.connect(DB)
        n = 0
        pcols = [c[1] for c in c2.execute("PRAGMA table_info(properties)")]
        has_station_col = "station" in pcols
        for bname, walk, floor, area, layout, stn in c2.execute(
                "SELECT name,walk_min,room_floor,area_m2,layout,"
                + ("station" if has_station_col else "'阿波座'")
                + " FROM properties WHERE walk_min IS NOT NULL"):
            nn = _m.norm_name(bname)
            b = c2.execute("SELECT id FROM buildings WHERE norm_name=?", (nn,)).fetchone()
            if not b:
                continue
            u = c2.execute("SELECT id FROM units WHERE building_id=? AND "
                           "(floor IS ? OR floor=?) AND layout=? AND abs(area_m2-?)<=0.3",
                           (b[0], floor, floor, layout, area or 0)).fetchone()
            if u and not c2.execute(
                    "SELECT 1 FROM stations WHERE unit_id=? AND name=?",
                    (u[0], stn or "阿波座")).fetchone():
                c2.execute("INSERT INTO stations(unit_id,name,walk_min) VALUES(?,?,?)",
                           (u[0], stn or "阿波座", walk))
                n += 1
        c2.commit(); c2.close()
        print(f"migrated to new schema (+{n} stations)")
    except Exception as e:
        print("migrate skip:", str(e)[:150])

def main():
    import argparse as ap_m
    ap = ap_m.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--chinryo-max", type=int, default=10)
    ap.add_argument("--stations", nargs="*", default=None,
                    help="駅名の指定。省略時はconfig.yamlの全駅")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--detail-limit", type=int, default=30)
    a = ap.parse_args()
    init_db()
    targets = a.stations or list(EK_CODES.keys())
    all_rows = []
    for stn in targets:
        ek = EK_CODES.get(stn)
        if not ek:
            print(f"[skip] unknown station: {stn}")
            continue
        for p in range(1, a.max_pages + 1):
            url = list_url(p, a.chinryo_max, ek)
            print(f"[list] {stn} p{p}: {url}")
            try:
                soup = fetch(url)
            except Exception as e:
                print(" list fetch error:", str(e)[:100])
                break
            rows = parse_list(soup, station=stn)
            print(f"  -> {len(rows)} rooms")
            if not rows:
                break
            all_rows.extend(rows)
            time.sleep(1.2)
    if a.detail:
        for r in all_rows[:a.detail_limit]:
            if not r.get("detail_url"):
                continue
            eq, hb, ev = fetch_detail(r["detail_url"])
            r["equipment"] = eq
            r["has_bathtub"] = hb
            r["no_bathtub_evidence"] = ev
            print("  detail %s %s bath=%s" % (r["name"], r["rent_yen"], hb))
    save(all_rows)
    print("saved/fetched %d -> %s" % (len(all_rows), DB))

if __name__ == "__main__":
    main()


"""SUUMO HTMLパーサ（20物件サンプルで規則を検証済み）。

一覧ページ (.cassetteitem):
  td は固定位置。先頭2列は空。2=階 3=賃料/管理費 4=敷金/礼金 5=間取り/専有面積。
  空セルを除去してインデックス参照してはいけない（桁ズレの原因）。
  駅は「路線/駅 歩N分」が複数並ぶ。最寄りは最小徒歩。

詳細ページ:
  価格  = .property_view_note-info （note-list が 賃料/管理費 と 敷金/礼金 の2つに分かれる）
  建物  = table.table_gaiyou （間取り詳細/構造/階建/築年月/損保/契約期間/保証会社/ほか初期費用 or ほか諸費用）
  アクセス = .property_view_table （所在地/駅徒歩/間取り/専有面積/築年数/階/向き/建物種別）
  設備  = 「部屋の特徴・設備」見出しの親要素

値の欠落・表記ゆれ:
  契約期間/保証会社/ほか初期費用は欠落あり。損保は「1.5万円2年」「要」「-」が混在。
  よって全項目を Optional で返し、欠落は None にする。
"""
import re
import unicodedata
from pathlib import Path

import yaml

CFG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
STRIP_PATTERNS = CFG.get("building_name_strip_patterns", [])

_NUM = r"([\d,]+(?:\.\d+)?)"
_DASH = ("", "-", "−", "‐", "―", "－", "‐")
_STATION_RE = re.compile(
    r"([^\s/]+?線|[^\s/]+?電鉄|大阪メトロ[^\s/]+)/([^\s/]+?)駅"
    r"(?:\s*歩\s*(\d+)分|\s*(\d+)分|\s*歩(\d+)|\s*(\d+)歩|\s*(\d+)分\s*歩)"
    r"(?:分|\b)"
)  # closes _STATION_RE
_LAYOUT_RE = re.compile(r"(ワンルーム|\d[SLDK]{1,4})")


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").replace("\xa0", " ")


def _int(m):
    return int(m.group(1)) if m else None


def to_yen(tok):
    """'9.3万円' '10000円' '要' '-' を円intへ。判定不能/欠落はNone。"""
    if tok is None:
        return None
    t = nfkc(str(tok)).strip()
    if t in _DASH:
        return None
    m = re.search(_NUM + r"\s*万円", t)
    if m:
        return int(round(float(m.group(1).replace(",", "")) * 10000))
    m = re.search(_NUM + r"\s*円", t)
    if m:
        return int(m.group(1).replace(",", ""))
    if any(k in t for k in ("なし", "不要", "無料", "込")):
        return 0
    return None


def money_pair(cell):
    """一覧セル '9.3万円 10000円' / '- 9.3万円' を (第一, 第二) へ。"""
    text = nfkc(cell)
    if "～" in text or "〜" in text or "~" in text:
        # 範囲表記 '8.5万円～9万円' は単一項目の幅。第二値を
        # 管理費などと誤認しないよう第一値だけを返す
        vals = [to_yen(x) for x in re.findall(
            r"[\d,]+(?:\.\d+)?\s*(?:万円|円)", text)]
        return (vals[0] if vals else None), None
    tokens = [p for p in re.split(r"\s+", text.strip()) if p]
    if len(tokens) >= 2:
        vals = [to_yen(t) for t in tokens]
        return vals[0], vals[1]
    found = re.findall(_NUM + r"\s*(?:万円|円)|[-−‐―]", nfkc(cell))
    vals = [to_yen(x) for x in found]
    return (vals + [None, None])[0], (vals + [None, None])[1]


def canonical_url(url: str | None) -> str | None:
    """?bc=... 等のクエリを除去し同一物件を1URLへ正規化。"""
    return url.split("?")[0].split("#")[0] if url else None


def jnc_id(url):
    m = re.search(r"jnc_(\d+)", url or "")
    return m.group(1) if m else None


def strip_building_name(name: str | None, fallback: str | None = None) -> str:
    """SUUMO見出し混入部分を除去。空結果は元名またはfallback。"""
    original = nfkc(name)
    clean = original
    for pat in STRIP_PATTERNS:
        clean = re.sub(pat, "", clean).strip()
    return clean or (original if fallback is None else fallback)


def normalize_building_name(name: str | None) -> str:
    """建物照合用の表記統一。"""
    if not name:
        return ""
    clean = nfkc(name).strip()
    if re.match(r"^(地下鉄|JR|京阪|阪急|南海|近鉄)", clean) and "駅" in clean:
        return ""
    return re.sub(r"\s+", "", clean).replace("Ⅱ", "II").replace("Ⅲ", "III").lower()


def normalize_address(address: str | None) -> str:
    """建物照合用の住所統一。"""
    clean = nfkc(address).strip()
    clean = re.sub(r"\s+", "", clean)
    return clean.replace("大阪府大阪市", "").replace("大阪市", "")


def parse_stations(text):
    """'地下鉄中央線/阿波座駅 歩5分 ...' を全件 [{line,name,walk}] へ。"""
    results = _STATION_RE.findall(nfkc(text))
    out = []
    for line, name, *walk_vals in results:
        # walk_vals has 6 entries; use first truthy
        walk = next((w for w in walk_vals if w), None)
        if walk is not None:
            walk = int(walk)
        out.append({"line": line, "name": name, "walk": walk})
    return out


def parse_list(soup, focus_station=""):
    """一覧ページ -> 各部屋 dict のリスト。"""
    out = []
    for cas in soup.select(".cassetteitem"):
        head = cas.select_one(".cassetteitem_content-title")
        name = strip_building_name(
            head.get_text(strip=True) if head else "")
        addr_el = cas.select_one(".cassetteitem_detail-col1")
        address = nfkc(addr_el.get_text(" ", strip=True) if addr_el else "")
        det_el = cas.select_one(".cassetteitem_detail")
        det = nfkc(det_el.get_text(" ", strip=True) if det_el else "")

        stations = parse_stations(det)
        if stations:
            # walk が取れない駅があると比較で落ちるため不明は末尾扱い
            nearest = min(stations,
                          key=lambda s: s["walk"] if s["walk"] is not None
                          else 9999)
        else:
            nearest = {"line": "", "name": focus_station, "walk": None}
        age = _int(re.search(r"築(\d+)年", det)) \
            or (0 if "新築" in det else None)
        floors = _int(re.search(r"(\d+)階建", det))

        for row in cas.select(".cassetteitem_other tbody tr.js-cassette_link"):
            cells = [td.get_text(" ", strip=True) for td in row.select("td")]

            def cell(i):
                return cells[i] if i < len(cells) else ""

            rent, admin = money_pair(cell(3))
            if rent and admin and admin > rent:
                # 管理費が家賃を超えるのはセル誤読（実DBで8件確認）。
                # 総額が約2倍になり rank/app から消えるため欠落扱いにする。
                admin = None
            shiki, rei = money_pair(cell(4))
            layout = ""
            ml = _LAYOUT_RE.search(cell(5))
            if ml:
                layout = ml.group(1)
            ma = re.search(r"([\d.]+)\s*m", cell(5))
            area = float(ma.group(1)) if ma else None

            durl = None
            for a in row.select("a[href]"):
                h = a.get("href", "")
                if "jnc_" in h:
                    durl = h if h.startswith("http") else "https://suumo.jp" + h
                    break

            out.append({
                "name": name, "address": address, "age_years": age,
                "floors": floors, "floor": _int(re.search(r"(\d+)階", cell(2))),
                "rent_yen": rent, "admin_yen": admin,
                "shikikin_yen": shiki, "reikin_yen": rei,
                "layout": layout, "area_m2": area,
                "url": canonical_url(durl), "jnc": jnc_id(durl),
                "stations": stations, "nearest": nearest,
            })
    return out


def _table_map(node):
    out = {}
    for tr in (node.select("tr") if node else []):
        cells = [c.get_text(" ", strip=True) for c in tr.select("th,td")]
        for i in range(0, len(cells) - 1, 2):
            if cells[i] and cells[i] not in out:
                out[cells[i]] = cells[i + 1]
    return out


def _find_yen(text, label_re, window=25):
    """ラベル直後 window 文字以内の金額を返す。ラベル名に数字を含んでも安全。"""
    t = nfkc(text)
    for m in re.finditer(label_re, t):
        seg = t[m.end(): m.end() + window]
        am = re.search(r"([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)", seg)
        if am:
            return to_yen(am.group(1))
    return None


def _guarantee_rate(text):
    t = nfkc(text or "")
    for pat in (r"初回[^0-9]{0,10}(\d{1,3})\s*[%％]",
                r"総賃料の(\d{1,3})\s*[%％]",
                r"賃料[等]?[^0-9]{0,8}(\d{1,3})\s*[%％]"):
        m = re.search(pat, t)
        if m:
            return int(m.group(1))
    return None


def _yen_or_ratio(text, rent):
    """金額テキスト -> 円。'9.9万円' 等の実額を優先し、無ければ
    '賃料の1ヶ月分' '55%' のような賃料比を rent から換算する。
    'なし/不要/無料' は 0。判定不能は None。"""
    t = nfkc(text or "")
    if not t:
        return None
    if any(k in t for k in ("なし", "不要", "無料")) \
            and not re.search(r"[\d,]+\s*(?:万円|円)", t):
        return 0
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*万円", t)
    if m:
        return int(round(float(m.group(1).replace(",", "")) * 10000))
    m = re.search(r"([\d,]+)\s*円", t)
    if m:
        return int(m.group(1).replace(",", ""))
    if not rent:
        return None
    m = re.search(r"([\d.]+)\s*(?:ヶ月|か月|カ月)(?:分)?", t)
    if m:
        return int(rent * float(m.group(1)))
    m = re.search(r"([\d.]+)\s*[%％]", t)
    if m:
        return int(rent * float(m.group(1)) / 100)
    return None


def _agency_yen(g, other, full, price_raw, rent):
    """仲介手数料。ラベル付きの値だけを採用する。

    従来は「ほか初期費用」全文の先頭金額へフォールバックしており、
    注記が「合計14.3万円（内訳：…）」形式だと合計額そのものを
    仲介手数料と誤認した（新DBで約999件、2年総額の二重計上の原因）。
    ラベル近傍に無い金額は採用しない。あわせて、仲介手数料は
    法律上 賃料の1.1ヶ月分が上限なので、超過分は誤読として捨てる。
    """
    v = None
    for src in (price_raw, g.get("仲介手数料")):
        v = _yen_or_ratio(src, rent)
        if v is not None:
            break
    if v is None and other and "仲介手数料" in other:
        idx = other.find("仲介手数料")
        v = _yen_or_ratio(other[idx: idx + 40], rent)
    if v is None:
        idx = (full or "").find("仲介手数料")
        if idx >= 0:
            v = _yen_or_ratio(full[idx: idx + 40], rent)
    if v is not None and rent and v > rent * 1.1 + 1000:
        return None
    return v


AMENITY_HINT = (
    "バストイレ別", "エアコン", "オートロック", "独立洗面",
    "宅配ボックス", "バルコニー", "フローリング", "浴室",
    "洗面", "キッチン", "コンロ", "収納", "インターホン",
    "エレベーター", "給湯", "洗濯機", "温水洗浄",
    "システムキッチン", "室内洗濯機", "クローゼット", "ウォークインクローゼット",
    "バイク置き場", "駐車場", "浴室乾燥", "シューズボックス", "床暖房",
    "ガスコンロ", "IHコンロ", "追い焚き", "オートバス",
)


def _equipment_text(soup):
    """設備は複数ある ul.inline_list のうち、アメニティ語を最も含むもの。

    契約期間/保証会社/ほか初期費用 なども同じ ul.inline_list で表れるため、
    見出し親や全リスト結合では汚染する。キーワード一致数で選別する。
    """
    best = ""
    for ul in soup.select("ul.inline_list"):
        items = [li.get_text(strip=True) for li in ul.select("li")]
        t = nfkc("、".join(x for x in items if x) or ul.get_text("、", strip=True))
        score = sum(1 for k in AMENITY_HINT if k in t)
        if score >= 3 and len(t) > len(best):
            best = t
    if best:
        return best
    for h in soup.find_all(["h2", "h3"]):
        t = h.get_text(strip=True)
        if "部屋の特徴" in t or "設備" in t:
            return nfkc(h.parent.get_text(" ", strip=True)).split(t, 1)[-1].strip()
    return ""


def parse_detail(soup):
    """詳細ページ -> dict（欠落はNone）。"""
    info = soup.select_one(".property_view_note-info") \
        or soup.select_one(".property_view_note")
    price = {"rent": None, "admin": None, "deposit": None, "key_money": None,
             "hoshoukin": None, "shoukyaku": None, "agency_raw": None}
    if info:
        for line in [x.strip() for x in nfkc(info.get_text("\n")).split("\n")
                     if x.strip()]:
            if line.startswith("管理費") or line.startswith("共益費"):
                price["admin"] = to_yen(line.split(":", 1)[-1])
            elif line.startswith(("敷金/礼金", "礼金/敷金")):
                # 合算表記「敷金/礼金: -/8.5万円」は / の前後で分ける。
                # 丸ごと to_yen すると礼金を敷金として取り違える。
                parts = line.split(":", 1)[-1].split("/")
                first = to_yen(parts[0])
                second = to_yen(parts[1]) if len(parts) > 1 else None
                if line.startswith("敷金"):
                    price["deposit"], price["key_money"] = first, second
                else:
                    price["key_money"], price["deposit"] = first, second
            elif line.startswith("敷金"):
                price["deposit"] = to_yen(line.split(":", 1)[-1])
            elif line.startswith("礼金"):
                price["key_money"] = to_yen(line.split(":", 1)[-1])
            elif line.startswith("保証金"):
                price["hoshoukin"] = to_yen(line.split(":", 1)[-1])
            elif line.startswith(("敷引", "償却")):
                price["shoukyaku"] = to_yen(line.split(":", 1)[-1])
            elif line.startswith("仲介手数料"):
                price["agency_raw"] = line.split(":", 1)[-1]
            elif price["rent"] is None and ("万円" in line or "円" in line):
                price["rent"] = to_yen(line)

    g = _table_map(soup.select_one("table.table_gaiyou"))
    acc = _table_map(soup.select_one(".property_view_table"))
    full = nfkc(soup.get_text(" ", strip=True))
    equipment = _equipment_text(soup)

    other = g.get("ほか初期費用") or g.get("ほか諸費用") or ""
    guarantee_rate = _guarantee_rate(g.get("保証会社"))
    rent = price["rent"]
    contract = g.get("契約期間") or ""
    cm = re.search(r"(\d+)年", contract)
    months = int(cm.group(1)) * 12 if cm else None
    # 保証会社の更新料と契約の更新料は別物。従来は両列に同じ値を
    # 入れていたため実質月額で二重計上されていた。
    guarantee_renew_yen = _find_yen(g.get("保証会社") or "", r"更新料")
    renewal_fee_yen = _find_yen(contract, r"更新料") \
        or _find_yen(other, r"更新手数料")
    admin = price["admin"]
    if rent and admin and admin > rent:
        admin = None  # 一覧側と同じ異常値ガード（管理費>家賃は誤読）
    # 敷金・礼金等の異常値ガード: 仲介側が円額を万円欄に入力した
    # ケース（実例「敷金: 435600万円」=43.5億円、家賃6.6万円）を通さない。
    # 住宅の敷金・礼金・保証金は通常0〜数ヶ月分で、12ヶ月分超は誤記。
    if rent:
        for key in ("deposit", "key_money", "hoshoukin", "shoukyaku"):
            if price[key] is not None and price[key] > rent * 12:
                price[key] = None

    key_exchange_yen = _find_yen(other, r"鍵交換")
    cleaning_yen = _find_yen(other,
                              r"(ハウスクリーニング|室内清掃|清掃|クリーニング)")
    support_yen = _find_yen(other, r"(サポート|CLUB|プレサポ|除菌消臭|安心)")
    # 「合計X万円（内訳：…）」形式では各項目は合計以下のはず。
    # 商品名末尾の数字と金額が連結した誤読（実例「アクト安心ライフ24
    # 1.65万円」が分離されず 241.65万円 になる）では項目が合計を
    # 超えるため、合計を超えた項目は捨てる。サポート費は合計が
    # 取れない場合でも10万円超を実勢外として捨てる。
    total_m = re.match(r"合計\s*([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)",
                       nfkc(other or ""))
    other_total = to_yen(total_m.group(1)) if total_m else None

    def _cap_fee(v, cap=None):
        if v is None:
            return None
        if other_total is not None and v > other_total:
            return None
        if cap is not None and v > cap:
            return None
        return v

    key_exchange_yen = _cap_fee(key_exchange_yen)
    cleaning_yen = _cap_fee(cleaning_yen)
    support_yen = _cap_fee(support_yen, cap=100000)

    return {
        "rent_yen": rent,
        "admin_yen": admin,
        "deposit_yen": price["deposit"],
        "key_money_yen": price["key_money"],
        "hoshoukin_yen": price["hoshoukin"],
        "shoukyaku_yen": price["shoukyaku"],
        "insurance_yen": to_yen(g.get("損保")),
        "key_exchange_yen": key_exchange_yen,
        "cleaning_yen": cleaning_yen,
        "support_yen": support_yen,
        "guarantee_first_yen": (int(rent * guarantee_rate / 100)
                                if rent and guarantee_rate else None),
        "guarantee_renew_yen": guarantee_renew_yen,
        "agency_yen": _agency_yen(g, other, full, price["agency_raw"], rent),
        "renewal_fee_yen": renewal_fee_yen,
        "water_fixed_yen": _find_yen(full, r"水道代"),
        "contract_months": months,
        "regular_lease": 0 if "定期借家" in full else 1,
        "free_rent_months": 1 if "フリーレント" in full else 0,
        "structure": g.get("構造"),
        "floors": _int(re.search(r"(\d+)階建",
                                 g.get("階建") or "")),
        "building_age_years": _int(re.search(r"築(\d+)年",
                                             acc.get("築年数") or "")),
        "direction": acc.get("向き"),
        "building_type": acc.get("建物種別"),
        "address": acc.get("所在地"),
        "stations": parse_stations(acc.get("駅徒歩", "")),
        "equipment": equipment,
        "note": other,
        "full": full,
    }

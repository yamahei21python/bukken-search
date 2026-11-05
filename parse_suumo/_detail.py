"""詳細ページのパース。

価格  = .property_view_note-info
建物  = table.table_gaiyou
アクセス = .property_view_table
設備  = 「部屋の特徴・設備」見出しの親要素
"""
import re

from ._money import (
    _agency_yen,
    _cleaning_yen,
    _find_yen,
    _free_rent_months,
    _guarantee_first_yen,
    _guard_rent_multiple,
    _labeled_yen,
    _support_fees,
    to_yen,
)
from ._normalize import _DASH, _int, nfkc
from ._stations import parse_stations


def _table_map(node):
    out = {}
    for tr in (node.select("tr") if node else []):
        cells = [c.get_text(" ", strip=True) for c in tr.select("th,td")]
        for i in range(0, len(cells) - 1, 2):
            if cells[i] and cells[i] not in out:
                out[cells[i]] = cells[i + 1]
    return out


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
            txt = nfkc(h.parent.get_text(" ", strip=True)) \
                .split(t, 1)[-1].strip()
            # 親要素の全文が返るページ型があり、PR文や物件概要の塊
            # （数百字）が設備として混入した。設備らしい語を複数
            # 含む場合だけ、長さに上限を付けて採用する。
            if sum(1 for k in AMENITY_HINT if k in txt) >= 2:
                return txt[:500]
            return ""
    return ""


def parse_detail(soup):
    """詳細ページ -> dict（欠落はNone）。"""
    info = soup.select_one(".property_view_note-info") \
        or soup.select_one(".property_view_note")
    price_note = nfkc(info.get_text(" ")) if info else ""
    price = {"rent": None, "admin": None, "deposit": None, "key_money": None,
             "hoshoukin": None, "shoukyaku": None, "agency_raw": None}
    if info:
        for line in [x.strip() for x in nfkc(info.get_text("\n")).split("\n")
                     if x.strip()]:
            if line.startswith(("管理費", "共益費")):
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
    rent = price["rent"]
    contract = g.get("契約期間") or ""
    # 契約期間のパース: 「2028年3月末まで」のような定期借家の期限
    # （西暦）を期間と誤認しないよう、大きな年数は除外する
    # （誤認すると contract_months が 24336 のような値になった）。
    months = None
    for m in re.finditer(r"(\d+)\s*年", contract):
        yrs = int(m.group(1))
        if yrs <= 30:
            months = yrs * 12
            # 「2年6ヶ月」形式のときだけ月を足す（直後のみを見る。
            # セル内の更新料「1ヶ月分」等を拾わないため）
            mm = re.match(r"\s*(\d+)\s*(?:ヶ月|か月|カ月|ヵ月)",
                          contract[m.end():])
            if mm:
                months += int(mm.group(1))
            break
    # 保証会社の更新料と契約の更新料は別物。従来は両列に同じ値を
    # 入れていたため実質月額で二重計上されていた。どちらも
    # 「賃料の1ヶ月分」等の比率表記が多いため _labeled_yen で拾う。
    guarantee_renew_yen = _labeled_yen(g.get("保証会社") or "",
                                       r"更新料", rent)
    if guarantee_renew_yen is None:
        # 「1年更新:10,000円」型の表記（保証会社の年次更新料）
        guarantee_renew_yen = _labeled_yen(g.get("保証会社") or "",
                                           r"年更新", rent)
    # ほか初期費用側は「更新手数料」表記しか見ておらず、主流の
    # 「更新料 15000円」「更新料 新賃料1.00ヶ月分」を取りこぼして
    # いた（備考に更新料があるのに NULL が81件、取得成功は1件）。
    # 保証会社の更新料（保証更新料/保証会社更新料）は別費目なので
    # 否定後読みで除外する。
    renewal_fee_yen = _labeled_yen(contract, r"更新料", rent) \
        or _labeled_yen(other, r"更新手数料", rent) \
        or _labeled_yen(other, r"(?<!保証)(?<!保証会社)更新料", rent)
    # ガード: 倍率が巨大な誤読（新賃料86000.00ヶ月分等）を棄却
    if renewal_fee_yen is not None and rent and renewal_fee_yen > rent * 3:
        renewal_fee_yen = None
    # 更新事務手数料は更新料とは別の費目（F9 で独立カラム化）。
    # 従来は保存先がなく、備考に残るだけだった。
    renewal_admin_fee_yen = _labeled_yen(other, r"更新事務手数料", rent) \
        or _labeled_yen(contract, r"更新事務手数料", rent)
    if renewal_admin_fee_yen is not None and rent \
            and renewal_admin_fee_yen > rent * 3:
        renewal_admin_fee_yen = None
    admin = price["admin"]
    if rent and admin and admin > rent:
        admin = None  # 一覧側と同じ異常値ガード（管理費>家賃は誤読）
    # 敷金・礼金等の異常値ガード: 仲介側が円額を万円欄に入力した
    # ケース（実例「敷金: 435600万円」=43.5億円、家賃6.6万円）を通さない。
    # 住宅の敷金・礼金・保証金は通常0〜数ヶ月分で、12ヶ月分超は誤記。
    if rent:
        for key in ("deposit", "key_money", "hoshoukin", "shoukyaku"):
            price[key] = _guard_rent_multiple(price[key], rent)

    key_exchange_yen = _find_yen(other, r"鍵交換")
    cleaning_yen = _cleaning_yen(other)
    support_yen, support_monthly_yen = _support_fees(other)
    # 「合計X万円（内訳：…）」形式では各項目は合計以下のはず。
    # 商品名末尾の数字と金額が連結した誤読（実例「アクト安心ライフ24
    # 1.65万円」が分離されず 241.65万円 になる）では項目が合計を
    # 超えるため、合計を超えた項目は捨てる。サポート費は合計が
    # 取れない場合でも10万円超を実勢外として捨てる。
    total_m = re.match(r"合計\s*([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)",
                       nfkc(other or ""))
    other_total = to_yen(total_m.group(1)) if total_m else None

    def _cap_fee(v, cap=None, check_total=True):
        if v is None:
            return None
        if check_total and other_total is not None and v > other_total:
            return None
        if cap is not None and v > cap:
            return None
        return v

    key_exchange_yen = _cap_fee(key_exchange_yen)
    cleaning_yen = _cap_fee(cleaning_yen)
    support_yen = _cap_fee(support_yen, cap=100000)
    # 月額型は初期費用の「合計」の内訳ではないため合計ガードは
    # 掛けず、上限だけを適用する
    support_monthly_yen = _cap_fee(support_monthly_yen, cap=100000,
                                   check_total=False)

    # 取扱店舗（掲載仲介）。listings.agent の帰属用（F10）。
    # 表示文字列は「店舗名(株)会社名」「会社名(株)店舗名」など
    # 順序の表記ゆれがあるため、分割せず表示のまま保持する。
    agent_el = soup.select_one(".viewform_advance_shop-name")
    agent = nfkc(agent_el.get_text(strip=True)) if agent_el else None
    if not agent:
        agent = None

    direction = acc.get("向き")
    if direction is not None and nfkc(direction).strip() in _DASH:
        # SUUMO の「-」は向き未公表のプレースホルダ。値として保存
        # すると実値の上書きや誤集計の元になるため NULL に倒す
        direction = None
    area_m = re.search(r"(\d+(?:\.\d+)?)", acc.get("専有面積") or "")

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
        "support_monthly_yen": support_monthly_yen,
        "guarantee_first_yen": _guarantee_first_yen(g.get("保証会社"), rent),
        "guarantee_renew_yen": guarantee_renew_yen,
        "agency_yen": _agency_yen(g, other, full, price["agency_raw"], rent),
        "renewal_fee_yen": renewal_fee_yen,
        "renewal_admin_fee_yen": renewal_admin_fee_yen,
        "water_fixed_yen": _find_yen(full, r"水道代"),
        "contract_months": months,
        "regular_lease": 0 if "定期借家" in full else 1,
        "free_rent_months": _free_rent_months(price_note, equipment,
                                              other, contract),
        "structure": g.get("構造"),
        "floors": _int(re.search(r"(\d+)階建",
                                 g.get("階建") or "")),
        "building_age_years": _int(re.search(r"築(\d+)年",
                                             acc.get("築年数") or "")),
        "direction": direction,
        "area_m2": float(area_m.group(1)) if area_m else None,
        "building_type": acc.get("建物種別"),
        "address": acc.get("所在地"),
        "stations": parse_stations(acc.get("駅徒歩", "")),
        "equipment": equipment,
        "note": other,
        "full": full,
        "agent": agent,
    }

"""金額パース: '万円/円/要/なし' 実額と '◯ヶ月分/◯%' 比率表記を円 int へ。"""
import re

from ._normalize import _DASH, _NUM, nfkc


def to_yen(tok):
    """'9.3万円' '10000円' '要' '-' を円intへ。判定不能/欠落はNone。"""
    if tok is None:
        return None
    t = nfkc(str(tok)).strip()
    if t in _DASH:
        return None
    m = re.search(_NUM + r"\s*万円", t)
    if m:
        return round(float(m.group(1).replace(",", "")) * 10000)
    m = re.search(_NUM + r"\s*円", t)
    if m:
        # 円分岐も小数（"2095.5円"）がありうる。int() 直変換だと
        # ValueError で落ち、詳細側は毒物件化・一覧側は run 全体が
        # 異常終了するため、万円分岐と同じく丸めて受ける。
        return round(float(m.group(1).replace(",", "")))
    if any(k in t for k in ("なし", "不要", "無料", "込")):
        return 0
    return None


def _guard_rent_multiple(value, rent, max_months=12):
    """敷金・礼金等の異常値ガード。仲介側が円額を万円欄に入力した
    ケース（実例「敷金: 435600万円」=43.5億円、家賃6.6万円）を通さない。
    住宅の敷金・礼金・保証金は通常0〜数ヶ月分で、12ヶ月分超は誤記。
    詳細側にあったガードを一覧・詳細の共通関数にした。"""
    if value is not None and rent and value > rent * max_months:
        return None
    return value


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
    padded = [*vals, None, None]
    return padded[0], padded[1]


def _find_yen(text, label_re, window=25):
    """ラベル直後 window 文字以内の金額を返す。ラベル名に数字を含んでも安全。"""
    t = nfkc(text)
    for m in re.finditer(label_re, t):
        seg = t[m.end(): m.end() + window]
        am = re.search(r"([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)", seg)
        if am:
            return to_yen(am.group(1))
    return None


def _first_value(seg, rent):
    """ラベル直後の断片から、最初に現れた金額/比率を採用する。

    金額を優先して断片全体から探すと、「更新料1ヵ月 更新事務
    手数料16500円」のような並記で別費目の金額を掴む（実例あり）。
    ラベルに最も近い表記が当該費目の値とみなす。
    """
    if any(k in seg for k in ("なし", "不要", "無料")) \
            and not re.search(r"[\d,]+\s*(?:万円|円)", seg):
        return 0
    # 段階制（「15万円未満10,000円/年 15万円以上14,000円/年」）では
    # 先頭の金額が閾値そのものなので、賃料が属する段の金額を返す。
    # 属する段の金額が読めない（末尾切断等）場合は誤読を避け None。
    if rent:
        mb = re.search(r"([\d,]+(?:\.\d+)?)\s*万円未満\s*"
                       r"([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)", seg)
        ma = re.search(r"([\d,]+(?:\.\d+)?)\s*万円以上\s*"
                       r"([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)", seg)
        if mb or ma:
            th = float((mb or ma).group(1).replace(",", "")) * 10000
            if rent < th:
                return to_yen(mb.group(2)) if mb else None
            return to_yen(ma.group(2)) if ma else None
    best = None
    am = None
    for cand in re.finditer(r"[\d,]+(?:\.\d+)?\s*万円|[\d,]+(?:\.\d+)?\s*円",
                            seg):
        if seg[cand.end():cand.end() + 2] in ("未満", "以上"):
            continue  # 段階制の閾値は金額として採用しない
        am = cand
        break
    if am:
        best = (am.start(), to_yen(am.group(0)))
    if rent:
        rm = re.search(r"(\d+(?:\.\d+)?)\s*(?:ヶ月|か月|カ月|ヵ月)(?:分)?", seg)
        if rm and (best is None or rm.start() < best[0]):
            best = (rm.start(), int(rent * float(rm.group(1))))
        pm = re.search(r"(\d+(?:\.\d+)?)\s*[%％]", seg)
        if pm and (best is None or pm.start() < best[0]):
            best = (pm.start(), int(rent * float(pm.group(1)) / 100))
    return best[1] if best else None


def _labeled_yen(text, label_re, rent, window=40):
    """ラベル近傍の金額を返す。絶対額に加え「賃料の1ヶ月分」「55%」
    のような比率表記も rent から換算する。

    更新料などは比率表記が主流で、絶対額だけ探す _find_yen では
    ほぼ全件取りこぼしていた（新DBで更新料 0/2,248件）。
    """
    t = nfkc(text or "")
    for m in re.finditer(label_re, t):
        v = _first_value(t[m.end(): m.end() + window], rent)
        if v is not None:
            return v
    return None


def _guarantee_rate(text):
    t = nfkc(text or "")
    m = re.search(r"初回[^0-9]{0,10}(\d{1,3})\s*[%％]", t)
    if m:
        return int(m.group(1))
    # 「総賃料の◯%」も、「月額保証料:総賃料の2%」のような月額文脈の
    # マッチは初回率と誤認しない（実例: 事務手数料33,000円+月額2%の
    # 物件が ¥1,640 化した）
    for m in re.finditer(r"総賃料の(\d{1,3})\s*[%％]", t):
        if "月額" in t[max(0, m.start() - 8):m.start()]:
            continue
        if "月次" in t[max(0, m.start() - 8):m.start()]:
            continue
        if "毎月" in t[m.end():m.end() + 6]:
            continue
        return int(m.group(1))
    # 「賃料の◯%」は初回率のこともあるが、「月額賃料の1%/毎月」の
    # ような月額保証料の率を初回率と誤認しないよう、月額文脈の
    # マッチは採用しない（実例: 初回保証料10,000円の物件が ¥630 化）
    for m in re.finditer(r"賃料[等]?[^0-9]{0,8}(\d{1,3})\s*[%％]", t):
        if "月額" in t[max(0, m.start() - 8):m.start()]:
            continue
        if "毎月" in t[m.end():m.end() + 6]:
            continue
        return int(m.group(1))
    return None


def _initial_fixed_yen(text):
    """「初回:33,000円」型の固定額。ラベルの後に率より先に金額が
    来ている場合だけ採用する。「初回契約事務手数料」のような
    事務手数料は保証料ではないので、そのマッチは読み飛ばす。"""
    t = nfkc(text or "")
    for m in re.finditer(r"初回", t):
        seg = t[m.end(): m.end() + 30]
        yen = re.search(r"([\d,]+)\s*円", seg)
        if not yen:
            continue
        if "事務手数料" in seg[:yen.start()]:
            continue
        pct = re.search(r"\d+\s*[%％]", seg)
        if pct and pct.start() < yen.start():
            continue
        return int(yen.group(1).replace(",", ""))
    return None


def _hosho_fixed_yen(text):
    """「保証料:35000円」型と「◯円/入居時」型の固定額。
    保証料ラベルの直後に金額が続く場合だけを採用し、月額の
    固定額（◯円/月）は初回とみなさない。"""
    t = nfkc(text or "")
    for m in re.finditer(r"保証料", t):
        seg = t[m.end(): m.end() + 20]
        yen = re.match(r"[：:・\s]*([\d,]+)\s*円", seg)
        if not yen:
            continue
        if re.match(r"\s*[／/]\s*(毎月|月)", seg[yen.end():]):
            continue
        return int(yen.group(1).replace(",", ""))
    m = re.search(r"([\d,]+)\s*円\s*[／/]\s*入居時", t)
    if m and "保証" in t[:m.start()]:
        return int(m.group(1).replace(",", ""))
    return None


def _guarantee_first_yen(text, rent):
    """初回保証料。固定額の明記（初回保証料/初回保証委託料 ◯円）を
    優先し、無い場合のみ率（総賃料の◯%等）から換算する。
    従来は率が無いと NULL 固定で、固定額のみの物件を取りこぼし、
    率があると月額率の誤認で実額と乖離していた。"""
    v = _labeled_yen(text or "", r"初回保証委託料|初回保証料", rent)
    if v is not None:
        return v
    v = _initial_fixed_yen(text)
    if v is not None:
        return v
    v = _hosho_fixed_yen(text)
    if v is not None:
        return v
    rate = _guarantee_rate(text)
    if rent and rate:
        return int(rent * rate / 100)
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
        return round(float(m.group(1).replace(",", "")) * 10000)
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*円", t)
    if m:
        return round(float(m.group(1).replace(",", "")))
    if not rent:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ヶ月|か月|カ月|ヵ月)(?:分)?", t)
    if m:
        return int(rent * float(m.group(1)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*[%％]", t)
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


def _cleaning_yen(text):
    """室内清掃費。「エアコンクリーニング/エアコン清掃」は空調の
    清掃費で別費目なので採用しない（従来はラベルの先勝ちで
    エアコン清掃費が cleaning_yen に混入していた）。"""
    t = nfkc(text or "")
    for m in re.finditer(r"(ハウスクリーニング|室内清掃|清掃|クリーニング)",
                         t):
        if "エアコン" in t[max(0, m.start() - 6):m.start()]:
            continue
        am = re.search(r"([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)",
                       t[m.end():m.end() + 25])
        if am:
            return to_yen(am.group(1))
    return None


def _support_fees(text):
    """サポート系費用を (一時金, 月額) に分けて返す。

    ほか初期費用には「安心サポート 月額880円」のような月額型と
    「ライフサポート4.62万円」のような入居時一時金型が混在する。
    従来は同一列に入れており、実質月額（全額を毎月加算）と
    2年総額（完全に無視）の両方が誤っていた。
    """
    t = nfkc(text or "")
    one_time = None
    monthly = None
    for m in re.finditer(r"(サポート|CLUB|プレサポ|除菌消臭|安心)", t):
        seg = t[m.start():m.start() + 48]
        am = re.search(r"([\d,]+(?:\.\d+)?\s*万円|[\d,]+\s*円)", seg)
        if not am:
            continue
        v = to_yen(am.group(1))
        if v is None:
            continue
        # 「月額880円」「990円/月額」など金額の前後に「月額」が
        # 付くものは月額型、付かないものは一時金として分類する
        if "月額" in t[m.start():m.start() + am.end() + 6]:
            if monthly is None:
                monthly = v
        elif one_time is None:
            one_time = v
        if one_time is not None and monthly is not None:
            break
    return one_time, monthly


def _free_rent_months(*texts):
    """フリーレント月数。物件側の文脈だけを探す。

    ページ全文で探すと仲介会社の PR 文（「フリーレント付き物件の
    特集も充実」等）に誤反応する。価格メモ・設備・ほか初期費用・
    契約期間に限定し、月数が読めればその値、言及のみなら 1。
    従来は 0/1 の二値で「2ヶ月」でも 1 になっていた。
    """
    for t in texts:
        m = re.search(
            r"フリーレント\s*(\d+(?:\.\d+)?)\s*(?:ヶ月|か月|カ月|ヵ月|月)",
            nfkc(t or ""))
        if m:
            return float(m.group(1))
    for t in texts:
        if "フリーレント" in nfkc(t or ""):
            return 1.0
    return 0.0

"""正規化: NFKC・共通定数・URL/建物名/住所の表記統一。

金額トークンの共通定義 (_NUM/_DASH/_LAYOUT_RE) もここに置く。
config.yaml はパッケージの1つ上 (リポジトリルート) にある。
"""
import re
import unicodedata
from pathlib import Path

import yaml

CFG = yaml.safe_load(
    (Path(__file__).parent.parent / "config.yaml").read_text())
STRIP_PATTERNS = CFG.get("building_name_strip_patterns", [])

_NUM = r"([\d,]+(?:\.\d+)?)"
_DASH = ("", "-", "−", "‐", "―", "－", "‐")

_LAYOUT_RE = re.compile(r"(ワンルーム|\d[SLDK]{1,4})")


def nfkc(s):
    t = unicodedata.normalize("NFKC", s or "").replace("\xa0", " ")
    # 「10、000円」のような桁区切り混じりの金額を1つの数値として
    # 読めるよう、数字に挟まれた読点だけを落とす（一般の読点は保持）
    t = re.sub(r"(?<=\d)、(?=\d)", "", t)
    # 空白区切りは千区切りの形（空白の後にちょうど3桁が続く）だけを
    # 対象にする（「10 000円」。日付・電話番号等の空白は壊さない）
    return re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", t)


def _int(m):
    return int(m.group(1)) if m else None


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


_READING_CHARS = set("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすず"
                     "せぜそぞただちぢつづてでとどなにぬねのはばぱひびぴ"
                     "ふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろ"
                     "ゎわゐゑをんァアィイゥウェエォオカガキギクグケゲコゴ"
                     "サザシジスズセゼソゾタダチヂツヅテデトドナニヌネノ"
                     "ハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨ"
                     "ラリルレロヮワヰヱヲンヴヵヶー・")


def _strip_reading_parens(s: str) -> str:
    """括弧内が読み表記（かな・カナ・長音・中点・空白のみ）の場合だけ
    括弧ごと落とす。「南館」「別館」のような意味のある括弧は残す。"""
    def repl(m):
        inner = m.group(1)
        if inner and all(ch in _READING_CHARS or ch.isspace()
                         for ch in inner):
            return ""
        return m.group(0)
    return re.sub(r"[（(]([^（）()]*)[）)]", repl, s)


def normalize_building_name(name: str | None) -> str:
    """建物照合用の表記統一。"""
    if not name:
        return ""
    clean = nfkc(name).strip()
    if re.match(r"^(地下鉄|JR|京阪|阪急|南海|近鉄)", clean) and "駅" in clean:
        return ""
    clean = _strip_reading_parens(clean)
    clean = clean.replace("・", "")
    return re.sub(r"\s+", "", clean).replace("Ⅱ", "II").replace("Ⅲ", "III").lower()


def normalize_address(address: str | None) -> str:
    """建物照合用の住所統一。"""
    clean = nfkc(address).strip()
    clean = re.sub(r"\s+", "", clean)
    return clean.replace("大阪府大阪市", "").replace("大阪市", "")

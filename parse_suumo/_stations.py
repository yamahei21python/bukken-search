"""駅・徒歩時間のパース。"""
import re

from ._normalize import nfkc

_STATION_RE = re.compile(
    r"([^\s/]+?線|[^\s/]+?電鉄|大阪メトロ[^\s/]+)/([^\s/]+?)駅"
    r"(?:\s*歩\s*(\d+)分|\s*(\d+)分|\s*歩(\d+)|\s*(\d+)歩|\s*(\d+)分\s*歩)"
    r"(?:分|\b)"
)  # closes _STATION_RE

def parse_stations(text):
    """'地下鉄中央線/阿波座駅 歩5分 ...' を [{line,name,walk}] へ。

    駅名で dedup し最大3件に切り詰める。SUUMO が物件に付ける駅は
    最大3件で、それを超える分は店舗情報など別ブロック由来の混入
    （実例: 旭区中宮の物件に仲介店舗の最寄り「四ツ橋駅 歩1分」が
    付いた）。同一駅が複数路線で並ぶ場合は先勝ちで1件にする。
    """
    results = _STATION_RE.findall(nfkc(text))
    out = []
    seen = set()
    for line, name, *walk_vals in results:
        if name in seen:
            continue
        seen.add(name)
        # walk_vals has 6 entries; use first truthy
        walk = next((w for w in walk_vals if w), None)
        if walk is not None:
            walk = int(walk)
        out.append({"line": line, "name": name, "walk": walk})
        if len(out) >= 3:
            break
    # F7: 最寄りから30分超も離れた駅は同一カセット内の外れ値として落とす
    # （仲介店舗側の駅や説明名由来の混入。実例: 都島区の物件に玉川68分）。
    # walk 不明の駅は判定材料がないため残す。
    walks = [s["walk"] for s in out if s["walk"] is not None]
    if len(walks) >= 2:
        nearest_walk = min(walks)
        out = [s for s in out
               if s["walk"] is None or s["walk"] <= nearest_walk + 30]
    return out

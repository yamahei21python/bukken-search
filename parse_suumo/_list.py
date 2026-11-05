"""一覧ページ (.cassetteitem) のパース。

td は固定位置。先頭2列は空。2=阶 3=賃料/管理費 4=敷金/礼金
5=間取り/専有面積。空セルを除外してインデックス参照してはいけない
（桁ズレの原因）。
"""
import re

from ._money import _guard_rent_multiple, money_pair
from ._normalize import _LAYOUT_RE, _int, canonical_url, jnc_id, nfkc, strip_building_name
from ._stations import parse_stations


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

        base = {"name": name, "address": address, "age_years": age,
                "floors": floors, "stations": stations, "nearest": nearest}
        for row in cas.select(".cassetteitem_other tbody tr.js-cassette_link"):
            try:
                out.append(_list_row(row, base))
            except Exception:
                # 1行のパース失敗（金額の想定外表記など）で一覧
                # run 全体を落とさない。当該行だけを捨てる。
                continue
    return out


def _list_row(row, base):
    """一覧の1行（1部屋）を dict へ。base はカセット共通部。"""
    cells = [td.get_text(" ", strip=True) for td in row.select("td")]

    def cell(i):
        return cells[i] if i < len(cells) else ""

    rent, admin = money_pair(cell(3))
    if rent and admin and admin > rent:
        # 管理費が家賃を超えるのはセル誤読（実DBで8件確認）。
        # 総額が約2倍になり rank/app から消えるため欠落扱いにする。
        admin = None
    shiki, rei = money_pair(cell(4))
    # 詳細側と同じ異常値ガード（一覧値は未取得物件では costs にも流れる）
    shiki = _guard_rent_multiple(shiki, rent)
    rei = _guard_rent_multiple(rei, rent)
    layout = ""
    ml = _LAYOUT_RE.search(cell(5))
    if ml:
        layout = ml.group(1)
    ma = re.search(r"(\d+(?:\.\d+)?)\s*m", cell(5))
    area = float(ma.group(1)) if ma else None

    durl = None
    for a in row.select("a[href]"):
        h = a.get("href", "")
        if "jnc_" in h:
            durl = h if h.startswith("http") else "https://suumo.jp" + h
            break

    return {
        "name": base["name"], "address": base["address"],
        "age_years": base["age_years"], "floors": base["floors"],
        "floor": _int(re.search(r"(\d+)階", cell(2))),
        "rent_yen": rent, "admin_yen": admin,
        "shikikin_yen": shiki, "reikin_yen": rei,
        "layout": layout, "area_m2": area,
        "url": canonical_url(durl), "jnc": jnc_id(durl),
        "stations": base["stations"], "nearest": base["nearest"],
    }

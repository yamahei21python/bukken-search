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

import re  # noqa: F401  (日付・電話等の互換で利用者が往々にしている)

from ._detail import AMENITY_HINT, _equipment_text, _table_map, parse_detail
from ._list import _list_row, parse_list
from ._money import (
                     _agency_yen,
                     _cleaning_yen,
                     _find_yen,
                     _first_value,
                     _free_rent_months,
                     _guarantee_first_yen,
                     _guarantee_rate,
                     _guard_rent_multiple,
                     _hosho_fixed_yen,
                     _initial_fixed_yen,
                     _labeled_yen,
                     _support_fees,
                     _yen_or_ratio,
                     money_pair,
                     to_yen,
)
from ._normalize import (
                     _DASH,
                     _LAYOUT_RE,
                     _NUM,
                     CFG,
                     STRIP_PATTERNS,
                     _strip_reading_parens,
                     canonical_url,
                     jnc_id,
                     nfkc,
                     normalize_address,
                     normalize_building_name,
                     strip_building_name,
)
from ._stations import _STATION_RE, parse_stations

__all__ = [
                     "AMENITY_HINT",
                     "CFG",
                     "STRIP_PATTERNS",
                     "_DASH",
                     "_LAYOUT_RE",
                     "_NUM",
                     "_STATION_RE",
                     "_agency_yen",
                     "_cleaning_yen",
                     "_equipment_text",
                     "_find_yen",
                     "_first_value",
                     "_free_rent_months",
                     "_guarantee_first_yen",
                     "_guarantee_rate",
                     "_guard_rent_multiple",
                     "_hosho_fixed_yen",
                     "_initial_fixed_yen",
                     "_labeled_yen",
                     "_list_row",
                     "_strip_reading_parens",
                     "_support_fees",
                     "_table_map",
                     "_yen_or_ratio",
                     "canonical_url",
                     "jnc_id",
                     "money_pair",
                     "nfkc",
                     "normalize_address",
                     "normalize_building_name",
                     "parse_detail",
                     "parse_list",
                     "parse_stations",
                     "strip_building_name",
                     "to_yen",
]

"""実質費用・湯船5段階判定・100点スコア"""
import unicodedata
import yaml
from pathlib import Path
CFG = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))

def effective_monthly(rent, admin=0, water=0, support=0,
                      guarantee_renew=0, renewal_fee=0,
                      contract_months=24, nonrefund_init=0):
    return ((rent or 0) + (admin or 0) + (water or 0) + (support or 0)
            + (guarantee_renew or 0) / 12
            + (renewal_fee or 0) / (contract_months or 24)
            + (nonrefund_init or 0) / 24)

def total_2year(rent, admin=0, init_total=0, renewal_fee=0,
                guarantee_renew=0, free_months=0):
    return ((rent or 0) + (admin or 0)) * 24 + (init_total or 0) \
        + (renewal_fee or 0) + (guarantee_renew or 0) * 2 \
        - (rent or 0) * (free_months or 0)

EXC = CFG["tub"]["exclude_keywords"]

def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").replace("\xa0", " ")


def _strip_excluded(t):
    for k in EXC:
        t = t.replace(k, "")
    return t


def _get_text_sources(d):
    """Get all available text sources from detail parse result for tub judgment."""
    sources = []
    # Primary: equipment field
    eq = d.get("equipment") or ""
    if eq:
        sources.append(_strip_excluded(eq))
    # Secondary: note field (contains other initial costs and features)
    note = d.get("note") or ""
    if note:
        sources.append(_strip_excluded(note))
    # Tertiary: full text from property view table
    full = nfkc(d.get("full") or "")
    if full:
        sources.append(_strip_excluded(full))
    return sources


def _judge_text(t):
    """1つのテキスト源だけを判定。キーワード無しは None。"""
    t = _strip_excluded(t or "")
    for kw in CFG["tub"]["confirmed_no"]:
        if kw in t:
            return "confirmed_no_tub", kw, 0.95
    for kw in CFG["tub"]["confirmed_yes"]:
        if kw in t:
            return "confirmed_tub", kw, 0.95
    for kw in CFG["tub"]["likely_no"]:
        if kw in t:
            return "likely_no_tub", kw, 0.6
    for kw in CFG["tub"]["likely_yes"]:
        if kw in t:
            return "likely_tub", kw, 0.6
    return None


def judge_tub(d):
    """-> (status, keyword, confidence)

    情報源ごとに判定し、設備 -> 備考 -> 全文の優先順で最初に
    判定が付いた源を採用する。従来は全源を混ぜて先勝ち判定だったため、
    設備に「ユニットバス」とあっても備考の「シャワーのみ」で
    湯船なし確定になるような矛盾が起きていた。
    """
    if isinstance(d, str):
        sources = [d]
    elif isinstance(d, dict):
        sources = _get_text_sources(d)
    else:
        sources = []
    for s in sources:
        r = _judge_text(s)
        if r:
            return r
    return "unknown", "", 0.0

def score_unit(u, weights=None):
    """100点満点: total30/tub20/transit15/size10/noise10/equip8/safety7。
    u: dict(total, tub_status, walk_min, area, equip,
    highway_m, road_m, floor, cancel_penalty, missing,
    autolock, elevator, new_seismic) -> (score, reasons)"""
    w = weights or CFG["weights"]
    R = CFG["rules"]
    s, reasons = 0, []
    must = R["must_total_max"]
    total = u.get("total") or 0
    if total > must:
        return -999, ["must_total over"]
    # 総額30点: must-2万以下で満点、mustで0点へ線形
    s += w["total"] * max(0, 1 - (total - (must - 20000)) / 20000) \
        if total > must - 20000 else w["total"]
    reasons.append(f"total {total}")
    # 湯船: config の tub_scores をカテゴリ最大値比として使う
    # （従来は同じ比率がコードにハードコードされ config が効かなかった）
    tub_scores = R.get("tub_scores") or {}
    ts = u.get("tub_status", "unknown")
    if tub_scores:
        top = max(tub_scores.values()) or 1
        s += w["tub"] * (tub_scores.get(ts, 0) / top)
    reasons.append(f"tub {ts}")
    # 交通: config の transit_walk5/walk10 の比率で按分
    wk = u.get("walk_min")
    if wk is not None:
        t5 = R.get("transit_walk5") or 8
        t10 = R.get("transit_walk10") or 4
        if wk <= 5:
            s += w["transit"]; reasons.append("walk<=5")
        elif wk <= 10:
            s += w["transit"] * (t10 / t5); reasons.append("walk<=10")
    # 広さ10点: 20m2で満点、15m2で0へ線形
    area = u.get("area") or 0
    s += w["size"] * min(1, max(0, (area - 15) / 5))
    reasons.append(f"area {area}")
    # 騒音10点: 満点から減点
    nz = w["noise"]
    if (u.get("highway_m") or 9999) <= 100:
        nz += R["highway100"]; reasons.append("highway-10")
    if (u.get("road_m") or 9999) <= 50:
        nz += R["road50"]; reasons.append("road-10")
    if (u.get("floor") or 2) <= 1:
        nz += R["penalty_1f"]; reasons.append("1F-5")
    s += max(0, nz)
    # 設備: config の free_net / washstand（合計はカテゴリ重みで頭打ち）
    eq = u.get("equip") or ""
    eq_pts = 0.0
    if "無料" in eq and "インターネット" in eq:
        eq_pts += R.get("free_net", w["equip"] / 2); reasons.append("free-net")
    if "独立" in eq and "洗面" in eq:
        eq_pts += R.get("washstand", w["equip"] / 2); reasons.append("washstand")
    s += min(eq_pts, w["equip"])
    # 防災防犯7点: 新耐震・オートロック・2階以上で加点、欠損で減点
    sf = 0.0
    if u.get("new_seismic"):
        sf += w["safety"] * 0.4
    if u.get("autolock"):
        sf += w["safety"] * 0.3
    if (u.get("floor") or 1) >= 2:
        sf += w["safety"] * 0.3
    if u.get("cancel_penalty"):
        sf += R["penalty_short_cancel2m"]; reasons.append("cancel-10")
    if u.get("missing"):
        sf += R["missing_info"]; reasons.append("missing-5")
    s += max(0, sf)
    return round(s, 1), reasons

"""実質費用・湯船5段階判定・100点スコア"""
from pathlib import Path

import yaml

from parse_suumo import nfkc

CFG = yaml.safe_load(
    (Path(__file__).parent / "config.yaml").read_text())


def effective_monthly(rent, admin=0, water=0,
                      guarantee_renew=0, renewal_fee=0,
                      contract_months=24, nonrefund_init=0,
                      support_monthly=0, renewal_admin_fee=0):
    """実質月額。

    入居時一時金（サポート一時金等）は月額に混ぜない。月額型
    サポートは support_monthly のみを加算する（従来は一時金
    46,200円が毎月 +46,200円に化けていた）。contract_months が
    不明（NULL）のときは 24ヶ月とみなして更新料を按分する。
    更新事務手数料は更新料と同時に発生するため同じ按分で加える。
    """
    return ((rent or 0) + (admin or 0) + (water or 0)
            + (support_monthly or 0)
            + (guarantee_renew or 0) / 12
            + (renewal_fee or 0) / (contract_months or 24)
            + (renewal_admin_fee or 0) / (contract_months or 24)
            + (nonrefund_init or 0) / 24)

def total_2year(rent, admin=0, init_total=0, renewal_fee=0,
                guarantee_renew=0, free_months=0,
                support_once=0, support_monthly=0, contract_months=None,
                renewal_admin_fee=0):
    """2年総額。サポート費は 一時金 + 月額×契約月数 で計上する
    （従来は完全に無視され、月額990円の物件で 23,760円脱落した）。
    contract_months 不明時は 24ヶ月で計算する。
    更新事務手数料は更新料と同じく2年内に1回発生するものとして加える。"""
    months = contract_months or 24
    return ((rent or 0) + (admin or 0)) * 24 + (init_total or 0) \
        + (renewal_fee or 0) + (renewal_admin_fee or 0) \
        + (guarantee_renew or 0) * 2 \
        + (support_once or 0) + (support_monthly or 0) * months \
        - (rent or 0) * (free_months or 0)

EXC = CFG["tub"]["exclude_keywords"]

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
    """1つのテキスト源だけを判定。キーワード無しは None。

    浴槽の実在証拠（ユニットバス/追焚/バストイレ別/浴室乾燥 等）が
    あれば湯船側を優先する。「シャワールーム」「シャワーブース」は
    浴槽と共存しうる弱い信号でしかなく（設備タグに両方が並ぶ物件が
    多数ある）、それ単独でも共存時でも湯船なし側には倒さない。
    実ページ検証では likely_no_tub が 5件中5件誤りだった。
    湯船なし側は「シャワーのみ」「浴槽なし」等の明示表現
    （confirmed_no）がある場合だけ採用する。
    """
    t = _strip_excluded(t or "")
    for kw in CFG["tub"]["confirmed_yes"]:
        if kw in t:
            return "confirmed_tub", kw, 0.95
    for kw in CFG["tub"]["likely_yes"]:
        if kw in t:
            return "likely_tub", kw, 0.6
    for kw in CFG["tub"]["confirmed_no"]:
        if kw in t:
            return "confirmed_no_tub", kw, 0.95
    return None


_TUB_PRIORITY = ("confirmed_tub", "likely_tub",
                 "confirmed_no_tub", "likely_no_tub")


def aggregate_tub_status(verdicts):
    """unit 内の複数 listing の判定を1つに集約する。

    同じ部屋が複数仲介で掲載されると listing ごとに判定が割れる
    （設備文の版差異）。last-writer-wins だと最後に取得した1件の
    誤判定が unit 全体に広がるため、強い浴槽証拠が1件でもあれば
    unit は湯船側とし、湯船なしは全 listing が湯船なし側の
    ときだけ採用する。
    verdicts: [(status, confidence), ...] -> (status, confidence)
    """
    for want in _TUB_PRIORITY:
        confs = [c for s, c in verdicts if s == want]
        if confs:
            return want, max(confs)
    return "unknown", 0.0


def is_shower_candidate(text):
    """シャワー候補（手動確認バケット）かどうか。

    設備文にシャワー設備の言及があり、湯船の証拠（確定・推定とも）
    が無く、湯船なし確定表現も無い文面。judge_tub が unknown を返す
    うち「シャワーのみの可能性が高い」部屋を拾うための述語で、
    tub_status 自体は変えない（表示・監査側でだけ使う）。
    """
    t = _strip_excluded(text or "")
    shower_words = CFG["tub"].get("likely_no") or []
    if not any(k in t for k in shower_words):
        return False
    if any(k in t for k in (CFG["tub"].get("confirmed_no") or [])):
        return False
    tub_words = (CFG["tub"].get("confirmed_yes") or []) \
        + (CFG["tub"].get("likely_yes") or [])
    return not any(k in t for k in tub_words)


_RECONCILE_METHOD = "reconcile"


def _reconcile_verdict(props):
    """1 unit 分の properties 行から復元判定を作る。

    props: [(has_bathtub, no_bathtub_evidence, equipment), ...]
    -> (tub_status, confidence, quote) 情報が無ければ None。

    evidence が失われた unit の復元なので、確定側には倒さず
    likely 側 (conf 0.6) を基本とする。湯船なし確定の文言
    (no_bathtub_evidence) が残っている場合だけ confirmed を許す。
    複数仲介で判定が割れる場合は湯船側勝ち
    (aggregate_tub_status と同じ規約)。
    """
    if not props:
        return None
    hbs = [p[0] for p in props]
    if 1 in hbs:
        quote = (next(p[2] for p in props if p[0] == 1) or "")[:400]
        return "likely_tub", 0.6, quote
    if any(h == 0 for h in hbs):
        no_ev = next((p[1] for p in props
                      if p[0] == 0 and p[1]), "")
        if no_ev:
            return "confirmed_no_tub", 0.95, no_ev[:400]
        quote = (next((p[2] for p in props if p[0] == 0), "") or "")[:400]
        return "likely_no_tub", 0.6, quote
    return None


def reconcile_tub(con):
    """units.tub_status を evidence / properties から再構築する。

    経緯: unit 融合合致の取り残しで listing を1つも持たない孤立
    unit が残り、また evidence を持たない unknown unit が
    properties.has_bathtub（最後の判定値）と矛盾して残っていた
    （実測: 孤立 1,684件 / 矛盾 568件、unknown 率 24.1%）。

    規約は変えない:
      1. listing を持たない孤立 unit と付随行
         (stations/amenities/evidence/favorites等) を削除
      2. evidence がある unit は aggregate_tub_status で再集約
         （evidence が審の上。現状と同一なら触れない）
      3. evidence 無し unit は properties から判定を復元し、
         method='reconcile' の evidence 行を残す
         （再実行の安全性と来歴のため。idempotent）

    -> レポート dict (deleted_units, reaggregated, restored, ...)
    """
    report = {"deleted_units": 0, "deleted_buildings": 0,
              "reaggregated": 0, "restored": 0, "still_unknown": 0}

    # 1. 孤立 unit 削除
    orphans = [r[0] for r in con.execute(
        "SELECT id FROM units u WHERE NOT EXISTS"
        " (SELECT 1 FROM listings l WHERE l.unit_id=u.id)")]
    if orphans:
        marks = ",".join("?" * len(orphans))
        for table in ("stations", "amenities", "evidence", "favorites",
                      "viewings", "contacts"):
            con.execute(f"DELETE FROM {table} WHERE unit_id IN ({marks})",
                        orphans)
        con.execute("DELETE FROM units WHERE id IN ({})".format(marks),
                    orphans)
        con.execute(
            "DELETE FROM buildings WHERE id IN (SELECT id FROM buildings b"
            " WHERE NOT EXISTS (SELECT 1 FROM units u"
            " WHERE u.building_id=b.id))")
    report["deleted_units"] = len(orphans)
    report["deleted_buildings"] = con.execute(
        "SELECT changes()").fetchone()[0] if orphans else 0

    # 2. evidence がある unit は再集約
    unit_ids = [r[0] for r in con.execute("SELECT id FROM units")]
    for uid in unit_ids:
        verdicts = [(r[0], r[1]) for r in con.execute(
            "SELECT tub_status, confidence FROM evidence"
            " WHERE unit_id=? AND tub_status != 'unknown'", (uid,))]
        status, conf = aggregate_tub_status(verdicts)
        row = con.execute(
            "SELECT tub_status, tub_confidence FROM units WHERE id=?",
            (uid,)).fetchone()
        if row and (row[0], row[1]) != (status, conf):
            con.execute("UPDATE units SET tub_status=?, tub_confidence=?"
                        " WHERE id=?", (status, conf, uid))
            report["reaggregated"] += 1

    # 3. evidence 無し unit は properties から復元
    bare = [r[0] for r in con.execute(
        "SELECT id FROM units u WHERE NOT EXISTS"
        " (SELECT 1 FROM evidence e WHERE e.unit_id=u.id)")]
    for uid in bare:
        props = [(r[0], r[1], r[2]) for r in con.execute(
            "SELECT p.has_bathtub, p.no_bathtub_evidence, p.equipment"
            " FROM listings l JOIN properties p ON p.detail_url=l.url"
            " WHERE l.unit_id=?", (uid,))]
        verdict = _reconcile_verdict(props)
        if verdict is None:
            report["still_unknown"] += 1
            continue
        status, conf, quote = verdict
        url = con.execute("SELECT url FROM listings WHERE unit_id=?"
                          " LIMIT 1", (uid,)).fetchone()
        con.execute("INSERT INTO evidence(unit_id,tub_status,quote,url,"
                    "method,confidence) VALUES(?,?,?,?,?,?)",
                    (uid, status, quote, url[0] if url else None,
                     _RECONCILE_METHOD, conf))
        con.execute("UPDATE units SET tub_status=?, tub_confidence=?"
                    " WHERE id=?", (status, conf, uid))
        report["restored"] += 1
    return report


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

def _score_total(total, w, R):
    """総額30点: must-2万以下で満点、mustで0点へ線形。"""
    must = R["must_total_max"]
    if total > must:
        return -999, None
    pts = w["total"] * max(0, 1 - (total - (must - 20000)) / 20000) \
        if total > must - 20000 else w["total"]
    return pts, [f"total {total}"]


def _score_tub(ts, w, R):
    """湯船: config の tub_scores をカテゴリ最大値比として使う
    （従来は同じ比率がコードにハードコードされ config が効かなかった）。"""
    tub_scores = R.get("tub_scores") or {}
    pts = 0.0
    if tub_scores:
        top = max(tub_scores.values()) or 1
        pts = w["tub"] * (tub_scores.get(ts, 0) / top)
    return pts, [f"tub {ts}"]


def _score_transit(walk_min, w, R):
    """交通: config の transit_walk5/walk10 の比率で按分。"""
    if walk_min is None:
        return 0.0, []
    t5 = R.get("transit_walk5") or 8
    t10 = R.get("transit_walk10") or 4
    if walk_min <= 5:
        return w["transit"], ["walk<=5"]
    if walk_min <= 10:
        return w["transit"] * (t10 / t5), ["walk<=10"]
    return 0.0, []


def _score_size(area, w):
    """広さ10点: 20m2で満点、15m2で0へ線形。"""
    return w["size"] * min(1, max(0, (area - 15) / 5)), [f"area {area}"]


def _score_noise(u, w, R):
    """騒音10点: 満点から減点。"""
    nz = w["noise"]
    reasons = []
    if (u.get("highway_m") or 9999) <= 100:
        nz += R["highway100"]
        reasons.append("highway-10")
    if (u.get("road_m") or 9999) <= 50:
        nz += R["road50"]
        reasons.append("road-10")
    if (u.get("floor") or 2) <= 1:
        nz += R["penalty_1f"]
        reasons.append("1F-5")
    return max(0, nz), reasons


def _score_equip(u, w, R):
    """設備: config の free_net / washstand（合計はカテゴリ重みで頭打ち）。"""
    eq = u.get("equip") or ""
    eq_pts = 0.0
    reasons = []
    if "無料" in eq and "インターネット" in eq:
        eq_pts += R.get("free_net", w["equip"] / 2)
        reasons.append("free-net")
    if "独立" in eq and "洗面" in eq:
        eq_pts += R.get("washstand", w["equip"] / 2)
        reasons.append("washstand")
    return min(eq_pts, w["equip"]), reasons


def _score_safety(u, w, R):
    """防災防犯7点: 新耐震・オートロック・2階以上で加点、欠損で減点。"""
    sf = 0.0
    reasons = []
    if u.get("new_seismic"):
        sf += w["safety"] * 0.4
    if u.get("autolock"):
        sf += w["safety"] * 0.3
    if (u.get("floor") or 1) >= 2:
        sf += w["safety"] * 0.3
    if u.get("cancel_penalty"):
        sf += R["penalty_short_cancel2m"]
        reasons.append("cancel-10")
    if u.get("missing"):
        sf += R["missing_info"]
        reasons.append("missing-5")
    return max(0, sf), reasons


def score_unit(u, weights=None):
    """100点満点: total30/tub20/transit15/size10/noise10/equip8/safety7。
    u: dict(total, tub_status, walk_min, area, equip,
    highway_m, road_m, floor, cancel_penalty, missing,
    autolock, elevator, new_seismic) -> (score, reasons)

    加点はカテゴリ別の _score_* ヘルパーに分解してある
    （重み配分と理由文字列は旧実装と同一）。
    """
    w = weights or CFG["weights"]
    R = CFG["rules"]
    total = u.get("total") or 0
    s, reasons = _score_total(total, w, R)
    if s == -999:
        return -999, ["must_total over"]
    ts = u.get("tub_status", "unknown")
    p, rs = _score_tub(ts, w, R)
    s += p
    reasons += rs
    p, rs = _score_transit(u.get("walk_min"), w, R)
    s += p
    reasons += rs
    p, rs = _score_size(u.get("area") or 0, w)
    s += p
    reasons += rs
    p, rs = _score_noise(u, w, R)
    s += p
    reasons += rs
    p, rs = _score_equip(u, w, R)
    s += p
    reasons += rs
    p, rs = _score_safety(u, w, R)
    s += p
    reasons += rs
    return round(s, 1), reasons

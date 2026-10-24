"""コスパ抽出: ヘドニック公正価値に対する割安度で優良物件をランキングする。

「同条件の平均より安い」方式は、駅や間取りが元々安いだけの物件を拾ってしまう。
ここでは log(総額) を属性で回帰した公正価値(fair)を基準に、実際の総額が
どれだけ割安かを残差で測る。単一の属性セルに依存しないため母数が薄い条件でも安定する。

公正価値モデルは Ridge(線形ヘドニック) と勾配ブースティングのブレンド
(--model で切替可)。賃料の非線形・交互作用を木モデルが拾い、線形が
小母数時の安定性を担保する。評価は建物GroupKFoldのOOFで統一。
分位点回帰の予測区間 (q10/q90) も併用し、実額が下限をも下回るものを
「堅い割安」(◎) として区別する。

使い方:
  python3 cost_perf.py                          # コスパ上位30件
  python3 cost_perf.py --top 50 --min-disc 0.12
  python3 cost_perf.py --walk-max 7 --min-area 20 --layout 1K 1DK
  python3 cost_perf.py --audit                  # クレンジング対象行を出力
  python3 cost_perf.py --json                   # 機械可読出力

注意:
  costs(初期費用)の取得率が低い場合は、賃料ベースの割安度のみ表示する。
  初期費用が揃う行は実質総額ベースのコスパも併記する。
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold

DB = Path(__file__).parent / "bukken.db"

# 希少レイアウトを代表区分へ寄せる
LAYOUT_MAP = {"ワンルーム": "1R", "ワンル": "1R", "1SLK": "1K", "1SK": "1K",
              "1SLDK": "1LDK", "2SLDK": "2LDK", "3SLDK": "3LDK"}
# 非返還初期費用(model.py の total_2year と同じ定義)
NONREFUND_COLS = ["key_money_yen", "agency_yen", "guarantee_first_yen",
                  "insurance_yen", "key_exchange_yen", "cleaning_yen"]

QUERY = """
SELECT p.id, p.name, p.station, p.address, p.walk_min, p.age_years,
       p.room_floor, p.rent_yen, p.admin_yen, p.total_yen, p.layout,
       p.area_m2, p.has_bathtub, p.equipment, p.detail_url,
       l.active AS listing_active, l.last_seen AS last_seen,
       c.fetched, c.key_money_yen, c.deposit_yen, c.agency_yen,
       c.guarantee_first_yen, c.guarantee_renew_yen, c.insurance_yen,
       c.key_exchange_yen, c.cleaning_yen, c.support_yen,
       c.water_fixed_yen, c.renewal_fee_yen, c.contract_months,
       c.free_rent_months, u.building_id,
       u.direction AS u_direction, u.corner AS u_corner,
       u.tub_status AS u_tub_status,
       u.tub_confidence AS u_tub_confidence,
       b.structure AS b_structure, b.floors AS b_floors,
       b.autolock AS b_autolock, b.elevator AS b_elevator,
       b.delivery_box AS b_delivery_box
FROM properties p
JOIN listings l ON l.url = p.detail_url
LEFT JOIN units u ON u.id = l.unit_id
LEFT JOIN buildings b ON b.id = u.building_id
LEFT JOIN costs c ON c.listing_id = l.id
"""


def jnc(url):
    m = re.search(r"jnc_(\d+)", url or "")
    return m.group(1) if m else None


def load(con):
    return pd.read_sql_query(QUERY, con)


def audit(df):
    """クレンジング対象を列挙する(母集団は触らずレポートのみ)。"""
    df = df.assign(jnc=df.detail_url.map(jnc))
    bad_admin = (df.admin_yen > df.rent_yen * 0.5) & (df.area_m2 < 40)
    dup = df[df.duplicated("jnc", keep=False) & df.jnc.notna()]
    report = {
        "admin_parse_error": df.loc[bad_admin, ["id", "name", "rent_yen",
                                                "admin_yen", "area_m2"]]
        .to_dict("records"),
        "admin_parse_error_n": int(bad_admin.sum()),
        "duplicate_jnc_n": int(dup.shape[0]),
        "duplicate_jnc_excess": int(dup.shape[0] - dup.jnc.nunique()),
        "station_missing_n": int((df.station.isna()
                                  | (df.station == "")).sum()),
        "area_lt12_n": int((df.area_m2 < 12).sum()),
        "area_gt110_n": int((df.area_m2 > 110).sum()),
        "bath_unknown_n": int(((df.has_bathtub == -1)
                               | df.has_bathtub.isna()).sum()),
        "equipment_empty_n": int((df.equipment.isna()
                                  | (df.equipment == "")).sum()),
    }
    return report


def clean(df):
    """クレンジング前でも破綻しないよう防御的に処理する。"""
    df = df.assign(jnc=df.detail_url.map(jnc)).sort_values("id")
    # jnc不明行は保持し、同一SUUMO物件(jnc)だけ1行へ
    known = df.jnc.notna()
    df = pd.concat([
        df.loc[~known],
        df.loc[known].drop_duplicates("jnc", keep="last"),
    ]).sort_index()

    # 管理費パース破損を無効化し total を再計算
    bad = (df.admin_yen > df.rent_yen * 0.5) & (df.area_m2 < 40)
    df.loc[bad, "admin_yen"] = np.nan
    df["total_yen"] = df.rent_yen + df.admin_yen.fillna(0)

    df["station"] = (df.station.fillna("NA").replace("", "NA"))
    df["layout"] = df.layout.replace(LAYOUT_MAP)
    df["layout"] = df.layout.fillna("NA")
    df["age_years"] = df.age_years.clip(0, 60)
    df["room_floor"] = df.room_floor.clip(1, 30)
    return df


def scope(df, a):
    m = (
        df.total_yen.between(getattr(a, "min_total", 45000), a.max_total)
        & df.area_m2.between(a.min_area, a.max_area)
        & df.walk_min.between(0, a.walk_max)
        & (df.station != "NA")
    )
    # 募集終了・陳腐化した物件を母集団から外す（従来は properties の
    # 全行が対象で、終了物件が「割安」に混ざっていた）
    if "listing_active" in df.columns:
        m &= df.listing_active.fillna(0).astype(int) == 1
    if a.max_age_days and "last_seen" in df.columns:
        seen = pd.to_datetime(df.last_seen, errors="coerce")
        # DBの時刻は UTC 統一。手元のローカル時刻と比べると9時間ずれる
        cutoff = pd.Timestamp.now(tz="UTC").tz_localize(None) \
            - pd.Timedelta(days=a.max_age_days)
        m &= seen.isna() | (seen >= cutoff)
    if a.layout:
        m &= df.layout.isin(a.layout)
    if a.station:
        m &= df.station.isin(a.station)
    if a.no_tub:
        m &= df.has_bathtub == 0
    return df[m].copy()


def parse_total_floors(text):
    """建物の総階数テキスト (例 '10階建', '地上12階地下1階') から総階数を取る。"""
    if not isinstance(text, str):
        return np.nan
    if text.strip().isdigit():
        return float(text.strip())  # buildings.floors は '10' 等の数値文字列
    m = re.search(r"(\d+)\s*階建", text)
    if m:
        return float(m.group(1))
    m = re.search(r"地上\s*(\d+)\s*階", text)
    return float(m.group(1)) if m else np.nan


def norm_structure(text):
    """構造表記を代表区分へ寄せる。"""
    if not isinstance(text, str) or not text:
        return "NA"
    for key in ("SRC", "RC", "S造", "鉄骨", "木造", "ALC", "ブロック"):
        if key in text:
            return {"S造": "S", "鉄骨": "S"}.get(key, key)
    return "OTHER"


# 設備テキストに含まれると賃料に効きやすい語 (詳細取得で埋まる)
EQUIP_KEYS = {
    "equip_washlet": "温水洗浄便座",
    "equip_bath_dry": "浴室乾燥",
    "equip_reheat": "追焚",
    "equip_sys_kitchen": "システムキッチン",
    "equip_flooring": "フローリング",
    "equip_washstand": "洗面所独立",
}


def build_features(df):
    X = pd.get_dummies(df[["station", "layout"]], drop_first=True)
    if "b_structure" in df.columns:
        X = pd.concat([X, pd.get_dummies(
            df["b_structure"].map(norm_structure), prefix="struct",
            drop_first=True)], axis=1)
    X["area"] = df.area_m2
    X["area_sq"] = df.area_m2 ** 2
    X["log_area"] = np.log(df.area_m2.clip(lower=1))
    X["age"] = df.age_years
    X["age_sq"] = df.age_years ** 2
    X["walk"] = df.walk_min
    X["walk_sq"] = df.walk_min ** 2
    X["floor"] = df.room_floor
    # 相対階数 (最上階・高層階はプレミアムが付きやすい)
    if "b_floors" in df.columns:
        total_floors = df["b_floors"].map(parse_total_floors)
        X["floor_ratio"] = df.room_floor / total_floors
        X["is_top_floor"] = (df.room_floor >= total_floors).astype(float)
    # 湯船の有無は賃料に効く。特徴に入れないと「湯船なし物件は
    # 構造的に安い」分まで割安と誤認する（このDBの主目的が
    # 湯船なし探しなので特に重要）
    hb = pd.to_numeric(df.get("has_bathtub"), errors="coerce")
    X["no_tub"] = (hb == 0).astype(float)
    X["has_tub"] = (hb == 1).astype(float)
    if "u_tub_confidence" in df.columns:
        X["tub_conf"] = pd.to_numeric(df["u_tub_confidence"],
                                      errors="coerce")
    # 建物設備・部屋属性 (詳細取得で埋まる。未取得は0として扱う)
    for col, name in (("b_autolock", "autolock"), ("b_elevator", "elevator"),
                      ("b_delivery_box", "delivery_box"),
                      ("u_corner", "corner")):
        if col in df.columns:
            X[name] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "u_direction" in df.columns:
        X["south"] = df["u_direction"].fillna("") \
            .str.contains("南").astype(float)
    if "equipment" in df.columns:
        eq = df["equipment"].fillna("")
        for name, key in EQUIP_KEYS.items():
            X[name] = eq.str.contains(key, regex=False).astype(float)
    X = X.astype(float)
    # 築年数・階数などは欠落が普通にある。NaN のままだと回帰が
    # 例外で落ちて cost_perf 自体が動かない（実DBで発生）。
    # 中央値で補完し、主要列は欠落自体も特徴として残す。
    for col in ("area", "age", "walk", "floor"):
        if col in X.columns:
            X[col + "_missing"] = X[col].isna().astype(float)
            X[col] = X[col].fillna(X[col].median())
    for col in ("area_sq", "log_area", "age_sq", "walk_sq", "floor_ratio",
                "tub_conf"):
        if col in X.columns:
            X[col] = X[col].fillna(X[col].median())
    return X.fillna(0.0)


def make_gbm():
    """勾配ブースティング (不動産価格推定の実務標準)。

    賃料は非線形・交互作用が強い (徒歩分数の逓減、築年数の非線形、
    駅×間取り) ため木モデルが線形より合う。一方で母数が小さいと
    過学習しやすいので、葉を大きめ・学習率低めの保守設定にし、
    評価は建物GroupKFoldのOOFで厳密に行う。
    """
    return HistGradientBoostingRegressor(
        learning_rate=0.05, max_iter=500, max_leaf_nodes=31,
        min_samples_leaf=30, l2_regularization=1.0, random_state=0)


def fit_fair(df, alpha, model="blend"):
    """公正価値(賃料ベース月額)を返す。建物単位のGroupKFoldで品質を測る。

    ranking には OOF(学習に使っていない予測)を使う。学習データ自身の残差は
    割安度が楽観的に出るため。--insample 指定時は全学習予測を使う。

    model: ridge (線形ヘドニック) / gbm (勾配ブースティング) /
    blend (両者のOOFをMAE逆数で加重平均; 既定)。
    あわせて分位点回帰で予測区間 (q10/q90) を返し、実額が下限をも
    下回る「堅い割安」を区別できるようにする。
    """
    X = build_features(df)
    y = np.log(df.total_yen.values)
    # グループは建物IDを使う。物件名文字列だと同一建物が別名で
    # 学習/検証に漏れ、逆に無関係な建物が同じ説明名で混ざる
    if "building_id" in df.columns:
        groups = np.array([
            f"b{int(b)}" if pd.notna(b) else f"n{n}"
            for b, n in zip(df["building_id"], df["name"])])
    else:
        groups = df.name.values
    n_groups = len(set(groups))

    factories = {"ridge": lambda: Ridge(alpha=alpha), "gbm": make_gbm}
    names = ["ridge", "gbm"] if model == "blend" else [model]
    splits = None
    if n_groups >= 2:
        gkf = GroupKFold(n_splits=min(5, n_groups))
        splits = list(gkf.split(X, y, groups))

    oof_log, ins_log, metrics = {}, {}, {}
    for name in names:
        if splits:
            pred = np.zeros(len(df))
            for tr, te in splits:
                pred[te] = factories[name]().fit(X.iloc[tr], y[tr]) \
                    .predict(X.iloc[te])
            oof_log[name] = pred
        else:
            oof_log[name] = factories[name]().fit(X, y).predict(X)
        ins_log[name] = factories[name]().fit(X, y).predict(X)
        r2 = 1 - np.sum((y - oof_log[name]) ** 2) / np.sum((y - y.mean()) ** 2)
        mae = mean_absolute_error(df.total_yen, np.exp(oof_log[name]))
        metrics[name] = {"r2": float(r2), "mae_yen": float(mae)}

    if model == "blend":
        wts = {n: 1.0 / max(metrics[n]["mae_yen"], 1.0) for n in names}
        tot = sum(wts.values())
        oof = sum(oof_log[n] * wts[n] for n in names) / tot
        ins = sum(ins_log[n] * wts[n] for n in names) / tot
        weights = {n: wts[n] / tot for n in names}
    else:
        oof, ins = oof_log[model], ins_log[model]
        weights = {model: 1.0}

    r2 = 1 - np.sum((y - oof) ** 2) / np.sum((y - y.mean()) ** 2)
    mae = mean_absolute_error(df.total_yen, np.exp(oof))
    sigma = max(float(np.std(y - oof)), np.finfo(float).eps)

    # 予測区間 (分位点回帰, 全データ学習)。区間自体の表示と、
    # 実額 < q10 の「堅い割安」判定に使う。
    q = {}
    for a_q, key in ((0.10, "q10"), (0.90, "q90")):
        try:
            mq = HistGradientBoostingRegressor(
                loss="quantile", quantile=a_q, learning_rate=0.05,
                max_iter=300, max_leaf_nodes=31, min_samples_leaf=30,
                l2_regularization=1.0, random_state=0).fit(X, y)
            q[key] = np.exp(mq.predict(X))
        except Exception:
            q[key] = np.full(len(df), np.nan)

    return np.exp(oof), np.exp(ins), {
        "r2": float(r2), "mae_yen": float(mae), "sigma_log": sigma,
        "models": metrics, "weights": weights,
        "q10": q["q10"], "q90": q["q90"]}


def value_or_zero(value):
    return value if pd.notna(value) else 0


def nonrefund_total(r):
    return sum(value_or_zero(r[col]) for col in NONREFUND_COLS)


def effective_monthly(r):
    """実質月額: 管理費+水道+サポート+更新/契約月+保証更新/12+初期非返還/24。"""
    months = value_or_zero(r.contract_months) or 24
    return (r.total_yen + value_or_zero(r.water_fixed_yen)
            + value_or_zero(r.support_yen)
            + value_or_zero(r.guarantee_renew_yen) / 12
            + value_or_zero(r.renewal_fee_yen) / months
            + nonrefund_total(r) / 24)


def total_2year(r):
    return (r.total_yen * 24 + nonrefund_total(r) + value_or_zero(r.deposit_yen)
            + value_or_zero(r.renewal_fee_yen)
            + value_or_zero(r.guarantee_renew_yen) * 2
            # フリーレント控除は models.total_2year と同じく家賃分のみ
            - r.rent_yen * value_or_zero(r.free_rent_months))


def rank(df, fair, meta, a):
    out = df.copy()
    out["fair"] = fair
    out["discount"] = 1 - out.total_yen / out.fair
    out["save_yen"] = out.fair - out.total_yen
    out["z"] = -out.discount / meta["sigma_log"]
    out.loc[out.discount <= 0, "discount"] = 0
    if "q10" in meta:
        out["fair_q10"] = np.asarray(meta["q10"], dtype=float)
        out["fair_q90"] = np.asarray(meta["q90"], dtype=float)
        # 堅い割安: 実額が予測区間の下限 (q10) をも下回る
        out["robust"] = (out.total_yen < out.fair_q10).astype(int)

    fetched = out.fetched.fillna(0).astype(int) == 1
    if fetched.any():
        out.loc[fetched, "eff_monthly"] = out[fetched].apply(
            effective_monthly, axis=1)
        out.loc[fetched, "t2"] = out[fetched].apply(total_2year, axis=1)
        # 初期費用が揃う行は総額ベースのコスパも算出
        eff = out.eff_monthly
        out.loc[fetched, "cost_perf"] = out.loc[fetched, "fair"] / eff[fetched]

    out = out[out.discount >= a.min_disc]
    out = out.sort_values("discount", ascending=False)
    return out.head(a.top)


def fmt(row, a):
    flag = " !" if row.z >= 3 else ""
    base = (f"[{row.discount:5.1%}] -{row.save_yen/10000:4.2f}万 "
            f"実{row.total_yen/10000:4.1f}万(公{row.fair/10000:4.1f}万) "
            f"{row.layout:>4} {row.area_m2:5.1f}m2 歩{row.walk_min}分 "
            f"築{row.age_years}年 {row.station} | {row['name']}{flag}")
    if pd.notna(row.get("robust")) and row.get("robust"):
        base += " | ◎堅い割安"
    if pd.notna(row.get("cost_perf")):
        base += f" | 総額コスパ{row.cost_perf:4.2f} 2年{row.t2/10000:.1f}万"
    return base


def main():
    ap = argparse.ArgumentParser(description="ヘドニック割安度で優良物件抽出")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--min-disc", type=float, default=0.0, dest="min_disc")
    ap.add_argument("--max-total", type=int, default=300000, dest="max_total")
    ap.add_argument("--min-total", type=int, default=45000, dest="min_total",
                    help="母集団の総額下限（従来は 45000 で固定だった）")
    ap.add_argument("--min-area", type=float, default=12, dest="min_area")
    ap.add_argument("--max-area", type=float, default=110, dest="max_area")
    ap.add_argument("--walk-max", type=int, default=15, dest="walk_max")
    ap.add_argument("--max-age-days", type=int, default=14, dest="max_age_days",
                    help="last_seen がこの日数より古い物件を母集団から"
                         "外す (0=無制限)")
    ap.add_argument("--layout", nargs="*")
    ap.add_argument("--station", nargs="*")
    ap.add_argument("--no-tub", action="store_true", dest="no_tub")
    ap.add_argument("--alpha", type=float, default=3.0)
    ap.add_argument("--model", choices=["blend", "ridge", "gbm"],
                    default="blend",
                    help="公正価値モデル (既定: ridge+gbm のブレンド)")
    ap.add_argument("--insample", action="store_true",
                    help="ランキングに学習データ自身の予測を使う(楽観的)")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with sqlite3.connect(DB) as con:
        raw = load(con)

    if a.audit:
        print(json.dumps(audit(raw), ensure_ascii=False, indent=2))
        return

    df = clean(raw)
    df = scope(df, a)
    if len(df) < 30:
        print(f"母数不足: {len(df)}件。フィルタを緩めてください。")
        return

    cv_pred, insample, meta = fit_fair(df, a.alpha, a.model)
    fair = insample if a.insample else cv_pred
    hits = rank(df, fair, meta, a)

    if a.json:
        cols = ["name", "station", "layout", "area_m2", "age_years", "walk_min",
                "room_floor", "rent_yen", "admin_yen", "total_yen", "fair",
                "fair_q10", "fair_q90", "robust",
                "discount", "save_yen", "detail_url"]
        cols = [c for c in cols if c in hits.columns]
        print(json.dumps(hits[cols].to_dict("records"),
                         ensure_ascii=False, default=float, indent=2))
        return

    n_fetched = int((df.fetched.fillna(0).astype(int) == 1).sum()) \
        if "fetched" in df.columns else 0
    print(f"母数{len(df)}件 (詳細取得済み {n_fetched}件"
          f"={n_fetched / len(df):.0%}) / モデル CV R2={meta['r2']:.3f} "
          f"MAE={meta['mae_yen']:.0f}円 / ヒット{len(hits)}件 "
          f"(!は要データ確認の外れ値)")
    for name, mm in meta.get("models", {}).items():
        w = meta.get("weights", {}).get(name)
        wtxt = f" 重み{w:.2f}" if w is not None and len(meta["models"]) > 1 \
            else ""
        print(f"  モデル {name}: CV R2={mm['r2']:.3f} "
              f"MAE={mm['mae_yen']:.0f}円{wtxt}")
    for _, row in hits.iterrows():
        print(fmt(row, a))


if __name__ == "__main__":
    main()

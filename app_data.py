"""選別画面 (app.py) のデータ層。Streamlit 非依存で単体テスト可能にする。

cost_perf のヘドニック公正価値モデルと実質費用計算を UI 用の
DataFrame にまとめる。フィルタは cost_perf.scope を1つの実装として
使う（CLI と画面で母集団の定義をズラさない）。
"""
import sqlite3
from types import SimpleNamespace

import pandas as pd

import cost_perf as cp

DEFAULT_FILTERS = {
    "max_total": 100000,
    "min_total": 45000,
    "min_area": 12,
    "max_area": 110,
    "walk_max": 10,
    "max_age_days": 14,
    "layout": None,
    "station": None,
    "no_tub": False,
}


def load_df(db_path=None):
    """母集団 (全active行) を cost_perf の抽出/クレンジングで読む。

    実質月額 (eff_monthly) と2年総額 (t2) は初期費用取得済み行のみ
    算出する (cost_perf.rank と同じ条件)。
    """
    con = sqlite3.connect(str(db_path or cp.DB))
    try:
        raw = cp.load(con)
    finally:
        con.close()
    df = cp.clean(raw)
    fetched = df["fetched"].fillna(0).astype(int) == 1
    if fetched.any():
        df.loc[fetched, "eff_monthly"] = df[fetched].apply(
            cp.effective_monthly, axis=1)
        df.loc[fetched, "t2"] = df[fetched].apply(cp.total_2year, axis=1)
    return df


def apply_filters(df, **overrides):
    """UI のフィルタ値を cost_perf.scope へ渡す。"""
    params = dict(DEFAULT_FILTERS)
    params.update({k: v for k, v in overrides.items() if k in params})
    return cp.scope(df, SimpleNamespace(**params))


def add_fair_value(df, alpha=3.0, model="ridge"):
    """公正価値・割安度列を付与して (df, meta) を返す。

    母数が30未満のときはモデルを建てず fair=total (割安度0)。
    model は既定で ridge (画面描画を優先。CLI の blend と比べて
    数秒で返り、評価指標はメタで確認できる)。
    """
    out = df.copy()
    if len(out) >= 30:
        fair, _insample, meta = cp.fit_fair(out, alpha, model)
    else:
        fair = out["total_yen"].to_numpy(dtype=float)
        meta = {"r2": None, "mae_yen": None, "note": "母数不足で fair=total"}
    out["fair"] = fair
    out["discount"] = (1.0 - out["total_yen"] / out["fair"]).clip(lower=0)
    out["save_yen"] = out["fair"] - out["total_yen"]
    return out, meta


def map_points(df):
    """マップ描画用に緯度経度 (欠損除去) だけの DataFrame を返す。"""
    if "b_lat" not in df.columns:
        return pd.DataFrame(columns=["lat", "lon"])
    pts = df.loc[df["b_lat"].notna() & df["b_lon"].notna(),
                 ["b_lat", "b_lon"]].rename(columns={"b_lat": "lat",
                                                     "b_lon": "lon"})
    return pts


def equipment_keyword_mask(df, keyword):
    """設備キーワードの部分一致。空文字は全件通す。"""
    if not keyword:
        return pd.Series(True, index=df.index)
    return df["equipment"].fillna("").str.contains(keyword, regex=False)

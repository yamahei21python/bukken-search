"""Streamlit選別画面: マップ＋公正価値割安度＋実質費用＋証跡＋お気に入り。

データ処理は app_data.py (Streamlit 非依存) に集約し、このファイルは
UI の配線のみを行う。公正価値は cost_perf のヘドニックモデル
(ridge) をフィルタ条件単位でキャッシュして使う。
"""
import sqlite3

import streamlit as st

import app_data
from db import DB
from models import is_shower_candidate

st.set_page_config(layout="wide")
st.title("阿波座 賃貸選別")


@st.cache_data(show_spinner="データ読込中...")
def _load_df():
    return app_data.load_df()


@st.cache_data(show_spinner="公正価値を計算中...")
def _run_pipeline(max_total, min_total, min_area, max_area, walk_max,
                  max_age_days, layout, station):
    df = app_data.load_df()
    fdf = app_data.apply_filters(
        df, max_total=max_total, min_total=min_total, min_area=min_area,
        max_area=max_area, walk_max=walk_max, max_age_days=max_age_days,
        layout=layout, station=station)
    out, meta = app_data.add_fair_value(fdf)
    return out, meta


# --- フィルタ (サイドバー) ---
with st.sidebar:
    st.header("フィルタ")
    max_total = st.slider("総額上限(管理費込)", 50000, 150000, 100000, 5000)
    walk_max = st.slider("徒歩上限(分)", 1, 20, 10)
    min_area = st.slider("専有面積 下限(m2)", 0, 60, 12)
    max_area = st.slider("専有面積 上限(m2)", 10, 120, 110)
    tub = st.multiselect(
        "湯船状態",
        ["confirmed_no_tub", "likely_no_tub", "unknown",
         "likely_tub", "confirmed_tub"],
        default=["confirmed_no_tub", "likely_no_tub", "unknown"])
    layouts = st.multiselect("間取り", ["1R", "1K", "1DK", "1LDK", "2K", "2DK",
                                       "2LDK", "3LDK"])
    shower_only = st.checkbox(
        "シャワー候補のみ（湯船未判定で、設備にシャワー言及あり・湯船証拠なし）",
        value=False)
    equip_kw = st.text_input("設備キーワード (部分一致)",
                             help="例: オートロック、追焚、独立洗面")

out, meta = _run_pipeline(max_total, 45000, min_area, max_area, walk_max, 14,
                          layouts or None, None)

if tub:
    out = out[out["u_tub_status"].isin(tub)]
if shower_only:
    out = out[(out["u_tub_status"] == "unknown")
              & out["equipment"].fillna("").map(is_shower_candidate)]
mask = app_data.equipment_keyword_mask(out, equip_kw)
out = out[mask]

if len(out) == 0:
    st.warning("条件に合う物件がありません。フィルタを緩めてください。")
    st.stop()

# --- 指標ヘッダ ---
m_r2, m_mae = meta.get("r2"), meta.get("mae_yen")
metric_cols = st.columns(4)
metric_cols[0].metric("ヒット件数", f"{len(out):,}")
metric_cols[1].metric(
    "モデル CV R2", f"{m_r2:.3f}" if m_r2 is not None else "-")
metric_cols[2].metric(
    "MAE", f"{m_mae:,.0f}円" if m_mae is not None else "-")
fetched = out["fetched"].fillna(0).astype(int) == 1
metric_cols[3].metric("初期費用取得率", f"{fetched.mean():.0%}")

tab_table, tab_map, tab_detail = st.tabs(["一覧", "マップ", "詳細/記録"])

DISP_COLS = {
    "name": "建物", "station": "駅", "walk_min": "徒歩", "layout": "間取り",
    "area_m2": "面積m2", "room_floor": "階", "age_years": "築年",
    "total_yen": "総額", "fair": "公正価値", "discount": "割安度",
    "save_yen": "割安額", "eff_monthly": "実質月額", "t2": "2年総額",
    "u_tub_status": "湯船", "equipment": "設備", "detail_url": "URL",
}
show = out[[c for c in DISP_COLS if c in out.columns]].rename(
    columns=DISP_COLS)
show["割安度"] = (show["割安度"] * 100).round(1)
for c in ("総額", "公正価値", "割安額", "実質月額", "2年総額"):
    if c in show.columns:
        show[c] = (show[c] / 10000).round(2)

with tab_table:
    st.dataframe(
        show,
        column_config={
            "割安度": st.column_config.ProgressColumn(
                "割安度%", min_value=0,
                max_value=max(show["割安度"], default=1)),
            "URL": st.column_config.LinkColumn("URL"),
        },
        height=520, use_container_width=True)
    st.download_button("CSV出力", show.to_csv(index=False), "bukken.csv")
    if fetched.any():
        best = show.dropna(subset=["実質月額"]).sort_values("実質月額")
        if len(best):
            st.subheader("実質月額が安い順 TOP10 (初期費用取得済み)")
            st.dataframe(best.head(10), use_container_width=True)

with tab_map:
    pts = app_data.map_points(out)
    if len(pts):
        st.caption(f"緯度経度がある物件 {len(pts)} 件 (geocode 未取得分は除く)")
        st.map(pts)
    else:
        st.info("この条件には緯度経度付きの物件がありません。")

with tab_detail:
    sel = st.selectbox("物件URL", out["detail_url"].tolist())
    if sel:
        con = sqlite3.connect(DB)
        try:
            row = out[out["detail_url"] == sel].iloc[0]
            st.write(f"**{row['name']}** {row['layout']} "
                     f"{row['area_m2']}m2 {row['station']} 歩{row['walk_min']}分")
            st.write(f"総額 {row['total_yen']/10000:.2f}万 / "
                     f"公正価値 {row['fair']/10000:.2f}万 / 割安度 "
                     f"{row['discount']*100:.1f}%")
            st.write(row["equipment"])
            ev = con.execute(
                "SELECT tub_status,quote,url,method,confidence,checked_at"
                " FROM evidence WHERE url=? ORDER BY checked_at DESC LIMIT 5",
                (sel,)).fetchall()
            st.table(ev)
            memo = st.text_input("メモ・除外理由")
            if st.button("お気に入り登録"):
                uid = con.execute("SELECT unit_id FROM listings WHERE url=?",
                                  (sel,)).fetchone()
                if uid:
                    con.execute("INSERT OR REPLACE INTO favorites(unit_id,memo)"
                                " VALUES(?,?)", (uid[0], memo))
                    con.commit()
                    st.success("登録")
            q = st.text_input("問い合わせ内容")
            if st.button("問い合わせ記録"):
                uid = con.execute("SELECT unit_id FROM listings WHERE url=?",
                                  (sel,)).fetchone()
                if uid:
                    con.execute("INSERT INTO contacts(unit_id,question)"
                                " VALUES(?,?)", (uid[0], q))
                    con.commit()
                    st.success("記録")
        finally:
            con.close()

st.caption(f"母集団: {len(out):,}件 / モデル: cost_perf (ridge) / "
           f"フィルタ変更で公正価値を再計算します")

"""Streamlit選別画面: 表＋比較＋お気に入り＋除外理由＋メモ＋問合せ/内見＋CSV"""
import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st
DB = Path(__file__).parent / "bukken.db"

st.title("阿波座 賃貸選別")
max_total = st.slider("総額上限(管理費込)", 50000, 150000, 100000, 5000)
tub = st.multiselect("湯船状態", ["confirmed_no_tub", "likely_no_tub", "unknown",
                                  "likely_tub", "confirmed_tub"],
                     default=["confirmed_no_tub", "likely_no_tub", "unknown"])
con = sqlite3.connect(DB)
try:
    df = pd.read_sql_query(
        """SELECT b.name, l.rent_yen, l.admin_yen, l.rent_yen+COALESCE(l.admin_yen,0) total,
           u.layout, u.area_m2, u.floor, u.tub_status, l.url,
           p.equipment equip,
           (SELECT MIN(walk_min) FROM stations s WHERE s.unit_id=u.id) walk_min,
           (SELECT quote FROM evidence e WHERE e.unit_id=u.id ORDER BY e.checked_at DESC LIMIT 1) evidence
           FROM listings l JOIN units u ON u.id=l.unit_id
           JOIN buildings b ON b.id=u.building_id
           LEFT JOIN properties p ON p.detail_url=l.url WHERE l.active=1""", con)
except Exception as e:
    st.error(f"DBのスキーマが想定と違います（db_audit.py で状態を確認できます）: {e}")
    st.stop()
df = df[df["total"] <= max_total]
if tub:
    df = df[df["tub_status"].isin(tub)]
shower_only = st.checkbox(
    "シャワー候補のみ（湯船未判定で、設備にシャワー言及あり・湯船証拠なし）",
    value=False)
if shower_only:
    import models
    df = df[(df["tub_status"] == "unknown")
            & df["equip"].fillna("").map(models.is_shower_candidate)]
st.write(f"hit: {len(df)}")
st.dataframe(df)
st.download_button("CSV出力", df.to_csv(index=False), "bukken.csv")
sel = st.selectbox("詳細", df["url"].tolist() if len(df) else [])
if sel:
    st.write(sel)
    ev = con.execute("SELECT tub_status,quote,url,method,confidence,checked_at FROM evidence"
                     " WHERE url=? ORDER BY checked_at DESC LIMIT 5", (sel,)).fetchall()
    st.table(ev)
    memo = st.text_input("メモ・除外理由")
    if st.button("お気に入り登録"):
        uid = con.execute("SELECT unit_id FROM listings WHERE url=?", (sel,)).fetchone()
        if uid:
            con.execute("INSERT OR REPLACE INTO favorites(unit_id,memo) VALUES(?,?)", (uid[0], memo))
            con.commit(); st.success("登録")
    q = st.text_input("問い合わせ内容")
    if st.button("問い合わせ記録"):
        uid = con.execute("SELECT unit_id FROM listings WHERE url=?", (sel,)).fetchone()
        if uid:
            con.execute("INSERT INTO contacts(unit_id,question) VALUES(?,?)", (uid[0], q))
            con.commit(); st.success("記録")
con.close()

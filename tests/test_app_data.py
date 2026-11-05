"""app_data (選別画面データ層) のテスト。

repo の bukken.db (CI でも checkout される) を読み取り専用で使い、
画面と同じ経路 (load -> filter -> fair value) が壊れないことを
守る。DB への書き込みは行わない。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app_data
from db import DB

REQUIRED_COLS = [
    "name", "station", "walk_min", "layout", "area_m2", "room_floor",
    "age_years", "rent_yen", "admin_yen", "total_yen", "detail_url",
    "u_tub_status", "equipment", "fetched", "b_lat", "b_lon",
]


@unittest.skipUnless(DB.exists(), "bukken.db が無い環境では skip")
class TestAppData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = app_data.load_df()

    def test_load_columns(self):
        for col in REQUIRED_COLS:
            self.assertIn(col, self.df.columns)
        self.assertGreater(len(self.df), 1000)

    def test_eff_monthly_computed_for_fetched(self):
        fetched = self.df["fetched"].fillna(0).astype(int) == 1
        self.assertTrue(fetched.any(), "初期費用取得済み行が0件")
        eff = self.df.loc[fetched, "eff_monthly"]
        self.assertFalse(eff.isna().any())
        # 実質月額は総額以上 (初期費用が積み上がるため)
        self.assertTrue((eff >= self.df.loc[fetched, "total_yen"] - 0.5).all())

    def test_t2_only_for_fetched(self):
        unfetched = self.df["fetched"].fillna(0).astype(int) != 1
        if unfetched.any():
            self.assertTrue(self.df.loc[unfetched, "t2"].isna().all())

    def test_apply_filters(self):
        fdf = app_data.apply_filters(self.df)
        self.assertGreater(len(fdf), 0)
        self.assertTrue((fdf["total_yen"] <= 100000).all())
        self.assertTrue((fdf["walk_min"] <= 10).all())
        self.assertTrue((fdf["area_m2"] >= 12).all())
        # 母集団は active かつ14日以内に last_seen
        self.assertTrue(fdf["listing_active"].fillna(0).astype(int).eq(1).all())

    def test_apply_filters_layout(self):
        fdf = app_data.apply_filters(self.df, layout=["1K"])
        if len(fdf):
            self.assertTrue((fdf["layout"] == "1K").all())

    def test_add_fair_value(self):
        fdf = app_data.apply_filters(self.df)
        out, meta = app_data.add_fair_value(fdf)
        self.assertGreater(len(out), 30)
        self.assertIsNotNone(meta.get("r2"))
        # ridge 単体でも CV R2 が 0.6 を下回るようなら母集団か特徴が壊れている
        self.assertGreater(meta["r2"], 0.6)
        fair = out["fair"]
        self.assertTrue((fair > 0).all())
        self.assertTrue((out["discount"] >= 0).all())
        # 割安度の分布が非自明 (全員0や全員同値はモデルが死んでいる)
        self.assertGreater(out["discount"].std(), 0.01)

    def test_fair_value_small_sample_falls_back(self):
        small = self.df.head(10)
        out, meta = app_data.add_fair_value(small)
        self.assertIsNone(meta.get("r2"))
        self.assertTrue((out["discount"] == 0).all())

    def test_map_points(self):
        pts = app_data.map_points(self.df)
        self.assertGreater(len(pts), 0)
        self.assertEqual(list(pts.columns), ["lat", "lon"])
        self.assertTrue(pts["lat"].notna().all())
        # 大阪府内の座標範囲 (北緯34〜35度) を外れた geocode は異常
        self.assertTrue(((pts["lat"] > 34) & (pts["lat"] < 36)).all())

    def test_equipment_keyword_mask(self):
        self.assertTrue(app_data.equipment_keyword_mask(self.df, "").all())
        m = app_data.equipment_keyword_mask(self.df, "オートロック")
        self.assertGreater(int(m.sum()), 0)

    def test_display_table_scaling(self):
        fdf = app_data.apply_filters(self.df)
        out, _meta = app_data.add_fair_value(fdf)
        show = app_data.display_table(out.head(20))
        for col in ("建物", "駅", "総額", "公正価値", "割安度", "実質月額"):
            self.assertIn(col, show.columns)
        # 割安度は % 表記へ 100 倍されている (円比 0〜1 → 0〜100)
        self.assertTrue((show["割安度"] <= 100.0).all())
        # 金額列は万円単位へ換算されている
        for _s, raw in zip(show["総額"], out.head(20)["total_yen"],
                           strict=False):
            self.assertAlmostEqual(_s, round(raw / 10000, 2), places=2)
        self.assertTrue((show["総額"] < 30).all())


if __name__ == "__main__":
    unittest.main()

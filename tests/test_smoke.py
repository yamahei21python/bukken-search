"""スモークテスト: パーサ・判定・保存まわりの回帰防止。

7054c2e で詳細適用が全件エラーになっても気づけなかった反省から、
ネットワーク無しで最低限の経路を通す。実行: python3 -m unittest
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup

from models import judge_tub, score_unit
from parse_suumo import money_pair, parse_detail, to_yen


class TestMoney(unittest.TestCase):
    def test_to_yen(self):
        self.assertEqual(to_yen("8.55万円"), 85500)
        self.assertEqual(to_yen("2.675万円"), 26750)
        self.assertIsNone(to_yen("-"))

    def test_money_pair_range(self):
        # 範囲表記の第二値を管理費と誤認しない
        self.assertEqual(money_pair("8.5万円～9万円"), (85000, None))

    def test_money_pair_normal(self):
        self.assertEqual(money_pair("9.3万円 10000円"), (93000, 10000))


class TestJudgeTub(unittest.TestCase):
    def test_equipment_wins_over_note(self):
        d = {"equipment": "ユニットバス", "note": "シャワーのみ", "full": ""}
        self.assertEqual(judge_tub(d)[0], "confirmed_tub")

    def test_full_fallback(self):
        d = {"equipment": "", "note": "", "full": "お風呂はシャワーのみ"}
        self.assertEqual(judge_tub(d)[0], "confirmed_no_tub")

    def test_likely(self):
        d = {"equipment": "シャワールーム", "note": "", "full": ""}
        self.assertEqual(judge_tub(d)[0], "likely_no_tub")


class TestParseDetail(unittest.TestCase):
    def test_combined_deposit_key_money(self):
        html = ("<html><body><div class='property_view_note-info'>\n"
                "8.5万円\n管理費: 5000円\n敷金/礼金: -/8.5万円\n"
                "</div></body></html>")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertIsNone(d["deposit_yen"])
        self.assertEqual(d["key_money_yen"], 85000)

    def test_admin_guard(self):
        html = ("<html><body><div class='property_view_note-info'>\n"
                "8.5万円\n管理費: 9万円\n</div></body></html>")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertIsNone(d["admin_yen"])


class TestScore(unittest.TestCase):
    def test_score_uses_config(self):
        u = dict(total=80000, tub_status="likely_no_tub", walk_min=7,
                 area=22, floor=3, equip="インターネット無料、独立洗面台",
                 missing=False)
        sc, _ = score_unit(u)
        self.assertEqual(sc, 79.6)


class TestSavePreservesDetail(unittest.TestCase):
    """一覧の再保存で詳細情報（equipment/has_bathtub）が消えないこと。"""

    def setUp(self):
        import db as db_mod
        self.tmp = Path(__file__).parent / "_tmp_test.db"
        for suf in ("", "-wal", "-shm"):
            p = Path(str(self.tmp) + suf)
            if p.exists():
                p.unlink()
        self.orig = db_mod.DB
        db_mod.DB = self.tmp
        db_mod.initialize_db()

    def tearDown(self):
        import db as db_mod
        db_mod.DB = self.orig
        for suf in ("", "-wal", "-shm"):
            p = Path(str(self.tmp) + suf)
            if p.exists():
                p.unlink()

    def test_properties_not_wiped(self):
        import db as db_mod
        import scraper
        from detail_scraper import apply_detail
        row = {"name": "テスト", "address": "大阪市西区立売堀3",
               "age_years": 10, "floors": 5, "structure": "鉄筋系",
               "area_m2": 25.0, "layout": "1K", "floor": 3,
               "direction": None, "rent_yen": 80000, "admin_yen": 5000,
               "shikikin_yen": 0, "reikin_yen": 80000,
               "url": "https://suumo.jp/chintai/jnc_000999999999/",
               "stations": [{"line": "地下鉄中央線", "name": "阿波座",
                             "walk": 5}],
               "nearest": {"line": "地下鉄中央線", "name": "阿波座",
                           "walk": 5}}
        scraper.save([row])
        con = db_mod.connect_db()
        lid, uid = con.execute("SELECT id, unit_id FROM listings").fetchone()
        d = {"rent_yen": 80000, "admin_yen": 5000, "deposit_yen": 0,
             "key_money_yen": 80000, "hoshoukin_yen": None,
             "shoukyaku_yen": None, "insurance_yen": None,
             "key_exchange_yen": None, "cleaning_yen": None,
             "support_yen": None, "water_fixed_yen": None,
             "guarantee_first_yen": None, "guarantee_renew_yen": None,
             "agency_yen": 80000, "renewal_fee_yen": None,
             "contract_months": 24, "free_rent_months": 0,
             "regular_lease": 1, "direction": "南", "structure": "鉄筋系",
             "floors": 5, "equipment": "シャワールーム、オートロック",
             "note": "", "stations": [{"line": "地下鉄中央線",
                                       "name": "阿波座", "walk": 4}]}
        apply_detail(con, lid, uid, row["url"], d)
        con.commit()
        con.close()
        scraper.save([row])  # 翌日の一覧再取得に相当
        con = db_mod.connect_db()
        equip, hb, walk = con.execute(
            "SELECT equipment, has_bathtub, walk_min FROM properties"
        ).fetchone()
        con.close()
        self.assertTrue(equip)
        self.assertIsNotNone(hb)
        # 詳細側の徒歩（4分）が properties にも反映される
        self.assertEqual(walk, 4)


if __name__ == "__main__":
    unittest.main()

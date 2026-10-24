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

    def _with_other(self, other, price_lines="7.05万円\n管理費: 11000円\n"):
        return ("<html><body><div class='property_view_note-info'>\n"
                + price_lines + "</div>"
                "<table class='table_gaiyou'><tr><th>ほか初期費用</th>"
                f"<td>{other}</td></tr></table></body></html>")

    def test_agency_not_from_other_total(self):
        # 「合計X万円（内訳：…）」の合計額を仲介手数料と誤認しない
        html = self._with_other(
            "合計14.3万円（内訳：鍵交換代3.3万円 クリーニング費5.5万円）")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertIsNone(d["agency_yen"])
        self.assertEqual(d["key_exchange_yen"], 33000)
        self.assertEqual(d["cleaning_yen"], 55000)

    def test_agency_labeled(self):
        html = self._with_other("仲介手数料：5.94万円",
                                "5.4万円\n管理費: 5000円\n")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertEqual(d["agency_yen"], 59400)

    def test_agency_over_cap(self):
        # 仲介手数料は賃料の1.1ヶ月分が上限。超過は誤読として捨てる
        html = ("<html><body><div class='property_view_note-info'>\n"
                "7万円\n管理費: 5000円\n仲介手数料: 20万円\n"
                "</div></body></html>")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertIsNone(d["agency_yen"])

    def test_deposit_absurd_guard(self):
        # 円額を万円欄に入力した誤記（敷金: 435600万円）を通さない
        html = ("<html><body><div class='property_view_note-info'>\n"
                "6.6万円\n管理費: 7000円\n敷金: 435600万円\n"
                "</div></body></html>")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertIsNone(d["deposit_yen"])

    def test_support_glued_number_guard(self):
        # 商品名末尾の数字と金額の連結誤読（241.65万円）は合計超過で捨てる
        html = self._with_other(
            "合計5.5万円（内訳：アクト安心ライフ241.65万円"
            " あっとくらぶ1.1万円 鍵交換代2.75万円）",
            "6.2万円\n管理費: 8000円\n")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertIsNone(d["support_yen"])
        self.assertEqual(d["key_exchange_yen"], 27500)


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


class TestTimestampsUtc(unittest.TestCase):
    """DB時刻は UTC 統一（'localtime' を使うと実行環境でずれる）。"""

    def test_no_localtime_in_sql(self):
        root = Path(__file__).parent.parent
        offenders = []
        for f in list(root.glob("*.py")) + list(root.glob("*.sql")):
            if "localtime" in f.read_text(encoding="utf-8"):
                offenders.append(f.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

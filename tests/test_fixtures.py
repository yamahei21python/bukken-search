"""実ページ (bukken_html/) を使ったパーサ回帰テスト。

test_smoke.py は手作りスニペットで規則を検証するが、こちらは実際に
取得した SUUMO の一覧・詳細 HTML 全体を食わせ、構造変化や想定外の
表記ゆれでパーサが壊れないかを検証する。

フィクスチャは repo 同梱 (chore: バックアップ投入 で追加)。
無い環境では skip する。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup

from parse_suumo import parse_detail, parse_list

FIXTURES = Path(__file__).parent.parent / "bukken_html"

LIST_FILES = sorted(FIXTURES.glob("list_*.html")) if FIXTURES.exists() else []
DETAIL_FILES = sorted(FIXTURES.glob("detail_*.html")) if FIXTURES.exists() else []


@unittest.skipUnless(FIXTURES.exists(), "bukken_html/ が無い環境では skip")
class TestListFixtures(unittest.TestCase):
    """一覧6ページ・805行の実ページで不変条件を守る。"""

    def iter_all_rows(self):
        for f in LIST_FILES:
            with self.subTest(fixture=f.name):
                rows = parse_list(BeautifulSoup(f.read_text(), "lxml"))
                self.assertTrue(rows, f"{f.name}: 行が0件")
                yield from rows

    def load_all_rows(self):
        return list(self.iter_all_rows())

    def test_row_count(self):
        rows = self.load_all_rows()
        self.assertGreaterEqual(len(rows), 800)

    def test_rent_in_sane_range(self):
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                self.assertIsNotNone(r["rent_yen"])
                self.assertGreaterEqual(r["rent_yen"], 10000)
                self.assertLessEqual(r["rent_yen"], 1000000)

    def test_admin_not_over_rent(self):
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                if r["admin_yen"] is not None:
                    self.assertLessEqual(r["admin_yen"], r["rent_yen"])

    def test_shikikin_reikin_within_12_months(self):
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                for k in ("shikikin_yen", "reikin_yen"):
                    if r[k] is not None:
                        self.assertLessEqual(r[k], r["rent_yen"] * 12)

    def test_area_in_sane_range(self):
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                self.assertIsNotNone(r["area_m2"])
                self.assertGreaterEqual(r["area_m2"], 5)
                self.assertLessEqual(r["area_m2"], 120)

    def test_url_and_jnc(self):
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                self.assertTrue(r["url"].startswith("https://suumo.jp/chintai/jnc_"))
                self.assertRegex(r["jnc"], r"^\d+$")

    def test_layout_format(self):
        import re
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                self.assertTrue(re.fullmatch(r"(\d[SLDK]{1,4}|ワンルーム)?",
                                             r["layout"]), r["layout"])

    def test_nearest_station(self):
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                self.assertTrue(r["nearest"]["name"], "最寄り駅名が空")
                w = r["nearest"]["walk"]
                if w is not None:
                    self.assertGreaterEqual(w, 1)
                    self.assertLessEqual(w, 120)

    def test_age_and_floor_in_sane_range(self):
        for r in self.load_all_rows():
            with self.subTest(jnc=r["jnc"]):
                if r["age_years"] is not None:
                    self.assertGreaterEqual(r["age_years"], 0)
                    self.assertLessEqual(r["age_years"], 100)
                if r["floor"] is not None:
                    self.assertGreaterEqual(r["floor"], 1)
                    self.assertLessEqual(r["floor"], 60)


@unittest.skipUnless(FIXTURES.exists(), "bukken_html/ が無い環境では skip")
class TestDetailFixtures(unittest.TestCase):
    """詳細20ページの実ページで不変条件を守る。"""

    def load_all(self):
        out = []
        for f in DETAIL_FILES:
            with self.subTest(fixture=f.name):
                out.append((f, parse_detail(BeautifulSoup(
                    f.read_text(), "lxml"))))
        return out

    def test_all_pages_parse(self):
        self.assertEqual(len(self.load_all()), 20)

    def test_rent_in_sane_range(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                self.assertIsNotNone(d["rent_yen"])
                self.assertGreaterEqual(d["rent_yen"], 10000)
                self.assertLessEqual(d["rent_yen"], 1000000)

    def test_admin_not_over_rent(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                if d["admin_yen"] is not None:
                    self.assertLessEqual(d["admin_yen"], d["rent_yen"])

    def test_deposit_like_fees_within_12_months(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                for k in ("deposit_yen", "key_money_yen", "hoshoukin_yen",
                          "shoukyaku_yen"):
                    if d[k] is not None:
                        self.assertLessEqual(d[k], d["rent_yen"] * 12, k)

    def test_renewal_fee_guard(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                if d["renewal_fee_yen"] is not None:
                    self.assertLessEqual(d["renewal_fee_yen"],
                                         d["rent_yen"] * 3)

    def test_agency_within_statutory_cap(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                if d["agency_yen"] is not None:
                    self.assertLessEqual(d["agency_yen"],
                                         d["rent_yen"] * 1.1 + 1000)

    def test_contract_months_sane(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                cm = d["contract_months"]
                if cm is not None:
                    self.assertGreaterEqual(cm, 1)
                    self.assertLessEqual(cm, 360)

    def test_equipment_and_address_present(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                self.assertTrue(d["equipment"], "設備が空")
                self.assertTrue(d["address"], "所在地が空")
                self.assertTrue(d["stations"], "駅が空")

    def test_free_rent_and_lease_flags(self):
        for f, d in self.load_all():
            with self.subTest(fixture=f.name):
                self.assertGreaterEqual(d["free_rent_months"], 0)
                self.assertIn(d["regular_lease"], (0, 1))


@unittest.skipUnless(FIXTURES.exists(), "bukken_html/ が無い環境では skip")
class TestEllipsisPercentRegression(unittest.TestCase):
    """「初回保証料…50％」の実例。

    NFKC で「…」が「...」化した後、旧正規表現 ([\\d.]+) が
    「...50」にマッチして float() が例外を出し、parse_detail が
    該当物件1件を silently 失敗させていた (000109766029)。
    """

    JNC = "000109766029"

    def _detail(self):
        f = FIXTURES / f"detail_{self.JNC}.html"
        return parse_detail(BeautifulSoup(f.read_text(), "lxml"))

    def test_no_crash_and_rate_parsed(self):
        d = self._detail()
        self.assertIsNotNone(d["rent_yen"])
        # 初回保証料…50％ → 賃料の50%が初回保証料として読める
        self.assertEqual(d["guarantee_first_yen"],
                         int(d["rent_yen"] * 50 / 100))


if __name__ == "__main__":
    unittest.main()

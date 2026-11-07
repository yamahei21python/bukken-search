"""SUUMO 掲載終了ページの検知と無効化のテスト。"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup

from db import _ROOT, PROPERTIES_DDL
from detail_scraper import deactivate_listing, is_dead_page


def _dead_soup():
    html = ("<!doctype html><html><body>"
            "<p>ページを表示できませんでした。</p>"
            "<p>お探しの情報は、当サイトへの掲載が終了したため"
            "ご覧いただけません。</p></body></html>")
    return BeautifulSoup(html, "lxml")


def _live_soup():
    html = ("<!doctype html><html><body>"
            '<div class="property_view_note-info">賃料:8万円</div>'
            "</body></html>")
    return BeautifulSoup(html, "lxml")


def _fresh_db():
    con = sqlite3.connect(":memory:")
    con.executescript((Path(_ROOT) / "schema.sql").read_text())
    con.executescript(PROPERTIES_DDL)
    return con


def _seed_listing(con, lid=1):
    con.execute("INSERT INTO buildings(id, norm_address, name, norm_name)"
                " VALUES(1, 'addr', 'bldg', 'bldg')")
    con.execute("INSERT INTO units(id, building_id, area_m2, layout)"
                " VALUES(1, 1, 20.0, '1K')")
    con.execute("INSERT INTO listings(id, unit_id, site, url, active,"
                " last_seen) VALUES(?, 1, 'suumo', ?, 1, datetime('now'))",
                (lid, f"https://suumo.jp/chintai/jnc_{lid:012d}/"))
    con.execute("INSERT INTO costs(listing_id, key_money_yen, deposit_yen,"
                " fetched) VALUES(?, 50000, NULL, 1)", (lid,))


class TestIsDeadPage(unittest.TestCase):
    def test_dead_page_detected(self):
        self.assertTrue(is_dead_page(_dead_soup()))

    def test_live_page_not_dead(self):
        self.assertFalse(is_dead_page(_live_soup()))

    def test_real_dead_page_markers(self):
        # ユーザーが踏んだ実ページの文言を含む
        text = ("ページを表示できませんでした。お探しの情報は、"
                "当サイトへの掲載が終了したためご覧いただけません。")
        self.assertTrue(any(m in text for m in
                            ("掲載が終了したため",
                             "ページを表示できませんでした")))


class TestDeactivateListing(unittest.TestCase):
    def test_deactivates_and_keeps_costs_history(self):
        con = _fresh_db()
        _seed_listing(con, lid=1)
        deactivate_listing(con, 1,
                           "https://suumo.jp/chintai/jnc_000000000001/")
        con.commit()
        active = con.execute(
            "SELECT active FROM listings WHERE id=1").fetchone()[0]
        self.assertEqual(active, 0)
        # costs の取得履歴は保持 (数値は壊さない)
        fetched = con.execute(
            "SELECT fetched FROM costs WHERE listing_id=1").fetchone()[0]
        self.assertEqual(fetched, 1)
        # 来歴が evidence に残る
        ev = con.execute(
            "SELECT method, quote FROM evidence WHERE unit_id=1"
            " ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(ev[0], "dead_page")
        self.assertIn("掲載終了", ev[1])


if __name__ == "__main__":
    unittest.main()

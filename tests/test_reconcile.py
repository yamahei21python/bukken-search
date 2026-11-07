"""models.reconcile_tub のテスト (temp DB 上で全分岐を検証)。"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import _ROOT, PROPERTIES_DDL
from models import reconcile_tub


def _fresh_db():
    con = sqlite3.connect(":memory:")
    con.executescript((Path(_ROOT) / "schema.sql").read_text())
    con.executescript(PROPERTIES_DDL)
    return con


def _seed_building_unit(con, *, uid=1, bid=1, tub="unknown", conf=0.0):
    con.execute("INSERT INTO buildings(id, norm_address, name, norm_name)"
                " VALUES(?, ?, ?, ?)",
                (bid, f"addr{bid}", f"bldg{bid}", f"bldg{bid}"))
    con.execute("INSERT INTO units(id, building_id, area_m2, layout,"
                " tub_status, tub_confidence) VALUES(?,?,20.0,'1K',?,?)",
                (uid, bid, tub, conf))


def _seed_listing_property(con, *, lid, uid, url, has_bathtub,
                           no_ev="", equip=""):
    con.execute("INSERT INTO listings(id, unit_id, site, url, active)"
                " VALUES(?,?, 'suumo', ?, 1)", (lid, uid, url))
    con.execute(
        "INSERT INTO properties(detail_url, has_bathtub,"
        " no_bathtub_evidence, equipment, rent_yen, admin_yen)"
        " VALUES(?,?,?,?,70000,5000)",
        (url, has_bathtub, no_ev, equip))


def _evidence(con, uid):
    return con.execute(
        "SELECT tub_status, method, confidence FROM evidence"
        " WHERE unit_id=?", (uid,)).fetchall()


class TestReconcile(unittest.TestCase):
    def test_orphan_units_deleted(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        _seed_building_unit(con, uid=2, bid=2)
        # unit 1 は listing 無し (孤立) で stations/amenities を持つ
        con.execute("INSERT INTO stations(unit_id,name,line,walk_min)"
                    " VALUES(1,'阿波座','',5)")
        con.execute("INSERT INTO amenities(unit_id,name) VALUES(1,'エアコン')")
        # unit 2 は listing 有り -> 残る
        _seed_listing_property(con, lid=10, uid=2,
                               url="https://suumo.jp/chintai/jnc_1/",
                               has_bathtub=None)
        rep = reconcile_tub(con)
        con.commit()
        self.assertEqual(rep["deleted_units"], 1)
        self.assertIsNone(con.execute(
            "SELECT 1 FROM units WHERE id=1").fetchone())
        self.assertIsNone(con.execute(
            "SELECT 1 FROM stations WHERE unit_id=1").fetchone())
        self.assertIsNone(con.execute(
            "SELECT 1 FROM amenities WHERE unit_id=1").fetchone())
        self.assertIsNotNone(con.execute(
            "SELECT 1 FROM units WHERE id=2").fetchone())

    def test_orphan_building_deleted_when_empty(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        # 孤立 unit だけの建物 -> 建物も削除
        rep = reconcile_tub(con)
        con.commit()
        self.assertEqual(rep["deleted_units"], 1)
        self.assertIsNone(con.execute(
            "SELECT 1 FROM buildings WHERE id=1").fetchone())

    def test_unknown_with_has_bathtub_1_restored_as_likely_tub(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        _seed_listing_property(
            con, lid=10, uid=1, url="https://suumo.jp/chintai/jnc_1/",
            has_bathtub=1, equip="バストイレ別、エアコン")
        rep = reconcile_tub(con)
        con.commit()
        self.assertEqual(rep["restored"], 1)
        self.assertEqual(con.execute(
            "SELECT tub_status, tub_confidence FROM units WHERE id=1"
        ).fetchone(), ("likely_tub", 0.6))
        ev = _evidence(con, 1)
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0][0], ev[0][1]), ("likely_tub", "reconcile"))
        self.assertIn("バストイレ別", con.execute(
            "SELECT quote FROM evidence WHERE unit_id=1").fetchone()[0])

    def test_has_bathtub_0_with_quote_is_confirmed_no_tub(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        _seed_listing_property(
            con, lid=10, uid=1, url="https://suumo.jp/chintai/jnc_1/",
            has_bathtub=0, no_ev="シャワーのみ", equip="シャワー付洗面台")
        rep = reconcile_tub(con)
        con.commit()
        self.assertEqual(rep["restored"], 1)
        self.assertEqual(con.execute(
            "SELECT tub_status, tub_confidence FROM units WHERE id=1"
        ).fetchone(), ("confirmed_no_tub", 0.95))

    def test_has_bathtub_0_without_quote_is_likely_no_tub(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        _seed_listing_property(
            con, lid=10, uid=1, url="https://suumo.jp/chintai/jnc_1/",
            has_bathtub=0, no_ev="", equip="")
        reconcile_tub(con)
        con.commit()
        self.assertEqual(con.execute(
            "SELECT tub_status FROM units WHERE id=1"
        ).fetchone()[0], "likely_no_tub")

    def test_tub_wins_over_conflicting_agents(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        _seed_listing_property(
            con, lid=10, uid=1, url="https://suumo.jp/chintai/jnc_1/",
            has_bathtub=0, no_ev="シャワーのみ")
        _seed_listing_property(
            con, lid=11, uid=1, url="https://suumo.jp/chintai/jnc_2/",
            has_bathtub=1)
        reconcile_tub(con)
        con.commit()
        # 湯船側勝ち (aggregate_tub_status と同じ規約)
        self.assertEqual(con.execute(
            "SELECT tub_status FROM units WHERE id=1"
        ).fetchone()[0], "likely_tub")

    def test_no_info_stays_unknown(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        _seed_listing_property(
            con, lid=10, uid=1, url="https://suumo.jp/chintai/jnc_1/",
            has_bathtub=None)
        rep = reconcile_tub(con)
        con.commit()
        self.assertEqual(rep["still_unknown"], 1)
        self.assertEqual(con.execute(
            "SELECT tub_status FROM units WHERE id=1"
        ).fetchone()[0], "unknown")

    def test_evidence_units_reaggregated(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1, tub="unknown", conf=0.0)
        _seed_listing_property(
            con, lid=10, uid=1, url="https://suumo.jp/chintai/jnc_1/",
            has_bathtub=1)
        # evidence には湯船側の判定が残っているのに unit が unknown の
        # 不整合を再集約で直す
        con.execute("INSERT INTO evidence(unit_id,tub_status,quote,url,"
                    "method,confidence) VALUES(1,'confirmed_tub','浴槽',"
                    "'https://suumo.jp/chintai/jnc_1/','detail_parse',0.95)")
        rep = reconcile_tub(con)
        con.commit()
        self.assertEqual(rep["reaggregated"], 1)
        self.assertEqual(con.execute(
            "SELECT tub_status, tub_confidence FROM units WHERE id=1"
        ).fetchone(), ("confirmed_tub", 0.95))
        # evidence が正しい unit は触れない
        self.assertEqual(con.execute(
            "SELECT tub_status FROM units WHERE id=1"
        ).fetchone()[0], "confirmed_tub")

    def test_idempotent(self):
        con = _fresh_db()
        _seed_building_unit(con, uid=1, bid=1)
        _seed_building_unit(con, uid=2, bid=2)
        _seed_listing_property(
            con, lid=10, uid=2, url="https://suumo.jp/chintai/jnc_2/",
            has_bathtub=1, equip="ユニットバス")
        rep1 = reconcile_tub(con)
        con.commit()
        self.assertEqual(rep1["deleted_units"], 1)
        self.assertEqual(rep1["restored"], 1)
        before = con.execute(
            "SELECT id, tub_status, tub_confidence FROM units"
            " ORDER BY id").fetchall()
        rep2 = reconcile_tub(con)
        con.commit()
        self.assertEqual((rep2["deleted_units"], rep2["restored"],
                          rep2["reaggregated"]), (0, 0, 0))
        after = con.execute(
            "SELECT id, tub_status, tub_confidence FROM units"
            " ORDER BY id").fetchall()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()

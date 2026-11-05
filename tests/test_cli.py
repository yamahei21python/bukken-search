"""CLI スクリプト (rank/filter/check_db) のテスト。

スクリプト本体は import 時に副作用を持たないよう main(argv=None)
へ整理済み。ここでは repo の bukken.db (読み取り専用) を使い、
CLI と同じ経路が動くことと出力の不変条件を検証する。
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_db
import filter as filter_cli
import rank


class TestRankCli(unittest.TestCase):
    def test_main_prints_and_returns_sorted_hits(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hits = rank.main(["--max-total", "100000", "--walk-max", "10"])
        out = buf.getvalue()
        self.assertTrue(out.startswith("hit: "), out[:50])
        self.assertIn("点]", out)
        self.assertGreater(len(hits), 0)
        scores = [h[0] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # 同点は実質月額昇順 (key=(score, -eff) の reverse=True)
        for i in range(1, len(hits)):
            if hits[i][0] == hits[i - 1][0]:
                self.assertGreaterEqual(hits[i][1], hits[i - 1][1])

    def test_collect_hits_respects_walk_max(self):
        a = rank.parse_args(["--max-total", "100000", "--walk-max", "5"])
        hits = rank.collect_hits(a)
        for _sc, _eff, h in hits:
            self.assertIsNotNone(h["walk_min"], "既定では徒歩不明を除外")
            self.assertLessEqual(h["walk_min"], 5)

    def test_collect_hits_shower_only(self):
        a = rank.parse_args(["--shower-only", "--allow-unknown-walk"])
        hits = rank.collect_hits(a)
        for _sc, _eff, h in hits:
            self.assertTrue(h["shower"])
            self.assertEqual(h["tub_status"], "unknown")

    def test_module_import_has_no_side_effect(self):
        # import 時に argparse が走って SystemExit にならない
        self.assertTrue(callable(rank.main))
        self.assertIn("SELECT", rank.QUERY)


class TestFilterCli(unittest.TestCase):
    def test_main_runs(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rows = filter_cli.main(["--max-rent", "70000", "--no-bathtub"])
        out = buf.getvalue()
        self.assertTrue(out.startswith("hit: "), out[:50])
        self.assertEqual(len(rows), int(out.splitlines()[0].split()[1]))

    def test_build_query_order_by_is_whitelisted(self):
        for sort in filter_cli.SORTMAP:
            a = filter_cli.parse_args(["--sort", sort])
            q, _params = filter_cli.build_query(a)
            self.assertIn(f"ORDER BY {filter_cli.SORTMAP[sort]}", q)

    def test_build_query_uses_placeholders(self):
        a = filter_cli.parse_args(["--max-rent", "80000", "--no-bathtub",
                                   "--walk-max", "7", "--max-age", "20",
                                   "--min-area", "18"])
        q, params = filter_cli.build_query(a)
        self.assertIn("has_bathtub=0", q)
        self.assertIn("walk_min<=?", q)
        self.assertIn("age_years<=?", q)
        self.assertIn("area_m2>=?", q)
        self.assertEqual(params, [80000, 7, 20, 18])
        # 値が SQL に埋め込まれていないこと (数値リテラル直書きの混入禁止)
        for p in params:
            self.assertNotIn(str(p), q.replace("<=? ", "").replace(">=?", ""))


class TestCheckDbCli(unittest.TestCase):
    def test_main_prints_table_counts(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_db.main()
        out = buf.getvalue()
        self.assertIn("--- table counts ---", out)
        self.assertIn("buildings:", out)
        self.assertIn("--- costs ---", out)


if __name__ == "__main__":
    unittest.main()

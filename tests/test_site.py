"""build_site (静的サイト生成) のスモークテスト。

実際の bukken.db から tmp ディレクトリへ生成し、
出力の構造と規模を検証する。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import build_site


class TestBuildSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        n = build_site.build(Path(cls.tmp.name))
        cls.n = n

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_output_files(self):
        d = Path(self.tmp.name)
        self.assertTrue((d / "index.html").exists())
        self.assertTrue((d / "data.json").exists())

    def test_data_json_structure(self):
        d = json.loads((Path(self.tmp.name) / "data.json").read_text())
        self.assertIn("generated_at", d)
        self.assertGreater(d["meta"]["rows"], 1000)
        self.assertIsNotNone(d["meta"]["r2"])
        self.assertEqual(len(d["rows"]), d["meta"]["rows"])
        row = d["rows"][0]
        for key in ("n", "st", "w", "tot", "fair", "disc", "url"):
            self.assertIn(key, row)
        # プライバシー: 湯船判定は検索戦略が推測できるため
        # 公開データには絶対に含めない (UI でも非表示)
        self.assertNotIn("tub", row)
        self.assertNotIn("has_bathtub", row)
        # 割安度順でソート済み (降順)
        discs = [r["disc"] or 0 for r in d["rows"]]
        self.assertEqual(discs, sorted(discs, reverse=True))

    def test_index_html_contains_ui(self):
        html = (Path(self.tmp.name) / "index.html").read_text()
        self.assertIn("阿波座 賃貸選別", html)
        self.assertIn("data.json", html)
        self.assertIn("leaflet", html.lower())
        # プライバシー: 湯船関連 UI は公開サイトに載せない
        for ng in ("湯船", "湯なし", "tub"):
            self.assertNotIn(ng, html)

    def test_output_size_reasonable(self):
        d = Path(self.tmp.name) / "data.json"
        self.assertLess(d.stat().st_size, 20 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()

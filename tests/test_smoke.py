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
from parse_suumo import (money_pair, parse_detail, to_yen, nfkc, _find_yen,
                         _guarantee_first_yen, _guarantee_rate,
                         _guard_rent_multiple, _labeled_yen, _list_row)


class TestMoney(unittest.TestCase):
    def test_to_yen(self):
        self.assertEqual(to_yen("8.55万円"), 85500)
        self.assertEqual(to_yen("2.675万円"), 26750)
        self.assertIsNone(to_yen("-"))

    def test_to_yen_decimal_yen_no_crash(self):
        # 小数円額（"2095.5円"）で ValueError を投げない
        self.assertEqual(to_yen("2095.5円"), 2096)
        self.assertEqual(to_yen("2095円"), 2095)

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

    def test_shower_room_alone_is_not_no_tub(self):
        # シャワールームは浴槽と共存しうる弱い信号。単独では
        # 湯船なし側に倒さない（旧仕様は likely_no_tub にしていた）
        d = {"equipment": "シャワールーム", "note": "", "full": ""}
        self.assertEqual(judge_tub(d)[0], "unknown")

    def test_shower_room_with_separate_bath_is_tub(self):
        # バストイレ別・浴室乾燥（浴槽の実在証拠）が共存すれば湯船側。
        # 実ページ検証で旧判定が 5件中5件誤っていたパターン
        d = {"equipment": "シャワールーム、バストイレ別、浴室乾燥機",
             "note": "", "full": ""}
        self.assertEqual(judge_tub(d)[0], "likely_tub")

    def test_explicit_no_tub_phrase(self):
        d = {"equipment": "シャワーのみ、エアコン", "note": "", "full": ""}
        self.assertEqual(judge_tub(d)[0], "confirmed_no_tub")


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

    def _with_contract(self, contract, rent_line="7万円\n管理費: 5000円\n"):
        return ("<html><body><div class='property_view_note-info'>\n"
                + rent_line + "</div>"
                "<table class='table_gaiyou'><tr><th>契約期間</th>"
                f"<td>{contract}</td></tr></table></body></html>")

    def test_contract_not_calendar_year(self):
        # 定期借家の期限（西暦）を契約期間と誤認しない
        d = parse_detail(BeautifulSoup(
            self._with_contract("2028年3月末まで"), "lxml"))
        self.assertIsNone(d["contract_months"])

    def test_renewal_ratio_and_months(self):
        # 比率表記の更新料（新賃料の1ヶ月分）を家賃から換算する
        d = parse_detail(BeautifulSoup(
            self._with_contract("2年 更新料: 新賃料の1ヶ月分"), "lxml"))
        self.assertEqual(d["contract_months"], 24)
        self.assertEqual(d["renewal_fee_yen"], 70000)

    def test_renewal_from_other_plain_label(self):
        # ほか初期費用の「更新料」表記（「更新手数料」以外）も拾う
        d = parse_detail(BeautifulSoup(
            self._with_other("更新料 15000円"), "lxml"))
        self.assertEqual(d["renewal_fee_yen"], 15000)

    def test_renewal_from_other_ratio(self):
        d = parse_detail(BeautifulSoup(
            self._with_other("更新料 新賃料1.00ヶ月分"), "lxml"))
        self.assertEqual(d["renewal_fee_yen"], 70500)

    def test_renewal_not_guarantee_renew(self):
        # 保証会社の更新料は契約更新料に混ぜない
        d = parse_detail(BeautifulSoup(
            self._with_other("保証会社更新料 1万円"), "lxml"))
        self.assertIsNone(d["renewal_fee_yen"])

    def test_support_monthly_split(self):
        # 月額型サポートは support_monthly_yen へ（一時金と分離）
        d = parse_detail(BeautifulSoup(
            self._with_other("安心サポート 月額880円"), "lxml"))
        self.assertIsNone(d["support_yen"])
        self.assertEqual(d["support_monthly_yen"], 880)

    def test_support_one_time(self):
        d = parse_detail(BeautifulSoup(
            self._with_other("ライフサポートプラス4.62万円"), "lxml"))
        self.assertEqual(d["support_yen"], 46200)
        self.assertIsNone(d["support_monthly_yen"])

    def test_support_mixed(self):
        d = parse_detail(BeautifulSoup(
            self._with_other("安心サポート 月額880円 除菌消臭1.1万円"),
            "lxml"))
        self.assertEqual(d["support_monthly_yen"], 880)
        self.assertEqual(d["support_yen"], 11000)

    def test_cleaning_not_aircon(self):
        # エアコンクリーニング代を室内清掃費と誤認しない（順序不問）
        d = parse_detail(BeautifulSoup(
            self._with_other("退去時エアコンクリーニング代1.1万円"
                             " ハウスクリーニング代3.3万円"), "lxml"))
        self.assertEqual(d["cleaning_yen"], 33000)
        d = parse_detail(BeautifulSoup(
            self._with_other("エアコンクリーニング代1.32万円"), "lxml"))
        self.assertIsNone(d["cleaning_yen"])

    def test_free_rent_agency_pr_ignored(self):
        # 仲介会社の PR 文（ページ全文にのみ出現）では発火しない
        html = ("<html><body><div>フリーレント付き物件の特集も充実"
                "</div><div class='property_view_note-info'>\n"
                "7万円\n管理費: 5000円\n</div></body></html>")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertEqual(d["free_rent_months"], 0)

    def _with_equipment(self, items):
        lis = "".join(f"<li>{x}</li>" for x in items)
        return ("<html><body><div class='property_view_note-info'>\n"
                "7万円\n管理費: 5000円\n</div>"
                f"<ul class='inline_list'>{lis}</ul></body></html>")

    def test_free_rent_months_kept(self):
        # 「フリーレント2ヶ月」は 2 として保持する（0/1二値化しない）
        d = parse_detail(BeautifulSoup(self._with_equipment(
            ["エアコン", "オートロック", "フローリング",
             "フリーレント2ヶ月"]), "lxml"))
        self.assertEqual(d["free_rent_months"], 2.0)

    def test_free_rent_tag_only_is_one(self):
        d = parse_detail(BeautifulSoup(self._with_equipment(
            ["エアコン", "オートロック", "フローリング",
             "フリーレント"]), "lxml"))
        self.assertEqual(d["free_rent_months"], 1.0)

    def test_contract_absent_is_none(self):
        # 契約期間が読めない場合は None（24で埋めない）
        html = ("<html><body><div class='property_view_note-info'>\n"
                "7万円\n管理費: 5000円\n</div></body></html>")
        d = parse_detail(BeautifulSoup(html, "lxml"))
        self.assertIsNone(d["contract_months"])

    def _with_acc(self, rows_html):
        return ("<html><body><div class='property_view_note-info'>\n"
                "7万円\n管理費: 5000円\n</div>"
                "<table class='property_view_table'>"
                f"{rows_html}</table></body></html>")

    def test_direction_placeholder_and_area(self):
        # 向き「-」はプレースホルダとして NULL に倒し、専有面積は拾う
        d = parse_detail(BeautifulSoup(self._with_acc(
            "<tr><th>所在地</th><td>大阪市西区</td>"
            "<th>駅徒歩</th><td>地下鉄中央線/阿波座駅 歩5分</td></tr>"
            "<tr><th>間取り</th><td>1K</td>"
            "<th>専有面積</th><td>23.2m2</td></tr>"
            "<tr><th>向き</th><td>-</td><th>階</th><td>3階</td></tr>"),
            "lxml"))
        self.assertIsNone(d["direction"])
        self.assertEqual(d["area_m2"], 23.2)
        self.assertEqual([s["name"] for s in d["stations"]], ["阿波座"])

    def test_direction_real_value(self):
        d = parse_detail(BeautifulSoup(self._with_acc(
            "<tr><th>向き</th><td>南</td><th>階</th><td>3階</td></tr>"),
            "lxml"))
        self.assertEqual(d["direction"], "南")


class TestStations(unittest.TestCase):
    def test_dedup_and_cap(self):
        from parse_suumo import parse_stations
        st = parse_stations(
            "地下鉄中央線/阿波座駅 歩5分 地下鉄千日前線/阿波座駅 歩3分"
            " 地下鉄長堀鶴見緑地線/西長堀駅 歩7分"
            " 地下鉄四つ橋線/本町駅 歩9分 地下鉄御堂筋線/本町駅 歩8分")
        self.assertEqual([s["name"] for s in st],
                         ["阿波座", "西長堀", "本町"])

    def test_fino_stations(self):
        # 旭区中宮の物件: 物件情報ブロックの3駅だけが正解で、
        # 仲介店舗の駅（四ツ橋・心斎橋・西大橋）を拾わない
        fino = (Path(__file__).resolve().parents[2]
                / "fino" / "detail.html")
        if not fino.exists():
            self.skipTest("fino corpus not available")
        d = parse_detail(BeautifulSoup(fino.read_text(), "lxml"))
        self.assertEqual(
            [(s["name"], s["walk"]) for s in d["stations"]],
            [("千林大宮", 11), ("城北公園通", 14), ("森小路", 18)])


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

    def test_shikikin_none_is_null(self):
        # 敷金・礼金が未取得のとき、文字列 'None' でなく NULL が入る
        import db as db_mod
        import scraper
        row = {"name": "テスト2", "address": "大阪市西区立売堀3",
               "age_years": 10, "floors": 5, "structure": "鉄筋系",
               "area_m2": 25.0, "layout": "1K", "floor": 3,
               "direction": None, "rent_yen": 80000, "admin_yen": 5000,
               "shikikin_yen": None, "reikin_yen": None,
               "url": "https://suumo.jp/chintai/jnc_000999999998/",
               "stations": [{"line": "地下鉄中央線", "name": "阿波座",
                             "walk": 5}],
               "nearest": {"line": "地下鉄中央線", "name": "阿波座",
                           "walk": 5}}
        scraper.save([row])
        con = db_mod.connect_db()
        shiki, rei = con.execute(
            "SELECT shikikin, reikin FROM listings").fetchone()
        con.close()
        self.assertIsNone(shiki)
        self.assertIsNone(rei)


class TestRound6Db(unittest.TestCase):
    """第6ラウンド修正のDB挙動: 駅の置き換え、浴槽判定の unit 集約、
    契約期間 NULL、サポート月額の保存、properties の方向保護。"""

    def setUp(self):
        import db as db_mod
        self.tmp = Path(__file__).parent / "_tmp_test6.db"
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

    def _row(self, url, **kw):
        row = {"name": "テスト", "address": "大阪市西区立売堀3",
               "age_years": 10, "floors": 5, "structure": None,
               "area_m2": 25.0, "layout": "1K", "floor": 3,
               "direction": None, "rent_yen": 80000, "admin_yen": 5000,
               "shikikin_yen": 0, "reikin_yen": 80000, "url": url,
               "stations": [{"line": "地下鉄中央線", "name": "阿波座",
                             "walk": 5}],
               "nearest": {"line": "地下鉄中央線", "name": "阿波座",
                           "walk": 5}}
        row.update(kw)
        return row

    def _detail(self, **kw):
        d = {"rent_yen": 80000, "admin_yen": 5000, "deposit_yen": 0,
             "key_money_yen": 80000, "hoshoukin_yen": None,
             "shoukyaku_yen": None, "insurance_yen": None,
             "key_exchange_yen": None, "cleaning_yen": None,
             "support_yen": None, "support_monthly_yen": None,
             "water_fixed_yen": None,
             "guarantee_first_yen": None, "guarantee_renew_yen": None,
             "agency_yen": None, "renewal_fee_yen": None,
             "contract_months": None, "free_rent_months": 0,
             "regular_lease": 1, "direction": None, "structure": None,
             "floors": 5, "equipment": "", "note": "", "stations": [],
             "area_m2": None}
        d.update(kw)
        return d

    def _lid_uid(self, con, url):
        return con.execute(
            "SELECT id, unit_id FROM listings WHERE url=?",
            (url,)).fetchone()

    def test_detail_stations_replace_and_list_keeps(self):
        import db as db_mod
        import scraper
        from detail_scraper import apply_detail
        url = "https://suumo.jp/chintai/jnc_000999999901/"
        scraper.save([self._row(url)])
        con = db_mod.connect_db()
        lid, uid = self._lid_uid(con, url)
        apply_detail(con, lid, uid, url, self._detail(stations=[
            {"line": "地下鉄中央線", "name": "阿波座", "walk": 4},
            {"line": "地下鉄四つ橋線", "name": "本町", "walk": 9}]))
        con.commit()
        got = {(n, w) for n, w in con.execute(
            "SELECT name, walk_min FROM stations WHERE unit_id=?", (uid,))}
        # 一覧値（阿波座5分）は詳細値で置き換わっている
        self.assertEqual(got, {("阿波座", 4), ("本町", 9)})
        con.close()
        # 翌日の一覧再保存でも詳細由来の駅は上書きされない
        scraper.save([self._row(url)])
        con = db_mod.connect_db()
        got = {(n, w) for n, w in con.execute(
            "SELECT name, walk_min FROM stations WHERE unit_id=?", (uid,))}
        con.close()
        self.assertEqual(got, {("阿波座", 4), ("本町", 9)})

    def test_tub_aggregation_tub_wins(self):
        import db as db_mod
        import scraper
        from detail_scraper import apply_detail
        url_a = "https://suumo.jp/chintai/jnc_000999999902/"
        url_b = "https://suumo.jp/chintai/jnc_000999999903/"
        scraper.save([self._row(url_a), self._row(url_b)])
        con = db_mod.connect_db()
        la, ua = self._lid_uid(con, url_a)
        lb, ub = self._lid_uid(con, url_b)
        self.assertEqual(ua, ub)  # 同じ部屋の複数掲載
        apply_detail(con, lb, ub, url_b,
                     self._detail(equipment="シャワーのみ"))
        con.commit()
        st = con.execute("SELECT tub_status FROM units WHERE id=?",
                         (ua,)).fetchone()[0]
        self.assertEqual(st, "confirmed_no_tub")
        apply_detail(con, la, ua, url_a,
                     self._detail(equipment="バストイレ別、エアコン"))
        con.commit()
        st = con.execute("SELECT tub_status FROM units WHERE id=?",
                         (ua,)).fetchone()[0]
        # 兄弟 listing に浴槽証拠があれば unit は湯船側に倒れる
        self.assertEqual(st, "likely_tub")
        hbs = {r[0] for r in con.execute(
            "SELECT has_bathtub FROM properties WHERE detail_url IN (?,?)",
            (url_a, url_b))}
        self.assertEqual(hbs, {1})
        # 湯船なし側の詳細を再適用しても last-writer-wins で戻らない
        apply_detail(con, lb, ub, url_b,
                     self._detail(equipment="シャワーのみ"))
        con.commit()
        st = con.execute("SELECT tub_status FROM units WHERE id=?",
                         (ua,)).fetchone()[0]
        con.close()
        self.assertEqual(st, "likely_tub")

    def test_costs_contract_null_and_support_monthly(self):
        import db as db_mod
        import scraper
        from detail_scraper import apply_detail
        url = "https://suumo.jp/chintai/jnc_000999999904/"
        scraper.save([self._row(url)])
        con = db_mod.connect_db()
        lid, uid = self._lid_uid(con, url)
        # 未取得行の contract_months は 24 で埋めず NULL
        cm = con.execute("SELECT contract_months FROM costs"
                         " WHERE listing_id=?", (lid,)).fetchone()[0]
        self.assertIsNone(cm)
        apply_detail(con, lid, uid, url, self._detail(
            support_monthly_yen=880, equipment="エアコン"))
        con.commit()
        cm, sm = con.execute(
            "SELECT contract_months, support_monthly_yen FROM costs"
            " WHERE listing_id=?", (lid,)).fetchone()
        con.close()
        # 契約期間が読めない詳細でも NULL のまま（消費側が24で按分）
        self.assertIsNone(cm)
        self.assertEqual(sm, 880)

    def test_properties_direction_survives_list_resave(self):
        import db as db_mod
        import scraper
        from detail_scraper import apply_detail
        url = "https://suumo.jp/chintai/jnc_000999999905/"
        scraper.save([self._row(url)])
        con = db_mod.connect_db()
        lid, uid = self._lid_uid(con, url)
        apply_detail(con, lid, uid, url,
                     self._detail(direction="南", equipment="エアコン"))
        con.commit()
        con.close()
        scraper.save([self._row(url)])  # 一覧再保存（direction は来ない）
        con = db_mod.connect_db()
        direc = con.execute("SELECT direction FROM properties"
                            " WHERE detail_url=?", (url,)).fetchone()[0]
        con.close()
        self.assertEqual(direc, "南")


class TestTimestampsUtc(unittest.TestCase):
    """DB時刻は UTC 統一（'localtime' を使うと実行環境でずれる）。"""

    def test_no_localtime_in_sql(self):
        root = Path(__file__).parent.parent
        offenders = []
        for f in list(root.glob("*.py")) + list(root.glob("*.sql")):
            if "localtime" in f.read_text(encoding="utf-8"):
                offenders.append(f.name)
        self.assertEqual(offenders, [])


class TestAuditFixes20261026(unittest.TestCase):
    """2026-10-26 監査所見 F1〜F4 の回帰防止。"""

    def test_thousands_separators(self):
        # F4: 読点・空白の桁区切りを全経路で読めること
        self.assertEqual(to_yen("10、000円"), 10000)
        self.assertEqual(to_yen("10 000円"), 10000)
        self.assertEqual(money_pair("10、000円 66000円"), (10000, 66000))
        self.assertEqual(_find_yen("更新料10、000円/年", r"更新料"), 10000)

    def test_guard_rent_multiple(self):
        # F2: 家賃12ヶ月分超は誤記として落とす（詳細・一覧共通）
        self.assertIsNone(_guard_rent_multiple(4356000000, 66000))
        self.assertEqual(_guard_rent_multiple(200000, 85000), 200000)
        self.assertIsNone(_guard_rent_multiple(None, 66000))
        self.assertEqual(_guard_rent_multiple(100000, None), 100000)

    def test_list_row_giant_shikikin(self):
        # F2: 一覧カセットの「敷金: 435600万円」が素通ししないこと
        row = BeautifulSoup(
            "<tr><td><a href='/chintai/jnc_000000000001/'>x</a></td>"
            "<td></td><td>7階</td><td>6.6万円 7000円</td>"
            "<td>435600万円 66000円</td><td>1K 25.5m2</td></tr>",
            "html.parser").find("tr")
        base = {"name": "x", "address": "y", "age_years": 10, "floors": 5,
                "stations": [], "nearest": {"name": None, "walk": None}}
        r = _list_row(row, base)
        self.assertEqual(r["rent_yen"], 66000)
        self.assertIsNone(r["shikikin_yen"])
        self.assertEqual(r["reikin_yen"], 66000)

    def test_guarantee_first_fixed_amount(self):
        # F3: 固定額の明記が月額率の誤認より優先されること
        self.assertEqual(
            _guarantee_first_yen(
                "保証会社利用必 初回保証料:10000円、以降は月額賃料の1%/毎月",
                63000),
            10000)

    def test_guarantee_first_rates(self):
        # F3: 率のみの場合は従来どおり換算されること
        self.assertEqual(
            _guarantee_first_yen("日本セーフティー利用必 総賃料の50%", 69000),
            34500)
        self.assertEqual(
            _guarantee_first_yen(
                "初回保証委託料:連帯保証人なし30%(※下限15,000円)", 90000),
            27000)

    def test_guarantee_rate_ignores_monthly(self):
        self.assertIsNone(_guarantee_rate("以降は月額賃料の1%/毎月"))

    def test_guarantee_renew_tiered(self):
        # F3: 段階制は閾値でなく賃料が属する段の金額を読むこと
        text = "更新料:15万円未満10,000円/年 15万円以上14,000円/年"
        self.assertEqual(_labeled_yen(text, r"更新料", 90000), 10000)
        self.assertEqual(_labeled_yen(text, r"更新料", 160000), 14000)

    def test_guarantee_renew_known_good(self):
        # F3: 既知の正常値が壊れないこと（比率表記・高額の正当な更新料）
        self.assertEqual(
            _labeled_yen("更新料 新賃料1.00ヶ月分", r"更新料", 82000), 82000)
        self.assertEqual(
            _labeled_yen("更新料 114000円", r"更新料", 90000), 114000)

    def test_guarantee_renew_annual_label(self):
        # F3: 「1年更新:10 000円」型（空白区切り含む）
        self.assertEqual(
            _labeled_yen("1年更新:10 000円 その他のプラン有", r"年更新", 81000),
            10000)

    def test_nfkc_preserves_general_text(self):
        # F4: 桁区切り以外の読点・空白は壊さないこと
        self.assertEqual(nfkc("浴室、洗面所"), "浴室、洗面所")
        self.assertEqual(nfkc("2026 10月"), "2026 10月")
        self.assertEqual(nfkc("06 6454"), "06 6454")
        self.assertEqual(nfkc("10、000円"), "10000円")

    def test_guarantee_renew_tiered_truncated(self):
        # F3: 上段の金額が末尾切断された実文面型。下段は読め、上段は
        # 閾値や切断途中の数字を返さず None になること
        text = "更新料:15万円未満10,000円/年 15万円以上14,00"
        self.assertEqual(_labeled_yen(text, r"更新料", 90000), 10000)
        self.assertIsNone(_labeled_yen(text, r"更新料", 160000))

    def test_guarantee_renew_tiered_below_only(self):
        # F3: 下段だけの段階制。属さない側は None
        text = "更新料:15万円未満10,000円/年"
        self.assertEqual(_labeled_yen(text, r"更新料", 90000), 10000)
        self.assertIsNone(_labeled_yen(text, r"更新料", 160000))

    def test_guarantee_first_fixed_beats_rate(self):
        # F3: 固定額が率より先に来なくても固定額が優先されること
        # （rate は固定額が取れない場合のみ実行される）
        self.assertEqual(
            _guarantee_first_yen("総賃料の50% 初回保証料:20000円", 69000),
            20000)


class TestApplyDetailNullCleanup(unittest.TestCase):
    """F2: 詳細適用時に異常値と 'None' 文字列が全層で NULL 化されること。"""

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

    def test_abnormal_and_none_strings_cleaned(self):
        import db as db_mod
        import scraper
        from detail_scraper import apply_detail
        row = {"name": "テスト3", "address": "大阪市西区立売堀3",
               "age_years": 10, "floors": 5, "structure": "鉄筋系",
               "area_m2": 25.0, "layout": "1K", "floor": 3,
               "direction": None, "rent_yen": 80000, "admin_yen": 5000,
               "shikikin_yen": 0, "reikin_yen": 80000,
               "url": "https://suumo.jp/chintai/jnc_000999999997/",
               "stations": [{"line": "地下鉄中央線", "name": "阿波座",
                             "walk": 5}],
               "nearest": {"line": "地下鉄中央線", "name": "阿波座",
                           "walk": 5}}
        scraper.save([row])
        con = db_mod.connect_db()
        lid, uid = con.execute("SELECT id, unit_id FROM listings").fetchone()
        # 過去の汚染を再現: properties に 'None' 文字列と異常値、
        # listings に 'None' 文字列を植える
        con.execute("UPDATE properties SET shikikin_yen='None',"
                    " reikin_yen=4356000000")
        con.execute("UPDATE listings SET shikikin='None' WHERE id=?", (lid,))
        con.commit()
        d = {"rent_yen": 80000, "admin_yen": 5000, "deposit_yen": None,
             "key_money_yen": None, "hoshoukin_yen": None,
             "shoukyaku_yen": None, "insurance_yen": None,
             "key_exchange_yen": None, "cleaning_yen": None,
             "support_yen": None, "support_monthly_yen": None,
             "water_fixed_yen": None,
             "guarantee_first_yen": None, "guarantee_renew_yen": None,
             "agency_yen": None, "renewal_fee_yen": None,
             "contract_months": 24, "free_rent_months": 0,
             "regular_lease": 1, "direction": "南", "structure": "鉄筋系",
             "floors": 5, "building_age_years": 10,
             "equipment": "シャワールーム", "note": "",
             "stations": [{"line": "地下鉄中央線", "name": "阿波座",
                           "walk": 4}]}
        apply_detail(con, lid, uid, row["url"], d)
        con.commit()
        shiki, rei, t_shiki = con.execute(
            "SELECT shikikin_yen, reikin_yen, typeof(shikikin_yen)"
            " FROM properties").fetchone()
        l_shiki = con.execute(
            "SELECT shikikin FROM listings WHERE id=?", (lid,)).fetchone()[0]
        c_dep = con.execute(
            "SELECT typeof(deposit_yen) FROM costs WHERE listing_id=?",
            (lid,)).fetchone()[0]
        con.close()
        self.assertIsNone(shiki)
        self.assertIsNone(rei)
        self.assertEqual(t_shiki, "null")
        self.assertIsNone(l_shiki)
        self.assertEqual(c_dep, "null")


if __name__ == "__main__":
    unittest.main()

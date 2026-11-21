import unittest
from math import isfinite

from tea_catalog import CATALOG, DIRECTORY, exact_match, find_drinks, menu_entry
from test_app import open_app


class TeaDirectoryTests(unittest.TestCase):
    def test_catalogue_counts_distinct_drinks_and_keeps_menu_only_out_of_recipes(self):
        products = find_drinks()
        self.assertEqual(len(products), len(set(products)))
        self.assertEqual(set(products), set(DIRECTORY))
        self.assertGreaterEqual(len(find_drinks("霸王茶姬", evidence_only=True)), 150)
        self.assertEqual(find_drinks("1點點", "A2牛乳"), find_drinks("一点点", "A2牛乳"))
        self.assertIn(("一点点", "A2牛乳红茶"), find_drinks("1点点", term="A2"))
        self.assertTrue(menu_entry("１点点", "A2牛乳红茶")["menus"])
        self.assertFalse(menu_entry("一点点", "A2牛乳红茶")["evidence_regions"])
        self.assertFalse(find_drinks("春水堂", region="中国大陆", evidence_only=True))
        self.assertTrue(find_drinks("春水堂", region="中国台湾", evidence_only=True))
        self.assertEqual(exact_match("一点点", "A2牛乳红茶"), [])
        self.assertFalse(find_drinks("一点点", term="A2", evidence_only=True))
        self.assertIsNone(menu_entry("另一品牌", "A2牛乳红茶"))

    def test_verified_metrics_belong_to_specific_source_and_market(self):
        rows = exact_match("CHAGEE", "金芒杨枝甘露")
        cup = next(row for row in rows if (row["size"], row["sugar"], row["temp"])
                   == ("中杯", "不另外加糖", "标准冰"))
        self.assertEqual((cup["region"], cup["kcal"], cup["grade"]), ("中国大陆", 196, "C"))
        self.assertIsNone(cup.get("total_sugar"))
        for row in CATALOG:
            for key in ("kcal", "total_sugar", "volume"):
                val = row.get(key)
                if val is not None:
                    self.assertTrue(isfinite(val) and val >= 0, (row["name"], key, val))
            self.assertTrue(row["source"].startswith("https://"))
            self.assertTrue(row["region"] and row["scope"])

    def test_brand_category_and_evidence_filters_reach_correct_result(self):
        app = open_app("现制奶茶")
        app.selectbox(key="tea.catalog.brand").set_value("一点点").run()
        app.selectbox(key="tea.catalog.category").set_value("A2牛乳").run()
        picker = app.selectbox(key="tea.catalog.pick")
        self.assertTrue(all("仅菜单" in label for label in picker.options))
        picker.set_value(("一点点", "A2牛乳红茶")).run()
        self.assertIn("一点点 · A2牛乳红茶", [head.value for head in app.subheader])
        self.assertFalse(any("当前规格营养摘要" in node.proto.body for node in app.get("html")))
        app.selectbox(key="tea.catalog.brand").set_value("霸王茶姬").run()
        app.checkbox(key="tea.catalog.evidence").check().run()
        self.assertEqual(app.selectbox(key="tea.catalog.category").value, "")
        self.assertTrue(all("霸王茶姬" in label for label in app.selectbox(key="tea.catalog.pick").options))
        app.selectbox(key="tea.catalog.pick").set_value(("霸王茶姬", "金芒杨枝甘露")).run()
        self.assertTrue(any("196 <small>kcal" in node.proto.body for node in app.get("html")))
        self.assertFalse(app.exception)

import unittest

from tea_catalog import BRAND_LOOKUP, CATALOG, exact_match, grade_drink


class GradeTests(unittest.TestCase):
    def test_standard_table_one_boundaries(self):
        cases = [
            ((0.5, 0.75, 0.3, False), "A"),
            ((0.501, 0, 0, False), "B"),
            ((5, 0, 0, False), "B"),
            ((5.001, 0, 0, False), "C"),
            ((11.5, 0, 0, False), "C"),
            ((11.501, 0, 0, False), "D"),
            ((0, 0.751, 0, False), "B"),
            ((0, 2.5, 0, False), "B"),
            ((0, 2.501, 0, False), "D"),
            ((0, 0, 0.301, False), "C"),
            ((0, 0, 0, True), "B"),
            ((5.5, 2.51, 0.4, True), "D"),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                grade, explanation = grade_drink(*values)
                self.assertEqual(grade, expected)
                self.assertIn("045", explanation)

    def test_incomplete_or_invalid_values_are_not_graded(self):
        for values in [(None, 0, 0, False), (1, None, 0, True), (0, 0, None, False),
                       (0, 0, 0, None), (True, 0, 0, False), ("3", 0, 0, False),
                       (0, float("nan"), 0, False), (0, 0, -1, False), (0, 0, 0, 1),
                       (float("inf"), 0, 0, False)]:
            with self.subTest(values=values):
                self.assertIsNone(grade_drink(*values)[0])


class CatalogTests(unittest.TestCase):
    def test_servings_keep_regions_and_missing_values(self):
        variants = exact_match(" 清心福全 ", " 珍珠奶茶")
        self.assertEqual({r["size"]: r["kcal"] for r in variants}, {"中杯": 475, "大杯": 720})
        self.assertTrue(all(r["region"] == "中国台湾" and r["grade"] is None for r in variants))
        self.assertEqual(exact_match("另一个品牌", "珍珠奶茶"), [])
        self.assertEqual(exact_match("清心福全", "珍珠"), [])
        variants[0]["toppings"].append("椰果")
        self.assertFalse(exact_match("清心福全", "珍珠奶茶")[0]["toppings"])

    def test_published_grade_is_scoped_to_observed_recipe(self):
        variants = exact_match("霸王茶姬", "云中绿")
        self.assertTrue(any((r["size"], r["sugar"], r["temp"], r["grade"])
                            == ("中杯", "不另外加糖", "冷饮", "A") for r in variants))
        for row in CATALOG:
            self.assertIn(row["brand"], BRAND_LOOKUP)
            self.assertTrue(row["source"].startswith("https://"))
            self.assertTrue(row["scope"])
            if row["grade"]:
                self.assertIn(row["grade"], "ABCD")
                self.assertTrue(row["grade_source"].startswith("https://"))

    def test_maximums_and_extra_toppings_are_explicit(self):
        self.assertTrue(all(r["value_type"] == "最高标示值" for r in exact_match("思茶", "醇厚红茶拿铁")))
        oolong = exact_match("清心福全", "乌龙奶茶")[0]
        self.assertEqual(oolong["toppings"], [])
        self.assertIn("珍珠", oolong["topping_options"])
        self.assertEqual(oolong["toppings_source"], oolong["source"])


if __name__ == "__main__":
    unittest.main()

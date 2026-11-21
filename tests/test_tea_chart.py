import unittest

from tea_catalog import exact_match
from tea_chart import sweetness_variants
from test_app import open_app


class TeaChartTests(unittest.TestCase):
    def setUp(self):
        self.records = exact_match("霸王茶姬", "伯牙绝弦")
        self.first = next(r for r in self.records if r.get("chagee_recipe") and r["sugar"] == "不另外加糖")

    def test_compares_only_documented_recipes_differing_in_sweetness(self):
        unrelated = [dict(self.first, sugar="其他甜度", **{field: value}) for field, value in (
            ("region", "其他地区"), ("source", "其他来源"), ("scope", "其他配方范围"),
            ("kind", "奶盖茶"), ("temp", "去冰"), ("size", "大杯"), ("toppings", ["珍珠"]),
            ("value_type", "最高标示值"), ("user_record", True),
            ("chagee_recipe", {**self.first["chagee_recipe"], "milk": "其他奶基底"}),
        )]
        group = sweetness_variants(self.first, self.records + unrelated)
        self.assertEqual([(r["sugar"], r["kcal"], r["grade"]) for r in group], [
            ("不另外加糖", 130, "B"), ("少糖", 207, "B"), ("标准糖", 211, "C"),
        ])
        self.assertFalse(sweetness_variants(dict(self.first, kcal=0), self.records))
        self.assertFalse(sweetness_variants(dict(self.first, personal_fields=["能量"]), self.records))
        self.assertFalse(sweetness_variants(dict(self.first, user_record=True), self.records))

    def test_sweetness_switch_keeps_chart_detail_selectbox_and_diy_on_one_record(self):
        app = open_app("现制奶茶")
        app.selectbox(key="tea.catalog.pick").set_value(("霸王茶姬", "伯牙绝弦")).run()
        self.assertFalse(app.exception)

        def panel(css_class):
            return next(n.proto.body for n in app.get("html") if f'class="{css_class}"' in n.proto.body)

        def variant():
            return next(n for n in app.selectbox if n.label == "查看哪个规格的资料？")

        def sweetness():
            return next(n for n in app.radio if n.label == "切换同配方甜度")

        self.assertEqual(sweetness().options, ["不另外加糖", "少糖", "标准糖"])
        self.assertIn("少 81 kcal", panel("tea-energy"))
        self.assertIn("待补", panel("tea-recipe"))
        sweetness().set_value("标准糖").run()
        self.assertFalse(app.exception)
        self.assertIn("211 <small>kcal", panel("tea-recipe"))
        self.assertIn("C 级", panel("tea-recipe"))
        self.assertIn("差值 0 kcal", panel("tea-energy"))
        self.assertIn("标准糖", variant().options[variant().value])
        variant().set_value(1).run()
        self.assertEqual(sweetness().value, "少糖")
        self.assertIn("少 4 kcal", panel("tea-energy"))
        app.button(key="tea.use.record").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(next(n for n in app.selectbox if n.label == "甜度").value, "少糖")
        self.assertIn("少 4 kcal", panel("tea-energy"))
        next(n for n in app.selectbox if n.label == "甜度").set_value("不另外加糖").run()
        self.assertIn("少 81 kcal", panel("tea-energy"))

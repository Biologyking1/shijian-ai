import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from shopping import default_profile
from tea_decisions import (
    BRAND, ENERGY, GRADE, KIND, PROFILE, compare_orders, comparison_group, matching_recipe,
    _token, extra_only, per_100_ml, published_grade, yuan_price,
)


def cup(**changes):
    return dict(dict(brand="甲家", name="红茶", kind="纯茶", region="中国大陆", scope="上海菜单",
                     size="中杯", sugar="无额外糖", temp="正常冰", toppings=[], volume=500,
                     kcal=80, price=15.0, grade="B", grade_scheme="上海试点",
                     source="https://example.org/tea"), **changes)


def decision_app():
    import streamlit as st
    from shopping import default_profile
    from tea_decisions import render_comparison, render_simulator
    base = dict(brand="霸王茶姬", name="乌龙", kind="纯茶", size="中杯", sugar="无糖", temp="冰",
                toppings=[], region="中国大陆", scope="门店公示", kcal=5, price=12.0,
                chagee_options={"temp": ["冰", "热"], "size": ["中杯", "大杯"], "sugar": ["无糖", "少糖"]},
                chagee_recipe={"temp": "冰", "size": "中杯", "sugar": "无糖", "tea": "", "milk": "", "bubble": "", "extra": ""})
    milk = dict(base, name="鲜奶乌龙", kind="鲜奶茶", kcal=150, price=16.0)
    records = [base, milk]
    st.session_state["tea.records"] = records
    if st.radio("页面", ["DIY", "比较"], key="page") == "DIY":
        render_simulator(records, default_profile(), set())
    else:
        render_comparison(default_profile(), set())


def widget(app, kind, label):
    return next(w for w in getattr(app, kind) if w.label == label)


class TeaDecisionTests(unittest.TestCase):
    def test_match_requires_market_product_and_entire_recipe(self):
        base = cup(toppings=["椰果", "茶冻"])
        changed = dict(base, toppings=["茶冻", "椰果"])
        self.assertIs(matching_recipe(base, changed, []), base)
        for key, value in dict(brand="乙家", name="绿茶", size="大杯", sugar="半糖", temp="少冰",
                               toppings=[], region="中国台湾", scope="不同门店").items():
            with self.subTest(key=key):
                self.assertEqual(matching_recipe(base, dict(changed, **{key: value}), [base]), {})
        alternate = dict(base, sugar="半糖", kcal=123)
        self.assertIs(matching_recipe(base, dict(changed, sugar="半糖"), [alternate]), alternate)
        receipt = dict(base, kind="", region="", from_receipt=True)
        self.assertIs(matching_recipe(receipt, dict(receipt, region="上海", kind="纯茶"), []), receipt)
        self.assertTrue(extra_only(base, dict(base, toppings=["椰果", "茶冻", "珍珠"])))
        self.assertFalse(extra_only(base, dict(base, toppings=["珍珠"])))
        self.assertFalse(extra_only(base, dict(base, size="大杯", toppings=["椰果", "茶冻", "珍珠"])))

    def test_grade_requires_source_and_same_scheme(self):
        self.assertIsNone(published_grade(cup(source="", estimated_grade="A")))
        self.assertIsNone(published_grade(cup(grade=None, estimated_grade="A")))
        prefs = dict(default_profile(), weights=dict(nutrition=100, budget=0, taste=0))
        rows = compare_orders([cup(grade="A"), cup(grade="D"), cup(grade_scheme="其他体系")],
                              prefs, GRADE, scheme="上海试点")
        self.assertEqual([d.score for d in rows], [100, 0, None])
        self.assertEqual([d.rank for d in rows], [1, 2, None])

    def test_missing_zero_and_per_cup_conversion(self):
        self.assertEqual(per_100_ml(cup(volume=None, kcal=0)), {})
        data = per_100_ml(cup(kcal=0, total_sugar=5, sodium=100, protein=2))
        self.assertEqual(data, {"energy": 0, "sugar": 1, "sodium": 20, "protein": .4})
        card = cup(volume=None, kcal=None, per100={"total_sugar": 5, "sodium": 0, "kcal": 30})
        self.assertEqual(per_100_ml(card), {"sugar": 5, "sodium": 0, "energy": 30 * 4.184})
        prefs = dict(default_profile(), weights=dict(nutrition=100, budget=0, taste=0))
        rows = compare_orders([cup(volume=None, kcal=0), cup(kcal=None), cup(kcal=200)], prefs, ENERGY, 200.)
        self.assertEqual([d.score for d in rows], [100, None, 50])
        rows = compare_orders([cup(kcal=20), cup(kcal=300, value_type="最高标示值")], prefs, ENERGY)
        self.assertEqual([d.rank for d in rows], [1, 1])
        self.assertNotEqual(rows[0].group, rows[1].group)
        prefs["goals"] = ["sodium"]
        rows = compare_orders([cup(sodium=1000), cup(sodium=0), cup()], prefs, PROFILE)
        self.assertEqual([d.score for d in rows], [50, 100, None])

    def test_budget_restrictions_flavors_and_weights(self):
        base = cup(price=20, flavors=["原味"])
        cheap = cup(price=8, flavors=["微甜"])
        prefs = dict(default_profile(), weights=dict(nutrition=0, budget=90, taste=10), flavors=["原味"])
        self.assertEqual([d.rank for d in compare_orders([base, cheap], prefs)], [2, 1])
        prefs["weights"].update(budget=10, taste=90)
        self.assertEqual([d.rank for d in compare_orders([base, cheap], prefs)], [1, 2])
        self.assertEqual(compare_orders([dict(base, flavors=[])], prefs)[0].status, "incomplete")
        prefs["budget"] = 10
        self.assertEqual(compare_orders([base], prefs, ENERGY)[0].status, "blocked")
        self.assertEqual(compare_orders([dict(cheap, price=None)], prefs)[0].status, "unresolved")
        prefs.update(allergens=["乳"], diets=["纯素"])
        self.assertEqual(compare_orders([cheap], prefs)[0].status, "unresolved")
        self.assertEqual(compare_orders([dict(cheap, toppings=["牛奶"])], prefs)[0].status, "blocked")

    def test_foreign_prices_and_comparison_groups(self):
        self.assertIsNone(yuan_price(cup(region="中国台湾", price=50)))
        self.assertIsNone(yuan_price(cup(currency="TWD", price=50)))
        self.assertEqual(yuan_price(cup(region="中国台湾", currency="CNY", price=10)), 10)
        a = cup()
        b = cup(kind="鲜奶茶")
        c = cup(brand="乙家")
        self.assertEqual(comparison_group([a, b, c], BRAND, "甲家"), ([a, b], True))
        self.assertEqual(comparison_group([a, b, c], KIND, "纯茶"), ([a, c], True))
        self.assertEqual(comparison_group([a, c], BRAND, "甲家"), ([a], False))

    def test_edit_delete_select_and_switch_pages(self):
        app = AppTest.from_function(decision_app, default_timeout=15).run()
        self.assertFalse(app.exception)
        widget(app, "button", "加入茶饮比较").click().run()
        picker = widget(app, "selectbox", "从哪份配方开始？")
        picker.set_value(_token(app.session_state["tea.records"][1])).run()
        widget(app, "button", "加入茶饮比较").click().run()
        app.radio(key="page").set_value("比较").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["tea.cart"]), 2)
        self.assertEqual(len([b for b in app.button if b.label == "选这杯用于消费记录"]), 2)
        target = app.session_state["tea.cart"][0]["id"]
        app.selectbox(key="tea.compare.edit").set_value(target).run()
        widget(app, "number_input", "这份配方的实际总价（人民币元，含加料）").set_value(6.5).run()
        widget(app, "button", "保存候选修改").click().run()
        self.assertEqual(app.session_state["tea.cart"][0]["price"], 6.5)
        app.button(key="tea.compare.pick." + target).click().run()
        self.assertEqual(app.session_state["tea.last_order"]["price"], 6.5)
        widget(app, "button", "移除这杯候选").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["tea.cart"]), 1)
        app.radio(key="page").set_value("DIY").run()
        self.assertEqual(widget(app, "selectbox", "从哪份配方开始？").options[-1],
                         "霸王茶姬 · 鲜奶乌龙 · 中国大陆 · 中杯 · 无糖 · 冰 ｜ 门店公示")

    def test_explicit_live_lookup_and_session_reuse(self):
        with patch("tea_chagee.recent_recipe", return_value=None) as lookup:
            app = AppTest.from_function(decision_app, default_timeout=15).run()
            self.assertEqual(widget(app, "selectbox", "杯型").options, ["中杯", "大杯"])
            self.assertEqual(widget(app, "selectbox", "甜度").options, ["无糖", "少糖"])
            self.assertEqual(widget(app, "selectbox", "温度 / 冰量").options, ["冰", "热"])
            widget(app, "selectbox", "温度 / 冰量").set_value("热").run()
            lookup.assert_not_called()
            widget(app, "button", "向霸王茶姬查询这份改配").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.session_state["tea.live_variants"])
            self.assertIsNone(widget(app, "number_input", "本配方公布的能量（kcal / 杯）").value)
            request = lookup.call_args.args
            self.assertEqual(request[0], "乌龙")
            self.assertEqual(request[1]["temp"], "热")
            base = app.session_state["tea.records"][0]
            lookup.return_value = {**base, "temp": "热", "kcal": 30, "grade": "A", "chagee_recipe": request[1],
                                   "grade_scheme": "测试体系", "source": "https://example.org/official"}
            widget(app, "button", "向霸王茶姬查询这份改配").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(widget(app, "number_input", "本配方公布的能量（kcal / 杯）").value, 30)
            record = next(iter(app.session_state["tea.live_variants"].values()))
            self.assertEqual((record["kcal"], record["grade"]), (30, "A"))
            app.radio(key="page").set_value("比较").run()
            self.assertTrue(any("热" in item for item in app.multiselect(key="tea.compare.quick").options))
            app.radio(key="page").set_value("DIY").run()
            widget(app, "selectbox", "温度 / 冰量").set_value("热").run()
            self.assertFalse(any(b.label == "向霸王茶姬查询这份改配" for b in app.button))
            self.assertEqual(lookup.call_count, 2)

    def test_quick_add_catalogue_recipes_and_restrict_to_matching_groups(self):
        app = AppTest.from_function(decision_app, default_timeout=15).run()
        app.radio(key="page").set_value("比较").run()
        options = [_token(r) for r in app.session_state["tea.records"]]
        app.multiselect(key="tea.compare.quick").set_value(options).run()
        app.button(key="tea.compare.quick_add").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["tea.cart"]), 2)
        self.assertIn("第 1 名", " ".join(x.value for x in app.markdown))
        app.radio(key="tea.compare.mode").set_value(KIND).run()
        self.assertIn("这个组还需加入另一个品牌。", [x.value for x in app.info])

    def test_real_catalogue_size_change_and_grade_ranking_with_entered_prices(self):
        from tea_catalog import CATALOG
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
        app.button(key="enter_tea").click().run()
        app.radio(key="tea.route").set_value("DIY 点单").run()
        records = [r for r in CATALOG if r["brand"] == "清心福全" and r["name"] == "鲜奶茶"]
        medium = next(r for r in records if r["size"] == "中杯")
        large = next(r for r in records if r["size"] == "大杯")
        widget(app, "selectbox", "从哪份配方开始？").set_value(_token(medium)).run()
        widget(app, "selectbox", "杯型").set_value("大杯").run()
        self.assertEqual(next(m for m in app.metric if "每杯能量" in m.label).value, f"{large['kcal']:g} kcal")
        app.radio(key="tea.route").set_value("比较与推荐").run()
        # Historical pilot entries have a published grade even when cup energy is unknown.
        milk = next(r for r in CATALOG if r["brand"] == "霸王茶姬" and r["kind"] == "鲜奶茶"
                    and r["grade"] == "B" and r.get("kcal") is None)
        tea = next(r for r in CATALOG if r["brand"] == "霸王茶姬" and r["kind"] == "纯茶"
                   and r["grade"] == "A" and r["grade_scheme"] == milk["grade_scheme"])
        app.multiselect(key="tea.compare.quick").set_value([_token(tea), _token(milk)]).run()
        app.button(key="tea.compare.quick_add").click().run()
        self.assertEqual(app.selectbox(key="tea.compare.measure").value, GRADE)
        for order in app.session_state["tea.cart"]:
            app.number_input(key="tea.fill.price." + order["id"]).set_value(12.0)
        widget(app, "button", "保存本组资料并计算").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len([w for w in app.markdown if w.value.startswith("第 ")]), 2)


if __name__ == "__main__":
    unittest.main()

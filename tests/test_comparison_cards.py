import unittest

from streamlit.testing.v1 import AppTest


def shopping_page():
    import streamlit as st
    from nutrition import label_from_payload
    from shopping import default_profile
    from shopping_views import compare_decisions

    base = dict(name="原味", basis="per_100_ml", label_state="as_sold",
                nutrients={"energy": 120, "sodium": 20}, price=5, flavors=["清淡"])
    variants = st.session_state.get("variants", [{}, {"name": "<img src=x>", "price": 10}])
    prefs = {**default_profile(), **st.session_state.get("prefs", {})}
    compare_decisions([label_from_payload({**base, **v}) for v in variants], prefs)


def card(app):
    return next((x.proto.body for x in app.get("html") if 'class="food-pair"' in x.proto.body), "")


def tea_page():
    import streamlit as st
    from shopping import default_profile
    from tea_decisions import render_comparison

    base = dict(brand="茶铺", region="中国台湾", kcal=80, size="中杯", value_type="最高标示值",
                flavors=["原味"], temp="冰", sugar="无糖", toppings=[], price=60, currency="TWD")
    st.session_state["tea.records"] = []
    st.session_state["tea.cart"] = [{**base, "id": i, "kind": kind, "name": name}
                                    for i, kind, name in [("a", "纯茶", "乌龙"), ("b", "纯茶", "红茶"),
                                                          ("c", "鲜奶茶", "奶乌龙")]]
    render_comparison(default_profile(), set())


class ComparisonCardsTests(unittest.TestCase):
    def test_prices_explain_tiebreak_and_names_are_escaped(self):
        app = AppTest.from_function(shopping_page, default_timeout=15).run()
        html = card(app)
        self.assertIn("价格", html)
        self.assertIn("左侧", html)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertNotIn("<img src=x>", html)
        self.assertIn("120 kJ", html)
        self.assertIn("100 mL", html)

    def test_tie_and_budget_exclusion_follow_displayed_decisions(self):
        app = AppTest.from_function(shopping_page, default_timeout=15)
        app.session_state["variants"] = [{}, {"price": 5.00001}]
        app.run()
        self.assertIn("并列", card(app))
        app.session_state["prefs"] = {"budget": 5}
        app.run()
        self.assertIn("超过预算", card(app))
        self.assertNotIn("并列", card(app))

    def test_no_numeric_energy_comparison_across_states_or_units(self):
        for variant in [{"label_state": "prepared"}, {"basis": "per_100_g"}]:
            with self.subTest(variant=variant):
                app = AppTest.from_function(shopping_page, default_timeout=15)
                app.session_state["variants"] = [{}, variant]
                app.run()
                self.assertIn("口径", card(app))
                self.assertNotIn("120 kJ", card(app))
                self.assertNotIn("并列", card(app))

    def test_select_two_without_dropping_other_rows(self):
        app = AppTest.from_function(shopping_page, default_timeout=15)
        app.session_state["variants"] = [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}]
        app.run()
        self.assertIn("乙", card(app))
        app.selectbox(key="shopping.pair.right").set_value(2).run()
        self.assertIn("丙", card(app))
        self.assertNotIn("乙", card(app))
        self.assertEqual(len(app.dataframe[0].value), 3)

    def test_tea_pair_respects_group_upper_bounds_and_currency(self):
        app = AppTest.from_function(tea_page, default_timeout=15).run()
        self.assertFalse(app.exception)
        html = card(app)
        self.assertIn("奶乌龙", html)
        self.assertNotIn("红茶", html)
        self.assertIn("最高 80 kcal", html)
        self.assertNotIn("60 元", html)
        self.assertIn("待补", html)


if __name__ == "__main__":
    unittest.main()

import unittest

from guide_ui import portion_html
from test_app import open_app


class GuideUITests(unittest.TestCase):
    def test_home_example_switches_area_and_preserves_optional_profile_on_return(self):
        app = open_app(None)
        app.number_input(key="person_age").set_value(24).run()
        app.button(key="guide_demo").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="food_area").value, "现制奶茶")
        self.assertEqual(app.text_input(key="tea.name").value, "伯牙绝弦")
        self.assertTrue(any('class="tea-energy"' in row.proto.body for row in app.get("html")))
        app.button(key="guide_home").click().run()
        self.assertIsNone(app.radio(key="food_area").value)
        self.assertEqual(app.number_input(key="person_age").value, 24)
        app.radio(key="food_area").set_value("预包装食品").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key="load_demo"))

    def test_quick_portions_keep_graph_table_and_slider_in_sync(self):
        app = open_app()
        app.button(key="load_demo").click().run()
        app.button(key="apply_label").click().run()
        for key, amount, grams in [("dose_half", 250, "20 g"), ("dose_full", 500, "40 g")]:
            app.button(key=key).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.slider(key="drag_portion").value, amount)
            self.assertEqual(app.dataframe[0].value.loc["碳水化合物", "这次摄入"], grams)
            html = next(n.proto.body for n in app.get("html") if 'class="guide-portion"' in n.proto.body)
            self.assertIn(f"{amount} <small>mL", html)
            self.assertIn("数值待补", html)
        app.slider(key="drag_portion").set_value(0.0).run()
        self.assertIsNone(app.selectbox(key="portion_choice").value)
        self.assertEqual(app.dataframe[0].value.loc["碳水化合物", "这次摄入"], "0 g")

    def test_unknown_package_and_measured_zero_stay_distinct(self):
        html = portion_html(1, "份", None, {"sugar": 0})
        self.assertNotIn("guide-vessel", html)
        self.assertNotIn("数值待补", html)
        self.assertIn("0<small> g", html)
        self.assertIn("150%", portion_html(150, "g", 100, {"carbs": 20}))

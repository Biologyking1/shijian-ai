from pathlib import Path
import re
import unittest

from PIL import Image

from guide_ui import portion_html
from test_app import open_app


class GuideUITests(unittest.TestCase):
    def test_home_video_only_loads_after_opening_the_demos_dialog(self):
        app = open_app(None)
        self.assertFalse(app.get("video"))
        app.button(key="guide_video").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("video")), 1)
        self.assertFalse(app.get("video")[0].proto.autoplay)

    def test_home_has_two_distinct_photos_inside_the_navigation_buttons(self):
        app = open_app(None)
        photos = set()
        self.assertEqual([b.key for b in app.button if b.key in {"enter_food", "enter_tea"}],
                         ["enter_food", "enter_tea"])
        hero = next(n.proto.body for n in app.get("html") if '<header class="guide-intro">' in n.proto.body)
        self.assertIn('src="app/static/supermarket-shelves.webp"', hero)
        with Image.open(Path(__file__).resolve().parents[1] / "static/supermarket-shelves.webp") as photo:
            photo.load()
            self.assertGreater(photo.width, photo.height)
        for key, area in (("enter_food", "预包装食品"), ("enter_tea", "现制奶茶")):
            button = app.button(key=key)
            self.assertIn(area, button.label)
            match = re.search(r"!\[[^\]]*\]\(app/(static/[\w-]+\.webp)\)", button.label)
            self.assertIsNotNone(match)
            path = Path(__file__).resolve().parents[1] / match[1]
            with Image.open(path) as image:
                image.load()
                self.assertGreaterEqual(min(image.size), 300)
            photos.add(path.read_bytes())
            button.click().run()
            self.assertEqual(app.radio(key="food_area").value, area)
            app.button(key="guide_home").click().run()
        self.assertEqual(len(photos), 2)

    def test_home_food_shortcut_shows_calculator_and_preserves_existing_item(self):
        app = open_app(None)
        app.button(key="guide_food_demo").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="food_area").value, "预包装食品")
        app.button(key="dose_half").click().run()
        self.assertEqual(app.dataframe[0].value.loc["碳水化合物", "这次摄入"], "20 g")
        app.button(key="manual").click().run()
        current = app.session_state["single_product"]
        app.button(key="guide_home").click().run()
        self.assertEqual(app.button(key="guide_food_demo").label, "继续查看我的食品")
        app.button(key="guide_food_demo").click().run()
        self.assertEqual(app.session_state["single_product"].uid, current.uid)
        self.assertIsNone(app.session_state["single_product"].confirmed)

    def test_home_example_switches_area_and_preserves_optional_profile_on_return(self):
        app = open_app(None)
        app.number_input(key="person_age").set_value(24).run()
        app.button(key="guide_demo").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="food_area").value, "现制奶茶")
        self.assertEqual(app.text_input(key="tea.name").value, "伯牙绝弦")
        self.assertTrue(any('class="tea-energy"' in row.proto.body for row in app.get("html")))
        app.button(key="guide_home").click().run()
        self.assertTrue(app.button(key="enter_food"))
        self.assertEqual(app.number_input(key="person_age").value, 24)
        app.button(key="enter_food").click().run()
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

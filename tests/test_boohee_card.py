import os
import unittest
from unittest.mock import patch

from tea_decisions import published_grade
from test_app import open_app
from test_vision import image_bytes
from vision import VisionSettings, recognize_tea


class BooheeCardTests(unittest.TestCase):
    def test_screenshot_keeps_mass_basis_and_drops_third_party_grade(self):
        raw = dict(brand="样本店", name="测试奶茶", provider="boohee", grade="A",
                   basis="per_100g", mass=440, kcal=40, total_sugar=0)
        with patch("vision._transcribe", return_value=raw):
            card = recognize_tea(b"sample", VisionSettings("test", "", ""), card=True)
        self.assertEqual(card["basis"], "per_100g")
        self.assertEqual(card["mass"], 440)
        self.assertNotIn("grade", card)
        self.assertNotIn("volume", card)

    def open_boohee_form(self):
        app = open_app("现制奶茶")
        app.text_input(key="tea.brand").set_value("样本店")
        app.text_input(key="tea.name").set_value("测试奶茶").run()
        app.button(key="tea.search").click().run()
        ns = "tea.card.样本店.测试奶茶."
        app.radio(key=ns + "provider").set_value("薄荷健康 · 查奶茶").run()
        return app, ns + "boohee."

    def test_screenshot_only_prefills_matching_product_and_replacement_clears_it(self):
        raw = dict(brand="另一家", name="测试奶茶", size="大杯", basis="per_cup", kcal=220.0, grade="A")
        with patch.dict(os.environ, {"LING_API_KEY": "test-key"}), patch("tea_views.recognize_tea", return_value=raw):
            app, ns = self.open_boohee_form()
            uploader = next(w for w in app.get("file_uploader") if w.key == ns + "photo")
            uploader.set_value(("card.jpg", image_bytes(), "image/jpeg")).run()
            app.button(key=ns + "scan").click().run()
            self.assertTrue(any("品牌或品名" in err.value for err in app.error))
            self.assertNotIn(ns + "read", app.session_state)
            raw["brand"] = "样本店"
            app.button(key=ns + "scan").click().run()
            form = ns + str(app.session_state[ns + "version"])
            self.assertEqual(app.number_input(key=form + "kcal").value, 220)
            self.assertEqual(app.radio(key=form + "basis").value, "per_cup")
            self.assertFalse(any(w.key == form + "grade" for w in app.selectbox))
            next(w for w in app.get("file_uploader") if w.key == ns + "photo").clear().run()
            form = ns + str(app.session_state[ns + "version"])
            self.assertIsNone(app.number_input(key=form + "kcal").value)

    def test_mass_entry_needs_drink_weight_for_cup_total(self):
        app, ns = self.open_boohee_form()
        form = ns + "0"
        app.selectbox(key=form + "kind").set_value("鲜奶茶")
        app.text_input(key=form + "size").set_value("大杯")
        app.text_input(key=form + "region").set_value("上海")
        app.radio(key=form + "basis").set_value("per_100g")
        app.number_input(key=form + "ml").set_value(500)
        app.number_input(key=form + "kcal").set_value(40)
        app.number_input(key=form + "total_sugar").set_value(0)
        app.checkbox(key=form + "checked").set_value(True)

        def submit():
            next(b for b in app.button if b.label == "保存这份核对资料").click().run()
            self.assertFalse(app.exception)
            return list(app.session_state["tea.custom"].values())[-1]

        record = submit()
        self.assertEqual(record["per100g"], {"kcal": 40.0, "total_sugar": 0.0})
        self.assertNotIn("kcal", record)
        self.assertEqual(record["per100"], {})
        self.assertTrue(any("每 100 g" in t.value.columns for t in app.table))
        self.assertIn("薄荷健康", record["source_label"])
        self.assertIsNone(record["toppings"])
        self.assertIsNone(published_grade(record))
        self.assertIsNone(record["estimated_grade"])
        app.run()
        app.number_input(key=form + "mass").set_value(450)
        record = submit()
        self.assertEqual(record["kcal"], 180)
        self.assertEqual(record["per100"]["kcal"], 36)
        self.assertEqual(record["total_sugar"], 0)

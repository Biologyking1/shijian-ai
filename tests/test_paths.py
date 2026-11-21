import unittest
import json
import os
from unittest.mock import patch

import httpx

from test_app import open_app
from test_vision import image_bytes


class PathTests(unittest.TestCase):
    def test_intake_slider_changes_table_and_only_uses_explicit_sugar(self):
        app = open_app()
        app.button(key="load_demo").click().run()
        app.number_input(key="nutrient_sugar").set_value(8.0)
        app.button(key="apply_label").click().run()
        app.slider(key="drag_portion").set_value(250.0).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value.loc["糖", "这次摄入"], "20 g")
        self.assertTrue(any("5 块方糖" in item.value for item in app.caption))
        app.radio(key="reading_focus").set_value("宣传语、配料与过敏原").run()
        self.assertFalse(app.exception)
        self.assertTrue(any(heading.value == "配料百科" for heading in app.subheader))
        app.radio(key="reading_focus").set_value("购买匹配度").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("营养性价比" in item.value for item in app.markdown))

    def test_comparison_and_shelf_share_verified_products(self):
        app = open_app()
        app.radio(key="work_route").set_value("多款比较").run()
        app.button(key="basket_demo").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["basket"]), 3)
        app.button(key="inspect_candidate").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="work_route").value, "单品解读")
        self.assertEqual(app.dataframe[0].value.loc["糖", "这次摄入"], "0 g")
        app.radio(key="work_route").set_value("货架购物助手").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["basket"]), 3)
        app.button(key="basket_manual").click().run()
        app.text_input(key="food_name").set_value("现场看到的商品")
        app.number_input(key="edit_price").set_value(3.2)
        app.button(key="apply_label").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.confirmed and item.confirmed.name == "现场看到的商品"
                            for item in app.session_state["basket"].values()))

    def test_shelf_keeps_field_evidence_and_requires_confirmation(self):
        payload = {"products": [{"name": "原味茶", "evidence": {"name": 1}, "nutrients": {"sugar": 2},
                                 "uncertain_fields": ["sugar"]}, {"name": "柠檬茶", "evidence": {"name": 1}}]}
        def handler(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client, \
             patch.dict(os.environ, {"LING_API_KEY": "unused-test-key"}), \
             patch("vision.httpx.post", side_effect=client.post):
            app = open_app()
            app.radio(key="work_route").set_value("货架购物助手").run()
            widget = next(w for w in app.get("file_uploader") if w.key == "batch_files")
            photo = image_bytes()
            widget.set_value(("shelf.jpg", photo, "image/jpeg")).run()
            app.button(key="batch_scan").click().run()
            self.assertFalse(app.exception)
            rows = list(app.session_state["basket"].values())
            self.assertTrue(all(r.confirmed is None and r.photos == (photo,) for r in rows))
            app.selectbox(key="basket_product").set_value(rows[0].uid).run()
            self.assertTrue(any("需要复核" in warning.value for warning in app.warning))
            self.assertTrue(any("对应原图 1" in caption.value for caption in app.caption))
            app.button(key="apply_label").click().run()
            self.assertIsNone(app.session_state["basket"][rows[0].uid].confirmed)
            self.assertTrue(any("这些存疑值" in warning.value for warning in app.warning))
            app.number_input(key="nutrient_sugar").set_value(4)
            app.button(key="apply_label").click().run()
            self.assertFalse(app.exception)
            result = app.session_state["basket"][rows[0].uid]
            self.assertEqual(result.original.nutrients["sugar"], 2)
            self.assertEqual(result.confirmed.nutrients["sugar"], 4)

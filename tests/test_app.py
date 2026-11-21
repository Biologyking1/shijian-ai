import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import streamlit as st
from streamlit.testing.v1 import AppTest

from test_vision import image_bytes


def open_app(area="预包装食品"):
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    if area is not None:
        app.radio(key="food_area").set_value(area).run()
    return app


class AppTests(unittest.TestCase):
    def test_camera_is_only_mounted_after_opt_in(self):
        app = open_app()
        self.assertFalse(app.get("camera_input"))
        app.toggle(key="camera_open").set_value(True).run()
        self.assertEqual(len(app.get("camera_input")), 1)
        app.toggle(key="camera_open").set_value(False).run()
        self.assertFalse(app.get("camera_input"))
        self.assertEqual(len(app.get("file_uploader")), 1)

    def test_capture_and_album_share_one_batch_with_removal_and_limit(self):
        frame = image_bytes()
        # AppTest supports upload events but has no camera shutter simulator.
        def camera_double(label, **kwargs):
            return st.file_uploader(label, type=["jpg"], **kwargs)

        with patch("streamlit.camera_input", side_effect=camera_double), patch.dict(os.environ, {"LING_API_KEY": "test-key"}):
            app = open_app()
            app.toggle(key="camera_open").set_value(True).run()
            camera = next(widget for widget in app.get("file_uploader") if widget.key == "camera_shot")
            camera.set_value(("shot.jpg", frame, "image/jpeg")).run()
            self.assertFalse(app.exception)
            self.assertFalse(app.toggle(key="camera_open").value)
            self.assertFalse(app.button(key="scan").disabled)
            album = [(f"album-{index}.jpg", frame, "image/jpeg") for index in range(3)]
            app.get("file_uploader")[0].set_value(album).run()
            self.assertTrue(app.button(key="scan").disabled)
            app.get("file_uploader")[0].set_value(album[:1]).run()
            with patch("vision.httpx.post", side_effect=httpx.ConnectError("offline")) as endpoint:
                app.button(key="scan").click().run()
                parts = json.loads(endpoint.call_args.kwargs["content"])["messages"][1]["content"]
                self.assertEqual(sum(part["type"] == "image_url" for part in parts), 2)
            app.button(key="remove_shot_0").click().run()
            app.get("file_uploader")[0].clear().run()
            self.assertTrue(app.button(key="scan").disabled)

    def test_demo_can_skip_profile_and_recalculate_half_bottle(self):
        app = open_app()
        self.assertFalse(app.exception)
        app.button(key="load_demo").click().run()
        app.button(key="apply_label").click().run()
        self.assertFalse(app.exception)
        app.number_input(key="portion").set_value(250).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value.loc["碳水化合物", "这次摄入"], "20 g")
        self.assertEqual(app.dataframe[0].value.loc["糖", "这次摄入"], "—")
        app.selectbox(key="portion_choice").set_value("整包 · 500 毫升").run()
        self.assertEqual(app.dataframe[0].value.loc["碳水化合物", "这次摄入"], "40 g")

    def test_manual_mode_updates_health_focus_without_reentering_label(self):
        app = open_app()
        app.button(key="manual").click().run()
        app.selectbox(key="basis").set_value("每 100 克").run()
        app.number_input(key="nutrient_sodium").set_value(300)
        app.button(key="apply_label").click().run()
        self.assertFalse(app.exception)
        app.multiselect(key="health_flags").set_value(["血压偏高或高血压"]).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value.index[0], "钠")
        self.assertEqual(app.dataframe[0].value.loc["钠", "这次摄入"], "300 mg")

    def test_uses_confirmed_label_serving_even_if_nutrition_is_listed_per_100g(self):
        app = open_app()
        app.button(key="manual").click().run()
        app.selectbox(key="basis").set_value("每 100 克")
        app.number_input(key="serving_size").set_value(25)
        app.selectbox(key="serving_unit").set_value("g")
        app.number_input(key="nutrient_sodium").set_value(400)
        app.button(key="apply_label").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value.loc["钠", "这次摄入"], "100 mg")

    def test_upload_requires_review_and_uses_user_corrected_values(self):
        def handler(request):
            self.assertNotIn("血压", request.content.decode())
            payload = {"name": "测试饮料", "basis": "per_100_ml", "nutrients": {"carbs": 9},
                       "evidence": {"name": 1, "basis": 1, "carbs": 1}}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with patch.dict(os.environ, {"LING_API_KEY": "test-key", "LING_BASE_URL": "https://example.test/v1"}):
                with patch("vision.httpx.post", side_effect=client.post):
                    app = open_app()
                    app.multiselect(key="health_flags").set_value(["血压偏高或高血压"]).run()
                    app.get("file_uploader")[0].set_value(("label.jpg", image_bytes(), "image/jpeg")).run()
                    app.button(key="scan").click().run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.dataframe)
                    app.number_input(key="nutrient_carbs").set_value(8)
                    app.button(key="apply_label").click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(app.dataframe[0].value.loc["碳水化合物", "这次摄入"], "8 g")

import os
import unittest
from unittest.mock import patch

from test_app import open_app
from tea_views import _numbers, _order_candidates
from vision import VisionError, VisionSettings, recognize_label, recognize_products, recognize_tea


class TeaLookupTests(unittest.TestCase):
    def test_cup_conversion_needs_volume_and_preserves_measured_zero(self):
        nutrients = {"kcal": 40, "total_sugar": 0, "volume": 500, "sodium": None}
        self.assertEqual(
            _numbers(nutrients, "per_100ml", 500), ({"kcal": 200, "total_sugar": 0}, {"kcal": 40, "total_sugar": 0})
        )
        self.assertEqual(_numbers(nutrients, "per_cup", None), ({"kcal": 40, "total_sugar": 0}, {}))
        self.assertEqual(_numbers(nutrients, "per_100ml", 0)[0], {})
        self.assertEqual(_numbers(nutrients, None, 500), ({}, {}))

    def test_visible_specifications_exclude_other_recipes(self):
        records = [
            dict(size="中杯", sugar="三分糖", toppings=[]),
            dict(size="大杯", sugar="三分糖", toppings=["珍珠"]),
            dict(size="大杯", sugar="三分糖", toppings=[]),
        ]
        self.assertEqual(_order_candidates(dict(size="大杯", sugar="三分糖", toppings=[]), records), [2])
        self.assertEqual(_order_candidates(dict(size="大杯"), records), [1, 2])
        self.assertEqual(_order_candidates(dict(size="小杯"), records), [])
        self.assertEqual(_order_candidates(dict(brand="测试"), records), [])

    def test_photo_domains_and_ocr_field_boundaries(self):
        settings = VisionSettings("test", "https://example.test/v1", "test")
        raw = dict(
            brand="茶店",
            name="茉莉",
            phone="private",
            price=12,
            grade="取餐区 A",
            basis="per_100ml",
            protein=2,
            total_sugar=0,
            sweetener=False,
            sat_fat=-1,
        )
        with patch("vision._transcribe", return_value=raw):
            self.assertEqual(recognize_tea(b"photo", settings), {"brand": "茶店", "name": "茉莉", "price": 12})
            card = recognize_tea(b"photo", settings, card=True)
            self.assertEqual(
                card,
                {
                    "brand": "茶店",
                    "name": "茉莉",
                    "basis": "per_100ml",
                    "protein": 2,
                    "total_sugar": 0,
                    "sweetener": False,
                },
            )
        with patch("vision._transcribe", return_value={"unsupported": True}):
            for func, arg in [
                (recognize_tea, b"photo"),
                (recognize_label, [b"photo"]),
                (recognize_products, [b"photo"]),
            ]:
                with self.subTest(func=func.__name__), self.assertRaises(VisionError):
                    func(arg, settings)

    def test_home_and_all_tea_routes_work_as_guest(self):
        app = open_app(None)
        self.assertIsNone(app.radio(key="food_area").value)
        self.assertFalse(app.get("file_uploader"))
        app.radio(key="food_area").set_value("现制奶茶").run()
        self.assertTrue(app.text_input(key="tea.brand"))
        for route in ["DIY 点单", "比较与推荐", "个人茶饮账本", "查一杯奶茶"]:
            app.radio(key="tea.route").set_value(route).run()
            self.assertFalse(app.exception, route)
        app.radio(key="food_area").set_value("预包装食品").run()
        self.assertTrue(app.button(key="load_demo"))
        self.assertFalse(app.exception)

    def test_unknown_brand_can_save_verified_card_then_open_simulator(self):
        app = open_app("现制奶茶")
        app.text_input(key="tea.brand").set_value("测试茶店")
        app.text_input(key="tea.name").set_value("测试鲜奶茶").run()
        app.button(key="tea.search").click().run()
        self.assertTrue(any("尚无" in n.value for n in app.info))
        key = "tea.card.测试茶店.测试鲜奶茶.0"
        app.selectbox(key=key + "kind").set_value("鲜奶茶")
        app.text_input(key=key + "region").set_value("中国内地")
        app.radio(key=key + "basis").set_value("per_100ml")
        app.number_input(key=key + "ml").set_value(500)
        app.number_input(key=key + "kcal").set_value(30)
        app.text_input(key=key + "source").set_value("测试门店的营养卡")
        app.checkbox(key=key + "checked").set_value(True)
        next(b for b in app.button if b.label == "保存这份核对资料").click().run()
        self.assertFalse(app.exception)
        item = next(iter(app.session_state["tea.custom"].values()))
        self.assertEqual(item["kcal"], 150)
        self.assertIsNone(item["estimated_grade"])
        app.button(key="tea.use.record").click().run()
        self.assertEqual(app.radio(key="tea.route").value, "DIY 点单")
        self.assertFalse(app.exception)

    def test_uploaded_receipt_prefills_editable_fields_without_stale_results(self):
        from test_vision import image_bytes

        data = image_bytes()
        with (
            patch.dict(os.environ, {"LING_API_KEY": "test-key"}),
            patch(
                "tea_views.recognize_tea",
                return_value={"brand": "样本茶店", "name": "测试红茶", "sugar": "微糖", "price": 12, "grade": "B"},
            ),
        ):
            app = open_app("现制奶茶")
            app.radio(key="tea.entry").set_value("拍摄或上传杯贴").run()
            upload = next(w for w in app.get("file_uploader") if w.key == "tea.receipt.file")
            upload.set_value(("cup.jpg", data, "image/jpeg")).run()
            app.button(key="tea.scan").click().run()
            self.assertEqual(app.text_input(key="tea.brand").value, "样本茶店")
            app.text_input(key="tea.name").set_value("红茶").run()
            app.button(key="tea.search").click().run()
            self.assertTrue(app.button(key="tea.use.slip"))
            self.assertFalse(app.exception)
            next(w for w in app.get("file_uploader") if w.key == "tea.receipt.file").clear().run()
            self.assertNotIn("tea.slip", app.session_state)
            self.assertFalse(app.exception)

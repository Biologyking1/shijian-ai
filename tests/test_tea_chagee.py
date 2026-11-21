import unittest
from unittest.mock import patch

import httpx

from tea_chagee import live_variant, read_recipe
from tea_catalog import exact_match


class OfficialCalculatorTests(unittest.TestCase):
    def test_public_reply_is_exactly_bound_to_product_and_recipe(self):
        raw = dict(
            productName="测试奶茶",
            productSpec="中杯",
            productBrix="微糖",
            productTemperature="标准冰",
            productType="原叶鲜奶茶",
            greenGrade="B",
            productQuantity="130.00",
            productProtein="2.80",
            tfa="0",
            productFat="-",
            productCarbohydrate="6.7",
            productCaffeine=None,
        )
        options = dict(productSpec="中杯,大杯", productBrix="微糖,标准糖", productTemperature="标准冰")

        def handler(request):
            self.assertEqual(request.url.host, "qmproductcomput.bwcj.com")
            self.assertNotIn("Authorization", request.headers)
            data = options if request.url.path.endswith("/space") else raw
            return httpx.Response(200, json={"code": "1000", "data": data})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            cup = read_recipe(client, "测试奶茶", {"sugar": "微糖"})
            self.assertEqual(cup["kcal"], 130)
            self.assertEqual(cup["trans_fat"], 0)
            self.assertIsNone(cup["fat"])
            self.assertNotIn("total_sugar", cup)
            self.assertEqual(cup["chagee_options"]["size"], ["中杯", "大杯"])
            self.assertEqual(cup["grade"], "B")
            self.assertIsNone(read_recipe(client, "另一品名"))
            self.assertIsNone(read_recipe(client, "测试奶茶", {"sugar": "标准糖"}))

    def test_live_variant_keeps_tea_base_and_declines_unlisted_extras(self):
        rows = [r for r in exact_match("霸王茶姬", "伯牙绝弦") if r.get("chagee_recipe")]
        self.assertGreaterEqual(len(rows), 2)
        medium = next(r for r in rows if r["size"] == "中杯" and r["sugar"] == "不另外加糖")
        with patch("tea_chagee.recent_recipe", return_value=medium) as fetch:
            self.assertIsNone(live_variant(medium, {**medium, "toppings": ["未知小料"]}))
            fetch.assert_not_called()
            self.assertIsNotNone(live_variant(medium, {**medium, "size": "大杯"}))
            self.assertEqual(fetch.call_args.args[1]["tea"], medium["chagee_recipe"]["tea"])
            self.assertEqual(fetch.call_args.args[1]["size"], "大杯")

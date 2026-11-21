import json
import unittest
from unittest.mock import patch

import httpx

from nutrition import label_from_payload
from test_vision import image_bytes
import vision


SETTINGS = vision.VisionSettings("test-key", "https://example.test/v1", "model")
PRICE_CONTEXT = {"currency": "CNY", "unit": "single_pack", "same_sku": True,
                 "condition": "unconditional"}


def recognize(payload, photo_count=1, *, batch=True):
    answer = {"choices": [{"message": {"content": json.dumps(payload)}}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=answer))
    with httpx.Client(transport=transport) as client:
        method = vision.recognize_products if batch else vision.recognize_label
        return method([image_bytes()] * photo_count, SETTINGS, client)


class BatchVisionTests(unittest.TestCase):
    def test_products_share_a_shelf_image_but_keep_their_own_fields(self):
        products = [
            {"name": "原味酸奶", "price": 5.5, "price_context": PRICE_CONTEXT, "flavors": ["原味"],
             "claims": ["含活菌"], "allergen_text": "含乳", "nutrients": {"sugar": 0},
             "evidence": {"name": 1, "price": 1, "flavors": 1, "claims": 2, "allergen_text": 2, "sugar": 2}},
            {"name": "草莓味酸奶", "flavors": ["草莓味"], "evidence": {"name": 1, "flavors": 1}},
        ]
        first, second = recognize({"products": products}, 2)
        self.assertEqual((first.price, first.nutrients, first.allergen_text), (5.5, {"sugar": 0}, "含乳"))
        self.assertEqual((first.claims, first.flavors, first.evidence["claims"]), (["含活菌"], ["原味"], 2))
        self.assertEqual(first.uncertain_fields, [])
        self.assertEqual((second.price, second.nutrients, second.flavors), (None, {}, ["草莓味"]))

    def test_incomplete_or_conditional_price_context_never_becomes_a_price(self):
        base = {"name": "薄脆饼干", "price": 12, "evidence": {"name": 1, "price": 1}}
        for changes in ({"currency": "JPY"}, {"unit": "per_kg"}, {"same_sku": False},
                        {"condition": "member"}, {"condition": "buy_two"}):
            with self.subTest(changes=changes):
                result, = recognize({"products": [{**base, "price_context": {**PRICE_CONTEXT, **changes}}]})
                self.assertIsNone(result.price)
                self.assertNotIn("price", result.evidence)
                self.assertIn("price", result.uncertain_fields)
        for extra in ({}, {"price_context": PRICE_CONTEXT, "uncertain_fields": ["price"]},
                      {"price_context": PRICE_CONTEXT, "uncertain_fields": ["name"]},
                      {"price_context": PRICE_CONTEXT, "evidence": {"name": 1, "price": 2}}):
            result, = recognize({"products": [{**base, **extra}]})
            self.assertIsNone(result.price)

    def test_uncertain_fields_are_normalized_and_unlinked_values_need_review(self):
        result, = recognize({"products": [{"name": "玉米脆", "claims": [" 烘烤 ", None, "烘烤"],
            "evidence": {"name": 1, "price": 1, "fat": True, "sodium": 2, "unknown_key": 1},
            "nutrients": {"fat": 3, "sodium": 12}, "uncertain_fields": ["carbs", "carbs", "unknown_key", {}]}]})
        self.assertEqual(result.claims, ["烘烤"])
        self.assertEqual(result.evidence, {"name": 1})
        self.assertEqual(set(result.uncertain_fields), {"fat", "sodium", "claims", "carbs"})

    def test_manual_prices_and_old_payload_defaults(self):
        manual = label_from_payload({"price": 7.5})
        self.assertEqual((manual.price, manual.evidence, manual.uncertain_fields), (7.5, {}, []))
        self.assertEqual((manual.claims, manual.flavors, manual.allergen_text), ([], [], ""))

    def test_manual_confirmation_preserves_only_valid_references(self):
        label = label_from_payload({"name": "燕麦片", "price": 9, "nutrients": {"sugar": 0},
                                    "evidence": {"name": 1, "sugar": 2, "fat": 1}}, photo_count=1)
        self.assertEqual(label.evidence, {"name": 1})
        self.assertEqual(label.uncertain_fields, [])

    def test_empty_shelf_and_mixed_products_in_single_mode(self):
        self.assertEqual(recognize({"products": []}), [])
        with self.assertRaises(vision.VisionError):
            recognize({"products": [{"name": "甲"}, {"name": "乙"}]}, batch=False)
        with self.assertRaises(vision.VisionError):
            recognize({"multiple_products": True}, batch=False)

    def test_reject_invalid_batch_count_and_oversize_wire_payload_before_sending(self):
        def unexpected(request):
            self.fail("Rejected input must not be transmitted")

        with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
            for count in (0, vision.MAX_BATCH_PHOTOS + 1):
                with self.assertRaises(vision.VisionError):
                    vision.recognize_products([b""] * count, SETTINGS, client)
            with patch.object(vision, "MAX_REQUEST_BYTES", 100):
                with self.assertRaisesRegex(vision.VisionError, "体积"):
                    vision.recognize_products([image_bytes()], SETTINGS, client)

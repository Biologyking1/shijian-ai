import base64
from io import BytesIO
import json
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from vision import VisionError, VisionSettings, recognize_label


def image_bytes():
    photo = Image.new("RGB", (64, 64), "white")
    exif = Image.Exif()
    exif[270] = "private metadata"
    output = BytesIO()
    photo.save(output, "JPEG", exif=exif)
    return output.getvalue()


class VisionTests(unittest.TestCase):
    def test_direct_connection_ignores_proxy_for_the_model_request(self):
        settings = VisionSettings("test-key", "https://example.test/v1", "model", direct_connection=True)
        response = httpx.Response(200, request=httpx.Request("POST", settings.base_url),
                                  json={"choices": [{"message": {"content": '{"name":"燕麦片"}'}}]})
        with patch("vision.httpx.post", return_value=response) as send:
            label = recognize_label([image_bytes()], settings)
        self.assertEqual(label.name, "燕麦片")
        self.assertIs(send.call_args.kwargs["trust_env"], False)

    def test_request_contains_only_processed_photos_and_reads_structured_label(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://example.test/v1/chat/completions")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "test-vision")
            message = body["messages"][1]["content"]
            photos = [item for item in message if item["type"] == "image_url"]
            self.assertEqual(len(photos), 2)
            value = photos[0]["image_url"]["url"]
            self.assertTrue(value.startswith("data:image/jpeg;base64,"))
            with Image.open(BytesIO(base64.b64decode(value.split(",", 1)[1]))) as image:
                self.assertFalse(image.getexif())
            return httpx.Response(200, json={"choices": [{"message": {"content":
                '```json\n{"name":"样例", "basis":"per_100_ml", "nutrients":{"carbs":8}}\n```'}}]})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            label = recognize_label([image_bytes(), image_bytes()],
                                    VisionSettings("test-key", "https://example.test/v1", "test-vision"), client)
        self.assertEqual(label.name, "样例")
        self.assertEqual(label.nutrients, {"carbs": 8})

    def test_bad_photo_is_rejected_before_an_api_call(self):
        def unexpected_request(request):
            self.fail("An invalid image must not be sent")

        with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
            with self.assertRaises(VisionError):
                recognize_label([b"not a photo"],
                                VisionSettings("key", "https://example.test/v1", "model"), client)

    def test_api_error_details_are_not_shown_to_user(self):
        def handler(request):
            return httpx.Response(401, text="private upstream details")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(VisionError) as error:
                recognize_label([image_bytes()],
                                VisionSettings("key", "https://example.test/v1", "model"), client)
        self.assertIn("API Key", str(error.exception))
        self.assertNotIn("private", str(error.exception))

import unittest
from unittest.mock import patch

from nutrition import label_from_payload
from result_challenges import portion_challenge
from test_app import open_app


def question(app):
    return next(w for w in app.radio if (w.key or "").startswith("result_guess_"))


def feedback(app):
    return [w.proto.body for w in app.get("html") if 'class="guess-reveal"' in w.proto.body]


class ResultChallengeTests(unittest.TestCase):
    def test_food_guess_reveals_label_math_and_keeps_actual_portion_independent(self):
        app = open_app(None)
        app.button(key="guide_food_demo").click().run()
        self.assertIsNone(question(app).value)
        self.assertIn("250 mL", question(app).label)
        self.assertIn("碳水化合物", question(app).label)
        self.assertFalse(feedback(app))
        question(app).set_value("8 g").run()
        self.assertIn("来对一下答案。20 g", feedback(app)[0])
        self.assertIn("250 ÷ 100", feedback(app)[0])
        question(app).set_value("20 g").run()
        self.assertIn("猜中了！20 g", feedback(app)[0])
        app.button(key="dose_full").click().run()
        self.assertEqual(app.slider(key="drag_portion").value, 500)
        self.assertEqual(question(app).value, "20 g")
        self.assertFalse(app.exception)

    def test_only_comparable_known_quantities_generate_food_questions(self):
        base = {"basis": "per_100_ml", "category": "drink", "label_state": "as_sold",
                "package_size": 500, "package_unit": "mL", "nutrients": {"sodium": 12}}
        with patch("result_challenges._guess") as render:
            for patch_data in ({"basis": "unknown"}, {"nutrients": {}}, {"nutrients": {"sugar": 0}},
                               {"basis": "per_serving", "serving_size": 800_000, "serving_unit": "g"}):
                portion_challenge(label_from_payload({**base, **patch_data}))
            render.assert_not_called()
            for patch_data in ({"label_state": "prepared"}, {"package_unit": "g"},
                               {"package_size": .001}, {"package_size": None}):
                portion_challenge(label_from_payload({**base, **patch_data}))
                _, prompt, _, answer, _, _ = render.call_args.args
                self.assertIn("200 mL", prompt)
                self.assertEqual(answer, "24 mg")
            portion_challenge(label_from_payload({**base, "nutrients": {"sugar": 4, "sodium": 12}}), ["sodium"])
            self.assertIn("钠", render.call_args.args[1])
            self.assertEqual(render.call_args.args[3], "30 mg")

    def test_changing_sweetness_starts_a_new_guess_with_the_correct_difference(self):
        app = open_app(None)
        app.button(key="guide_demo").click().run()
        question(app).set_value("能量更低").run()
        self.assertIn("猜中了！能量更低", feedback(app)[0])
        self.assertIn("相差 81 kcal", feedback(app)[0])
        next(w for w in app.radio if w.label == "切换同配方甜度").set_value("少糖").run()
        self.assertIsNone(question(app).value)
        self.assertFalse(feedback(app))
        question(app).set_value("能量相同").run()
        self.assertIn("相差 4 kcal", feedback(app)[0])
        self.assertFalse(app.exception)

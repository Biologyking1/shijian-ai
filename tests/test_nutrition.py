import unittest

from nutrition import Basis, calculate_bmi, label_from_payload, review_food, scale_nutrients


class NutritionTests(unittest.TestCase):
    def test_half_bottle_keeps_carbs_and_sugar_distinct(self):
        label = label_from_payload({"basis": "per_100_ml", "package_size": 500,
                                    "package_unit": "mL", "nutrients": {"carbs": 8, "sodium": 0}})
        values = scale_nutrients(label, 250, "mL")
        self.assertEqual(values, {"carbs": 20, "sodium": 0})

    def test_convert_labeled_serving_without_mixing_mass_and_volume(self):
        label = label_from_payload({"basis": "per_serving", "serving_size": 30,
                                    "serving_unit": "g", "nutrients": {"sodium": 120}})
        self.assertEqual(scale_nutrients(label, 45, "g"), {"sodium": 180})
        self.assertEqual(scale_nutrients(label, 1.5, "份"), {"sodium": 180})
        with self.assertRaises(ValueError):
            scale_nutrients(label, 45, "mL")

    def test_unreadable_basis_and_values_are_not_invented(self):
        label = label_from_payload({"basis": "estimated", "nutrients": {
            "carbs": "8–10", "sodium": -1, "sugar": "NaN", "fat": True}})
        self.assertIs(label.basis, Basis.UNKNOWN)
        self.assertEqual(label.nutrients, {})
        with self.assertRaises(ValueError):
            scale_nutrients(label, 100, "g")

    def test_prepared_food_metadata_is_preserved(self):
        label = label_from_payload({"basis": "per_100_ml", "label_state": "prepared",
                                    "nutrients": {"sodium": 12}})
        self.assertEqual(label.label_state, "prepared")
        self.assertEqual(scale_nutrients(label, 200, "mL"), {"sodium": 24})

    def test_multiple_health_concerns_and_nutrition_label_gaps(self):
        label = label_from_payload({"category": "drink", "basis": "per_100_ml",
                                    "nutrients": {"carbs": 8}})
        result = review_food(label, {"glucose", "pressure", "lipids"})
        self.assertEqual(result.focus, ("carbs", "sugar", "sodium", "sat_fat", "trans_fat"))
        self.assertIn("糖", result.missing)
        self.assertIn("白水", result.alternative)
        self.assertTrue(any("缩小份量" in line for line in result.considerations))

    def test_bmi_uses_centimeters_and_accepts_missing_measurements(self):
        self.assertEqual(calculate_bmi(170, 65), 22.5)
        self.assertIsNone(calculate_bmi(None, 65))

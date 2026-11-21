from dataclasses import replace
import json
import unittest

from streamlit.testing.v1 import AppTest

from nutrition import label_from_payload
from shopping import default_profile, evaluate, export_profile, import_profile, nutrition_per_yuan, rank_products, unit_values


def product(name="原味豆饮", **changes):
    fields = dict(name=name, category="drink", basis="per_100_ml", label_state="as_sold",
                  price=8, package_size=400, package_unit="mL", serving_size=200, serving_unit="mL",
                  nutrients={"sodium": 100, "protein": 4}, ingredients="水、大豆", flavors=["原味"])
    return label_from_payload({**fields, **changes})


class ShoppingTests(unittest.TestCase):
    def test_nutrition_value_compares_equal_quantities_and_requires_matching_units(self):
        prefs = default_profile()
        prefs.update(goals=["protein"], references={**prefs["references"], "protein": 4.0})
        # 4 g protein per 100 mL gives 50 personal preference points at this reference.
        # A 400 mL package at 8 yuan costs 2 yuan for the same 100 mL.
        self.assertEqual(nutrition_per_yuan(product(), prefs), 25.0)
        self.assertIsNone(nutrition_per_yuan(product(price=None), prefs))
        self.assertIsNone(nutrition_per_yuan(product(package_unit="g"), prefs))
        self.assertIsNone(nutrition_per_yuan(product(label_state="prepared"), prefs))

    def test_observed_zero_is_valid_and_missing_value_prevents_ranking(self):
        prefs = default_profile()
        prefs.update(weights={"nutrition": 100, "budget": 0, "taste": 0}, goals=["sodium"])
        low = evaluate(product(nutrients={"sodium": 0}), prefs)
        unknown = evaluate(product(nutrients={"protein": 3}), prefs)
        self.assertEqual(low.score, 100)
        self.assertIsNone(unknown.score)
        self.assertEqual(unknown.status, "incomplete")
        self.assertIsNone(evaluate(product(basis="unknown"), prefs).score)
        prefs["goals"].append("protein")
        self.assertIsNone(evaluate(product(nutrients={"sodium": 0}), prefs).score)

    def test_budget_cap_and_allergen_override_scores(self):
        prefs = default_profile()
        prefs.update(budget=8, weights={"nutrition": 100, "budget": 0, "taste": 0})
        self.assertEqual(evaluate(product(price=8), prefs).status, "eligible")
        self.assertEqual(evaluate(product(price=8.01), prefs).status, "blocked")
        self.assertEqual(evaluate(product(price=None), prefs).status, "unresolved")
        prefs["allergens"] = ["大豆"]
        allergen = evaluate(product(price=1, allergen_text="含大豆"), prefs)
        self.assertEqual(allergen.status, "blocked")
        self.assertIsNone(allergen.score)
        self.assertEqual(evaluate(product(ingredients="", allergen_text=""), prefs).status, "unresolved")

    def test_weights_change_top_choice_and_ties_share_rank(self):
        first = product("高价原味", price=12, flavors=["原味"])
        second = product("低价柠檬", price=3, flavors=["柠檬味"])
        prefs = default_profile()
        prefs.update(weights={"nutrition": 0, "budget": 90, "taste": 10}, flavors=["原味"])
        self.assertEqual([r.rank for r in rank_products([first, second], prefs)], [2, 1])
        prefs["weights"].update(budget=10, taste=90)
        self.assertEqual([r.rank for r in rank_products([first, second], prefs)], [1, 2])
        tie = rank_products([first, replace(first, name="同分食品")], prefs)
        self.assertEqual([r.rank for r in tie], [1, 1])
        self.assertIsNone(evaluate(replace(first, flavors=[]), prefs).score)

    def test_serving_converts_and_mixed_dimensions_rank_separately(self):
        prefs = default_profile()
        prefs.update(weights={"nutrition": 1, "budget": 0, "taste": 0}, goals=["protein"])
        standard = product()
        serving = product(basis="per_serving", serving_size=50, nutrients={"protein": 2})
        self.assertEqual(evaluate(standard, prefs).score, evaluate(serving, prefs).score)
        grams = product(basis="per_100_g", nutrients={"protein": 50})
        decisions = rank_products([standard, serving, grams], prefs)
        self.assertEqual([r.rank for r in decisions], [1, 1, 1])
        self.assertNotEqual(decisions[0].group, decisions[-1].group)
        unknown_state = product(label_state="unknown")
        self.assertIsNone(evaluate(unknown_state, prefs).score)

    def test_inactive_dimensions_and_zero_weights(self):
        prefs = default_profile()
        prefs.update(weights={"nutrition": 40, "budget": 1, "taste": 80}, goals=[], flavors=[])
        decision = evaluate(product(), prefs)
        self.assertEqual(decision.score, decision.parts["budget"].score)
        prefs["weights"]["budget"] = 0
        self.assertEqual(evaluate(product(), prefs).status, "unscored")

    def test_unit_costs_respect_preparation_and_units(self):
        label = product()
        facts = unit_values(label)
        self.assertIn("2 元/100 mL", facts)
        self.assertIn("4 元/份", facts)
        self.assertIn("蛋白质 2 g/元", facts)
        self.assertNotIn("蛋白质", unit_values(replace(label, label_state="prepared")))
        self.assertNotIn("元/份", unit_values(replace(label, label_state="prepared")))
        self.assertNotIn("蛋白质", unit_values(replace(label, package_unit="g")))
        self.assertNotIn("g/元", unit_values(replace(label, price=0)))

    def test_profile_round_trip_and_bad_imports(self):
        prefs = default_profile()
        prefs.update(flavors=["柠檬"], allergens=["花生", "芒果"], budget=5)
        self.assertEqual(import_profile(export_profile(prefs)), prefs)
        payload = json.loads(export_profile(prefs))
        for key, value in (("budget", -1), ("budget", True), ("diet", "纯素"),
                           ("allergens", [""]), ("allergens", [10]), ("watch", "奶"),
                           ("weights", {"nutrition": 40}), ("goals", ["not_a_nutrient"])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                import_profile(json.dumps({**payload, "profile": {**prefs, key: value}}))
        for data in ("broken", '{"version":99}', b"x" * 40000):
            with self.assertRaises(ValueError):
                import_profile(data)


def shopping_ui():
    from nutrition import label_from_payload
    from shopping_views import compare_decisions, profile_panel, single_decision

    prefs = profile_panel()
    example = dict(label_state="as_sold", basis="per_100_ml", nutrients={"sodium": 100})
    first = label_from_payload(dict(example, name="原味", price=9, flavors=["原味"]))
    second = label_from_payload(dict(example, name="微辣", price=2, flavors=["微辣"]))
    single_decision(first, prefs)
    compare_decisions([first, second], prefs)


class ShoppingUiTests(unittest.TestCase):
    def test_budget_change_reranks_and_json_import_updates_widgets(self):
        app = AppTest.from_function(shopping_ui, default_timeout=10).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.get("file_uploader"))
        app.number_input(key="shopping.pref.budget").set_value(3.0).run()
        self.assertEqual(app.dataframe[0].value["状态"].tolist(), ["不符合限制", "可参与推荐"])
        prefs = default_profile()
        prefs.update(flavors=["原味"], weights={"nutrition": 0, "budget": 0, "taste": 100})
        app.checkbox(key="shopping.import.open").set_value(True).run()
        app.get("file_uploader")[0].set_value(("prefs.json", export_profile(prefs), "application/json")).run()
        app.button(key="shopping.import.apply").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.slider(key="shopping.pref.weights.taste").value, 100)
        self.assertEqual(app.dataframe[0].value["组内排名"].tolist(), ["1", "2"])
        self.assertEqual(app.session_state["shopping.profile"], prefs)
        app.get("file_uploader")[0].set_value(("bad.json", b"{}", "application/json")).run()
        app.button(key="shopping.import.apply").click().run()
        self.assertTrue(app.error)
        self.assertEqual(app.session_state["shopping.profile"], prefs)

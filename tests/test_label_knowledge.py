import unittest

from nutrition import label_from_payload
from label_knowledge import (
    ALLERGEN_OPTIONS, DIET_OPTIONS, check_claim, ingredient_entries, ingredient_note,
    restriction_check, watch_alerts,
)


def label(**fields):
    return label_from_payload(fields)


class KnowledgeTests(unittest.TestCase):
    def test_allergen_declarations_preserve_scope(self):
        item = label(ingredients="水、食盐", allergen_text="不含花生、坚果；含牛奶；可能含有小麦和大豆。")
        blocked, _ = restriction_check(item, {"allergens": ALLERGEN_OPTIONS})
        blocked = "\n".join(blocked)
        self.assertNotIn("花生", blocked)
        self.assertNotIn("坚果", blocked)
        self.assertIn("牛奶", blocked)
        self.assertRegex(blocked, r"可能.*大豆")
        self.assertRegex(blocked, r"可能.*小麦")

    def test_equipment_contact_and_contradictory_declaration(self):
        item = label(ingredients="花生油、水", allergen_text="不含花生。本生产线也加工含有芝麻的食品。")
        blocked, _ = restriction_check(item, {"allergens": ["花生", "芝麻"]})
        self.assertEqual(len(blocked), 2)
        self.assertTrue(any("可能" in reason and "芝麻" in reason for reason in blocked))

    def test_custom_allergen_matches_literal_and_keeps_alias_gap_explicit(self):
        prefs = {"allergens": ["芒果"]}
        self.assertTrue(restriction_check(label(ingredients="芒果泥、水"), prefs)[0])
        possible, _ = restriction_check(label(ingredients="水", allergen_text="可能含芒果"), prefs)
        self.assertIn("可能", possible[0])
        blocked, unknown = restriction_check(label(ingredients="水", allergen_text="不含芒果，不与芒果共线生产"), prefs)
        self.assertFalse(blocked)
        self.assertTrue(unknown)

    def test_sources_are_not_inferred_from_characters(self):
        item = label(ingredients="椰奶、乳酸菌、蛋白质、荞麦、木糖醇、可可脂")
        blocked, missing = restriction_check(item, {"allergens": ["乳及乳制品", "蛋类", "小麦"]})
        self.assertFalse(blocked)
        self.assertTrue(missing)

    def test_unreadable_diet_evidence_and_confirmed_diet_conflict(self):
        self.assertIn("纯素", DIET_OPTIONS)
        unknown = label(ingredients="水", unreadable="配料表下半段看不清")
        blocked, missing = restriction_check(unknown, {"diets": ["纯素"]})
        self.assertFalse(blocked)
        self.assertTrue(missing)
        blocked, _ = restriction_check(label(ingredients="乳清粉、明胶"), {"diets": ["纯素", "蛋奶素"]})
        self.assertEqual(len(blocked), 2)

    def test_no_lactose_does_not_clear_milk_allergy(self):
        item = label(ingredients="无乳糖牛奶、乳糖酶", claims=["无乳糖"])
        blocked, _ = restriction_check(item, {"allergens": ["乳及乳制品"], "diets": ["限制乳糖"]})
        self.assertEqual(len(blocked), 1)
        self.assertIn("牛奶", blocked[0])

    def test_watch_terms_do_not_block_or_turn_into_positive_ingredients(self):
        item = label(ingredients="水、柠檬酸、三氯蔗糖", allergen_text="不含花生")
        prefs = {"watch": ["柠檬酸", "花生"], "diets": ["避免添加糖"]}
        blocked, _ = restriction_check(item, prefs)
        self.assertFalse(blocked)
        self.assertEqual(watch_alerts(item, prefs), ["柠檬酸"])

    def test_watch_aliases_are_soft_and_do_not_match_sucralose_as_sugar(self):
        item = label(ingredients="谷氨酸钠、三氯蔗糖")
        prefs = {"watch": ["味精", "代糖", "蔗糖", "添加糖"]}
        self.assertEqual(watch_alerts(item, prefs), ["味精", "代糖"])
        self.assertEqual(restriction_check(item, prefs), ([], []))

    def test_absence_needs_both_product_and_named_facility_evidence(self):
        prefs = {"allergens": ["花生"]}
        for text in ("不含花生", "不与花生共线生产", "不含花生并在不处理大豆的专线上生产",
                     "未添加花生，不与花生共线生产"):
            blocked, missing = restriction_check(label(ingredients="水、米", allergen_text=text), prefs)
            self.assertFalse(blocked)
            self.assertTrue(missing)
        for text in ("本品不含花生，不与花生共线生产。", "不含花生并在不处理花生的专线上生产。"):
            self.assertEqual(restriction_check(label(ingredients="水、米", allergen_text=text), prefs), ([], []))
            self.assertTrue(restriction_check(label(ingredients="花生粉", allergen_text=text), prefs)[0])
            self.assertTrue(restriction_check(label(ingredients="水", allergen_text=text + "可能含有花生。"), prefs)[0])
            self.assertTrue(restriction_check(label(ingredients="水", allergen_text=text, unreadable="配料有遮挡"), prefs)[1])

    def test_gluten_free_claim_with_complete_information(self):
        prefs = {"diets": ["无麸质"]}
        self.assertEqual(restriction_check(label(ingredients="大米、水", claims=["无麸质认证"]), prefs), ([], []))
        self.assertTrue(restriction_check(label(ingredients="大米、水", claims=["尚未取得无麸质认证"]), prefs)[1])
        self.assertTrue(restriction_check(label(ingredients="大米、小麦粉", claims=["无麸质"]), prefs)[0])
        self.assertTrue(restriction_check(label(ingredients="大米", claims=["无麸质"], allergen_text="可能含小麦"), prefs)[1])
        self.assertTrue(restriction_check(label(ingredients="大米", allergen_text="不保证不含麸质"), prefs)[1])

    def test_compound_ingredients_unknown_and_additive_lookup(self):
        entries = ingredient_entries("配料：水、复合调味料（食盐、味精）、黄原胶、XYZ-9")
        self.assertIn("味精", entries)
        self.assertIn("XYZ-9", entries)
        self.assertIn("增稠", "".join(ingredient_note("黄原胶")))
        self.assertIn("暂未收录", "".join(ingredient_note("XYZ-9")))

    def test_sugar_is_distinct_from_carbs_and_added_sugar(self):
        item = label(ingredients="水、三氯蔗糖", basis="per_100_ml", nutrients={"carbs": 0})
        self.assertIn("缺少", " ".join(check_claim(item, "零糖")))
        result = " ".join(check_claim(item, "无蔗糖"))
        self.assertNotIn("发现蔗糖来源", result)
        item = label(ingredients="水、白砂糖", basis="per_100_ml", nutrients={"sugar": 0.2})
        self.assertIn("白砂糖", " ".join(check_claim(item, "不添加糖")))
        self.assertIn("0.2", " ".join(check_claim(item, "零糖")))

    def test_compound_claims_and_per_serving_normalization(self):
        item = label(basis="per_serving", serving_size=200, serving_unit="mL",
                     nutrients={"sugar": 1, "fat": 4})
        results = check_claim(item, "0糖0脂")
        self.assertEqual(len(results), 2)
        self.assertIn("落在", results[0])
        self.assertIn("超出", results[1])

    def test_high_protein_alternate_energy_basis_and_missing_measurements(self):
        item = label(basis="per_100_g", nutrients={"protein": 8, "energy": 500})
        self.assertIn("420 kJ", " ".join(check_claim(item, "高蛋白")))
        self.assertIn("达到", " ".join(check_claim(item, "高蛋白")))
        item = label(basis="per_100_g", nutrients={"protein": 8})
        self.assertIn("缺少", " ".join(check_claim(item, "高蛋白")))
        self.assertIn("参照食品", " ".join(check_claim(item, "减盐25%")))

    def test_unknown_or_ambiguous_claims_request_specific_evidence(self):
        item = label()
        self.assertIn("具体", " ".join(check_claim(item, "0添加")))
        self.assertIn("检测", " ".join(check_claim(item, "手作鲜萃")))
        self.assertIn("配料", " ".join(check_claim(item, "不添加防腐剂")))

    def test_numeric_claims_match_and_mismatch_with_explicit_units(self):
        item = label(basis="per_100_ml", nutrients={"sugar": 3, "sodium": 120})
        self.assertIn("数值一致", " ".join(check_claim(item, "每100毫升含糖3克")))
        self.assertIn("数值不同", " ".join(check_claim(item, "每100毫升含糖2克")))
        self.assertIn("数值一致", " ".join(check_claim(item, "每100毫升钠0.12克")))
        self.assertIn("未注明", " ".join(check_claim(item, "含糖3克")))
        self.assertIn("单位", " ".join(check_claim(item, "每100克含糖3克")))

    def test_numeric_pack_claim_requires_sold_state_and_matching_net_unit(self):
        base = dict(basis="per_100_ml", nutrients={"protein": 2}, package_size=400, package_unit="mL")
        for state in ("unknown", "prepared"):
            self.assertIn("出售时", " ".join(check_claim(label(**base, label_state=state), "每瓶含蛋白质8g")))
        item = label(**base, label_state="as_sold")
        self.assertIn("数值一致", " ".join(check_claim(item, "每瓶含蛋白质8g")))
        item = label(**{**base, "package_unit": "g"}, label_state="as_sold")
        self.assertIn("单位", " ".join(check_claim(item, "每瓶含蛋白质8g")))

    def test_numeric_per_serving_and_missing_only_relevant_field(self):
        item = label(basis="per_serving", serving_size=25, serving_unit="g", nutrients={"protein": 3})
        self.assertIn("数值一致", " ".join(check_claim(item, "每份含蛋白质3克")))
        self.assertIn("数值一致", " ".join(check_claim(item, "每100g含蛋白质12g")))
        self.assertIn("缺少", " ".join(check_claim(item, "每份含糖5克")))


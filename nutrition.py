from dataclasses import dataclass, field, replace
from enum import Enum
from math import isfinite
from typing import Any


class Basis(str, Enum):
    UNKNOWN = "unknown"
    GRAMS = "per_100_g"
    MILLILITERS = "per_100_ml"
    SERVING = "per_serving"


NUTRIENTS = {
    "energy": ("能量", "kJ"), "protein": ("蛋白质", "g"), "fat": ("脂肪", "g"),
    "sat_fat": ("饱和脂肪", "g"), "trans_fat": ("反式脂肪", "g"),
    "carbs": ("碳水化合物", "g"), "sugar": ("糖", "g"),
    "fiber": ("膳食纤维", "g"), "sodium": ("钠", "mg"),
}

FIELD_KEYS = (
    "name", "category", "ingredients", "basis", "label_state", "serving_size", "serving_unit",
    "package_size", "package_unit", "price", "claims", "flavors", "allergen_text", *NUTRIENTS,
)

CATEGORIES = {
    "other": "其他食品", "drink": "饮料", "noodles": "方便面或冲泡主食",
    "snack": "咸味零食", "sweet": "甜点或甜味零食", "processed_meat": "加工肉制品",
}

FOCUS = {
    "glucose": ("carbs", "sugar"),
    "pressure": ("sodium",),
    "lipids": ("sat_fat", "trans_fat"),
}

EXPLANATIONS = {
    "carbs": "碳水化合物包括糖和淀粉等。看这次的摄入量，比只看每 100 克或毫升更贴近实际。",
    "sugar": "标签单列的糖可能同时包含天然存在的糖和添加糖。",
    "sodium": "钠可以来自盐，也可以来自其他配料。按实际吃掉的份量看钠摄入。",
    "sat_fat": "饱和脂肪属于总脂肪的一部分，配方和食用量都会影响实际摄入。",
    "trans_fat": "反式脂肪是脂肪中的一类，可留意包装是否单独标示。",
}


@dataclass(frozen=True)
class FoodLabel:
    name: str
    category: str
    ingredients: str
    basis: Basis
    label_state: str
    serving_size: float | None
    serving_unit: str | None
    package_size: float | None
    package_unit: str | None
    nutrients: dict[str, float]
    unreadable: str
    price: float | None = None
    claims: list[str] = field(default_factory=list)
    flavors: list[str] = field(default_factory=list)
    allergen_text: str = ""
    evidence: dict[str, int] = field(default_factory=dict)
    uncertain_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FoodReview:
    focus: tuple[str, ...]
    missing: tuple[str, ...]
    how: str
    alternative: str
    considerations: tuple[str, ...]


def _quantity(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(number) or not 0 <= number <= 1_000_000 or (positive and number < 0.001):
        return None
    return number


def _text(value: Any, max_length: int) -> str:
    return value.strip()[:max_length] if isinstance(value, str) else ""


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := _text(item, 200))))[:50]


def populated_fields(label: FoodLabel) -> set[str]:
    result = set(label.nutrients)
    for key in FIELD_KEYS:
        if key in NUTRIENTS:
            continue
        value = getattr(label, key)
        if value is not None and value != [] and value != "" and value != "unknown":
            result.add(key)
    return result


def label_from_payload(payload: dict[str, Any], *, photo_count: int | None = None) -> FoodLabel:
    basis_value = _text(payload.get("basis"), 30)
    try:
        basis = Basis(basis_value)
    except ValueError:
        basis = Basis.UNKNOWN
    category = _text(payload.get("category"), 30)
    state = _text(payload.get("label_state"), 20)
    serving_unit = _text(payload.get("serving_unit"), 5)
    package_unit = _text(payload.get("package_unit"), 5)
    raw_nutrients = payload.get("nutrients")
    nutrients = {}
    if isinstance(raw_nutrients, dict):
        for key in NUTRIENTS:
            number = _quantity(raw_nutrients.get(key))
            if number is not None:
                nutrients[key] = number
    label = FoodLabel(
        name=_text(payload.get("name"), 100),
        category=category if category in CATEGORIES else "other",
        ingredients=_text(payload.get("ingredients"), 2500),
        basis=basis,
        label_state=state if state in {"as_sold", "prepared"} else "unknown",
        serving_size=_quantity(payload.get("serving_size"), positive=True),
        serving_unit=serving_unit if serving_unit in {"g", "mL"} else None,
        package_size=_quantity(payload.get("package_size"), positive=True),
        package_unit=package_unit if package_unit in {"g", "mL"} else None,
        nutrients=nutrients,
        unreadable=_text(payload.get("unreadable"), 300),
        price=_quantity(payload.get("price")),
        claims=_text_list(payload.get("claims")),
        flavors=_text_list(payload.get("flavors")),
        allergen_text=_text(payload.get("allergen_text"), 1500),
        uncertain_fields=[key for key in _text_list(payload.get("uncertain_fields")) if key in FIELD_KEYS],
    )
    raw_evidence = payload.get("evidence")
    if photo_count is None or not isinstance(raw_evidence, dict):
        return label
    fields = populated_fields(label)
    if category not in CATEGORIES:
        fields.discard("category")
    evidence = {key: number for key, number in raw_evidence.items()
                if key in fields and type(number) is int and 1 <= number <= photo_count}
    return replace(label, evidence=evidence)


def calculate_bmi(height_cm: float | None, weight_kg: float | None) -> float | None:
    height = _quantity(height_cm, positive=True)
    weight = _quantity(weight_kg, positive=True)
    if height is None or weight is None:
        return None
    return round(weight / (height / 100) ** 2, 1)


def portion_reference(label: FoodLabel) -> tuple[float, str] | None:
    if label.basis == Basis.GRAMS:
        return 100.0, "g"
    if label.basis == Basis.MILLILITERS:
        return 100.0, "mL"
    if label.basis == Basis.SERVING:
        if label.serving_size and label.serving_unit:
            return label.serving_size, label.serving_unit
        return 1.0, "份"
    return None


def scale_nutrients(label: FoodLabel, portion: float, unit: str) -> dict[str, float]:
    amount = _quantity(portion, positive=True)
    reference = portion_reference(label)
    if amount is None or reference is None:
        raise ValueError("需要有效份量和标签标示口径。")
    reference_size, reference_unit = reference
    if label.basis == Basis.SERVING and unit == "份":
        reference_size = 1.0
    elif unit != reference_unit:
        raise ValueError("食用量与营养标签的单位不一致。")
    ratio = amount / reference_size
    return {key: value * ratio for key, value in label.nutrients.items()}


def review_food(label: FoodLabel, health_flags: set[str]) -> FoodReview:
    focus = tuple(key for flag, keys in FOCUS.items() if flag in health_flags for key in keys)
    missing = tuple(NUTRIENTS[key][0] for key in focus if key not in label.nutrients)
    how = "可以先把这次要吃的量分出来，再用上面的份量工具换算。"
    alternative = "如果是当零食，可以考虑一份新鲜水果。已有饮食限制时，按你的饮食计划选。"

    if label.category == "drink":
        how = "先用杯子量出打算喝的量。想试口味时，可以先倒一小杯，再看这杯的碳水和糖。"
        alternative = "如果主要是解渴，可以换成白水或无糖茶。"
    elif label.category == "noodles":
        how = "可以少放调料，搭配蔬菜和鸡蛋。换算只反映标签所标的状态。"
        alternative = "想吃一顿热主食，可以换成清汤面，自己加青菜和鸡蛋、少放盐。"
    elif label.category == "snack":
        how = "把要吃的量倒进小碟，按称出来的克数看钠和脂肪摄入。"
        alternative = "想吃脆口零食，可以试试无额外加盐的爆米花。"
    elif label.category == "sweet":
        how = "可以先分出一小块，把这次的份量计入当天零食。已有碳水计划时按计划安排。"
        alternative = "想吃甜口加餐，可以试试原味无糖酸奶搭配少量水果，留意实际份量。"
    elif label.category == "processed_meat":
        how = "先按实际克数查看钠和脂肪，再搭配少盐的主食和蔬菜。"
        alternative = "想给一餐加蛋白质，可以换成少盐烹调的鸡肉、鱼或鸡蛋。"

    considerations = []
    if "glucose" in health_flags and (label.nutrients.get("carbs", 0) > 0 or label.nutrients.get("sugar", 0) > 0):
        considerations.append("控糖时，可按这顿饭的碳水计划缩小份量，再看换算后的碳水摄入。")
    if "pressure" in health_flags and label.nutrients.get("sodium", 0) > 0:
        considerations.append("控压时，可把这份食品的钠计入整餐，搭配少盐菜肴，少加蘸料。")
    if "lipids" in health_flags and any(label.nutrients.get(key, 0) > 0 for key in ("sat_fat", "trans_fat")):
        considerations.append("控脂时，可查看这次实际吃进去的饱和脂肪或反式脂肪，并考虑缩小份量。")
    return FoodReview(focus, missing, how, alternative, tuple(considerations))

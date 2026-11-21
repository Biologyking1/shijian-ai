"""Consumer-entered preferences and deterministic shopping comparisons."""

from dataclasses import dataclass, field
import json
from math import isfinite
from unicodedata import normalize

from label_knowledge import DIET_OPTIONS, restriction_check
from nutrition import FoodLabel, NUTRIENTS, portion_reference, scale_nutrients


DIMENSIONS = {"nutrition": "营养", "budget": "价格", "taste": "口味"}
# Editable scales for the preference model. They carry no dietary threshold meaning.
GOALS = {
    "sodium": ("少钠", "less", 200.0),
    "protein": ("多蛋白质", "more", 5.0),
    "fiber": ("多膳食纤维", "more", 3.0),
    "sugar": ("少糖", "less", 5.0),
    "carbs": ("少碳水化合物", "less", 15.0),
    "fat": ("少脂肪", "less", 5.0),
    "sat_fat": ("少饱和脂肪", "less", 2.0),
    "trans_fat": ("少反式脂肪", "less", 1.0),
    "energy": ("少能量", "less", 500.0),
}
STATUS = {
    "blocked": "不符合限制", "unresolved": "限制待核对", "incomplete": "评分缺资料",
    "unscored": "仅核对限制", "eligible": "可参与推荐",
}


def default_profile() -> dict:
    return {
        "weights": {"nutrition": 60, "budget": 30, "taste": 10},
        "goals": ["sodium"], "references": {k: entry[2] for k, entry in GOALS.items()},
        "budget": None, "reference_price": 10.0,
        "flavors": [], "allergens": [], "diets": [], "watch": [],
    }


def export_profile(prefs: dict) -> bytes:
    return json.dumps({"version": 1, "profile": prefs}, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def _number(value, *, low, high) -> bool:
    return type(value) in (float, int) and low <= value <= high and isfinite(value)


def import_profile(data: bytes | str) -> dict:
    if len(data) > 32_768:
        raise ValueError("偏好文件超过 32 KB。")
    try:
        document = json.loads(data)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("文件不是有效的 JSON。") from error
    if (not isinstance(document, dict) or type(document.get("version")) is not int
            or document["version"] != 1):
        raise ValueError("请选择本应用导出的第 1 版偏好文件。")
    prefs = document.get("profile")
    if not isinstance(prefs, dict) or prefs.keys() != default_profile().keys():
        raise ValueError("偏好字段与当前版本不符，请检查文件。")
    weights = prefs["weights"]
    if (not isinstance(weights, dict) or weights.keys() != DIMENSIONS.keys()
            or any(type(x) is not int or not 0 <= x <= 100 for x in weights.values())):
        raise ValueError("各项权重须为 0 至 100 的整数。")
    refs = prefs["references"]
    if (not isinstance(refs, dict) or refs.keys() != GOALS.keys()
            or not all(_number(v, low=0.001, high=1_000_000) for v in refs.values())):
        raise ValueError("营养参考值无效。")
    if (not _number(prefs["reference_price"], low=0.01, high=1_000_000)
            or (prefs["budget"] is not None and not _number(prefs["budget"], low=0, high=1_000_000))):
        raise ValueError("单包预算或参考价格无效。")
    options = {"goals": GOALS, "diets": DIET_OPTIONS}
    for key in ("goals", "allergens", "diets", "watch", "flavors"):
        entries = prefs[key]
        if (not isinstance(entries, list) or len(entries) > 32
                or not all(isinstance(x, str) and x == x.strip() and 0 < len(x) <= 80 for x in entries)
                or len(set(entries)) != len(entries)
                or (key in options and any(x not in options[key] for x in entries))):
            raise ValueError("偏好中有无法识别的选项，请检查文件。")
    return prefs


@dataclass
class Part:
    score: float | None
    detail: str


@dataclass
class Decision:
    label: FoodLabel
    status: str
    parts: dict[str, Part] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    score: float | None = None
    group: str = ""
    rank: int | None = None


def active_weights(prefs: dict) -> dict[str, int]:
    return {key: value for key, value in prefs["weights"].items()
            if value and (key != "taste" or prefs["flavors"]) and (key != "nutrition" or prefs["goals"])}


def _density(label: FoodLabel) -> tuple[str, dict[str, float]]:
    reference = portion_reference(label)
    if reference is None or reference[1] not in {"g", "mL"}:
        return "", {}
    unit = reference[1]
    return unit, scale_nutrients(label, 100, unit)


def _nutrition_part(label, prefs, unit, values) -> Part:
    if not unit:
        return Part(None, "请确认标示口径。按份标示的食品还需填写每份大小和单位。")
    goals = prefs["goals"]
    scores = []
    details = []
    for key in goals:
        title, nutrient_unit = NUTRIENTS[key]
        if key not in values:
            details.append(f"{title}缺少数值")
            continue
        value = values[key]
        ref = prefs["references"][key]
        numerator = value if GOALS[key][1] == "more" else ref
        score = 100 * numerator / (value + ref)
        scores.append(score)
        details.append(f"{GOALS[key][0]} {value:g} {nutrient_unit}（参考 {ref:g}，{score:.1f} 分）")
    if label.label_state == "unknown":
        details.append("请确认营养表对应包装原状还是冲调后")
    total = sum(scores) / len(goals) if len(scores) == len(goals) and label.label_state != "unknown" else None
    return Part(total, f"每 100 {unit} · " + "；".join(details))


def _flavor_name(tag: str) -> str:
    name = normalize("NFKC", tag).strip().casefold()
    for suffix in ("风味", "口味", "味"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name


def _taste_part(label, targets) -> Part:
    if not label.flavors:
        return Part(None, "缺少口味标签，请核对包装。")
    actual = {_flavor_name(tag) for tag in label.flavors}
    hits = [item for item in targets if _flavor_name(item) in actual]
    info = "包装口味为" + "、".join(label.flavors)
    if hits:
        return Part(100, info + "，符合喜欢的" + "、".join(hits) + "。")
    return Part(0, info + "，与所选口味均未匹配。")


def evaluate(label: FoodLabel, prefs: dict) -> Decision:
    blocked, unresolved = restriction_check(label, prefs)
    result = Decision(label, "eligible", blocked=list(blocked), unresolved=list(unresolved))
    cap = prefs["budget"]
    if cap is not None:
        if label.price is None:
            result.unresolved.append(f"缺少单包价格，无法核对 {cap:g} 元预算。")
        elif label.price > cap:
            result.blocked.append(f"单包 {label.price:g} 元，超过预算 {cap:g} 元。")
    weights = active_weights(prefs)
    result.group = "按单包价格和口味"
    if "nutrition" in weights:
        unit, values = _density(label)
        state = {"as_sold": "包装原状", "prepared": "冲调后"}.get(label.label_state, "状态待核对")
        result.group = f"每 100 {unit} · {state}" if unit else "营养口径待核对"
        result.parts["nutrition"] = _nutrition_part(label, prefs, unit, values)
    if "budget" in weights:
        ref = prefs["reference_price"]
        result.parts["budget"] = (Part(None, "缺少单包价格。") if label.price is None else
                                  Part(100 * ref / (ref + label.price), f"单包 {label.price:g} 元，参考价 {ref:g} 元。"))
    if "taste" in weights:
        result.parts["taste"] = _taste_part(label, prefs["flavors"])
    if result.blocked:
        result.status = "blocked"
    elif result.unresolved:
        result.status = "unresolved"
    elif not weights:
        result.status = "unscored"
    elif any(part.score is None for part in result.parts.values()):
        result.status = "incomplete"
    else:
        result.score = sum(weights[k] * p.score for k, p in result.parts.items()) / sum(weights.values())
    return result


def rank_products(labels, prefs) -> list[Decision]:
    results = [evaluate(label, prefs) for label in labels]
    groups: dict[str, list[Decision]] = {}
    for result in results:
        if result.score is not None:
            groups.setdefault(result.group, []).append(result)
    for group in groups.values():
        last_score = None
        for position, result in enumerate(sorted(group, key=lambda item: item.score, reverse=True), start=1):
            score = round(result.score, 1)
            if score != last_score:
                rank = position
            result.rank = rank
            last_score = score
    return results


def nutrition_per_yuan(label: FoodLabel, prefs: dict) -> float | None:
    """Preference points for one standard quantity divided by the price of that quantity."""
    if not (prefs["goals"] and label.price and label.package_size and label.label_state == "as_sold"):
        return None
    unit, values = _density(label)
    if not unit or unit != label.package_unit:
        return None
    score = _nutrition_part(label, prefs, unit, values).score
    cost_for_100 = label.price * 100 / label.package_size
    return None if score is None else score / cost_for_100


def unit_values(label: FoodLabel) -> str:
    """Keep net-content price facts distinct from prepared nutrition/serving data."""
    if label.price is None:
        return "单包价格待补充"
    details = [f"{label.price:g} 元/包"]
    if label.package_size and label.package_unit:
        price_per_unit = label.price / label.package_size
        details.append(f"{100 * price_per_unit:.3g} 元/100 {label.package_unit}")
        if label.label_state == "as_sold":
            if label.serving_size and label.serving_unit == label.package_unit:
                details.append(f"{price_per_unit * label.serving_size:.3g} 元/份")
            unit, values = _density(label)
            if unit == label.package_unit and label.price > 0:
                for key in ("protein", "fiber"):
                    if key in values:
                        per_yuan = values[key] * label.package_size / 100 / label.price
                        details.append(f"{NUTRIENTS[key][0]} {per_yuan:.3g} g/元")
    return " · ".join(details)

"""Estimate a nutrient amount using the confirmed label and calculator basis."""

from math import isfinite

import nutrition
from result_challenges import _guess


def _amount(value):
    return f"{value:.3f}".rstrip("0").rstrip(".")


def render_portion_guess(label, focus, reference):
    if not reference or not label.nutrients:
        return
    base, unit = reference
    half_pack = label.label_state == "as_sold" and label.package_unit == unit and (label.package_size or 0) >= .002
    quantity = label.package_size / 2 if half_pack else base * 2
    if quantity > 1_000_000:
        return
    scaled = nutrition.scale_nutrients(label, quantity, unit)
    for nutrient in dict.fromkeys((*focus, "sugar", "carbs", "sodium", "energy", *label.nutrients)):
        if nutrient not in scaled:
            continue
        value = scaled[nutrient]
        if not isfinite(value) or value < .002:
            continue
        name, value_unit = nutrition.NUTRIENTS[nutrient]
        description = ("喝掉一半" if label.category == "drink" else "吃掉一半") if half_pack else "两倍标签份量"
        scenario = ("冲调后" if label.label_state == "prepared" else "") + f"{description}（{quantity:g} {unit}）"
        shown = [_amount(v) for v in (value, label.nutrients[nutrient], value / 2, value * 2)]
        choices = sorted(list(dict.fromkeys(shown))[:3], key=float)
        options = [f"{v} {value_unit}" for v in choices]
        answer = f"{shown[0]} {value_unit}"
        explanation = (f"标签上每 {base:g} {unit} 含{name} {label.nutrients[nutrient]:g} {value_unit}。"
                       f"按这次的 {quantity:g} {unit} 换算：{label.nutrients[nutrient]:g} × "
                       f"（{quantity:g} ÷ {base:g}）≈ {answer}。")
        _guess(f"猜一猜 · {description}会摄入多少{name}？", f"{scenario}会摄入多少{name}？", options,
               answer, explanation, label.name)
        return

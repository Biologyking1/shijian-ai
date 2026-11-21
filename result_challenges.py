"""Optional one-tap questions about the current label or published tea recipes."""

from hashlib import sha256
from html import escape
from math import isfinite

import streamlit as st

import nutrition


def _guess(title, question, options, answer, explanation, context):
    # A new label or recipe must never inherit an answer to a different question.
    identity = repr((context, question, options, answer, explanation)).encode()
    key = "result_guess_" + sha256(identity).hexdigest()[:20]
    with st.container(key="result_challenge"):
        with st.expander(title, icon=":material/lightbulb:"):
            pick = st.radio(question, options, index=None, horizontal=True, key=key)
            if pick is not None:
                feedback = "猜中了！" if pick == answer else "来对一下答案。"
                st.html(f'<div class="guess-reveal" role="status"><strong>{feedback}{escape(answer)}</strong>'
                        f'<p>{escape(explanation)}</p></div>')


def _amount(value):
    return f"{value:.3f}".rstrip("0").rstrip(".")


def portion_challenge(label, focus, reference):
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


def sweetness_challenge(selected, variants):
    current = selected.get("kcal")
    others = [v for v in variants if v["sugar"] != selected["sugar"]]
    if not others:
        return
    other = next((v for v in others if v["sugar"] == "标准糖"), others[0])
    delta = current - other["kcal"]
    answer = "能量相同" if delta == 0 else ("能量更低" if delta < 0 else "能量更高")
    prompt = f"同一杯型和温度，从「{other['sugar']}」换成「{selected['sugar']}」，每杯能量会怎样？"
    explanation = (f"「{other['sugar']}」每杯 {other['kcal']:g} kcal，"
                   f"「{selected['sugar']}」每杯 {current:g} kcal，相差 {abs(delta):g} kcal。")
    _guess("猜一猜 · 换个甜度，每杯能量怎么变？", prompt, ["能量更低", "能量相同", "能量更高"],
           answer, explanation, (selected.get("brand"), selected.get("name"), selected.get("size"),
                                 selected.get("temp"), selected.get("source")))

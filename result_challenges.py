"""Optional one-tap questions about the current label or published tea recipes."""

from hashlib import sha256
from html import escape

import streamlit as st


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

"""Two-candidate summaries for the existing shopping and tea decision models."""

from html import escape

import streamlit as st

from nutrition import NUTRIENTS, portion_reference, scale_nutrients
from shopping import DIMENSIONS, STATUS


def choose_pair(names, key, *, categories=None):
    """Select distinct items, optionally requiring distinct categories (or brands)."""
    if len(names) == 2:
        return 0, 1
    with st.expander("更换并排对照的两款"):
        left_col, right_col = st.columns(2)

        def option(i):
            return f"{i + 1}. {names[i]}"

        left = left_col.selectbox("左侧候选", range(len(names)), format_func=option, key=key + ".left")
        others = [i for i in range(len(names))
                  if i != left and (categories is None or categories[i] != categories[left])]
        right = right_col.selectbox("右侧候选", others, format_func=option, key=key + ".right")
    return left, right


def packaged_nutrition_rows(pair, goals):
    units = []
    states = []
    values = []
    for item in pair:
        label = item.label
        basis = portion_reference(label)
        unit = basis[1] if basis and basis[1] in {"g", "mL"} else None
        units.append(unit)
        states.append({"as_sold": "包装原状", "prepared": "冲调后"}.get(label.label_state))
        values.append(scale_nutrients(label, 100, unit) if unit else {})
    if not all(units + states) or units[0] != units[1] or states[0] != states[1]:
        descriptions = [(f"每 100 {u}" if u else "单位待核对") + " · " + (s or "状态待核对")
                        for u, s in zip(units, states)]
        return [("营养口径 · 暂不可比", descriptions)]

    rows = []
    for key in dict.fromkeys([*goals[:1], "energy"]):
        name, unit = NUTRIENTS[key]
        rows.append((f"{name} / 100 {units[0]}", [
            f"{v[key]:g} {unit}" if key in v else "待补充" for v in values]))
    return rows


def _reason(item):
    if item.blocked or item.unresolved:
        return (item.blocked or item.unresolved)[0].rstrip("。")
    missing = "、".join(DIMENSIONS[k] for k, part in item.parts.items() if part.score is None)
    if missing:
        return f"{missing}资料待补"
    return STATUS[item.status]


def pair_verdict(pair, weights, nutrition_title):
    left, right = pair
    if left.score is None or right.score is None:
        if left.status == right.status == "unscored":
            return "两款均通过已设限制。启用偏好评分后可查看匹配分。"
        return f"左侧{_reason(left)}，右侧{_reason(right)}。"
    if left.group != right.group:
        return "两款的评分口径不同，各自在同口径候选中排名。"
    if round(left.score, 1) == round(right.score, 1):
        return f"两款按当前偏好并列，匹配分均为 {left.score:.1f} 分。"
    winner, other, side = (left, right, "左侧") if left.score > right.score else (right, left, "右侧")
    driver = max(weights, key=lambda k: weights[k] * (winner.parts[k].score - other.parts[k].score))
    reason = {"nutrition": f"「{nutrition_title}」得分更高", "budget": "价格更低", "taste": "口味更符合你的喜好"}
    return f"{side}更符合当前偏好，主要因为{reason[driver]}。"


_STYLE = """
<style>
.food-pair { background:var(--guide-card); color:var(--guide-ink); border:1px solid var(--guide-line);
  border-radius:4px; overflow:hidden; font-variant-numeric:tabular-nums; }
.food-pair table { table-layout:fixed; width:100%; border-collapse:collapse; margin:0; }
.food-pair th,.food-pair td { width:50%; text-align:left; vertical-align:top;
  border:0; padding:.65rem clamp(.7rem,2vw,1.15rem); overflow-wrap:anywhere; }
.food-pair thead th { background:var(--guide-paper); color:var(--guide-ink); font-size:1.17rem;
  font-family:var(--guide-sans); font-weight:700; line-height:1.35; padding-block:1rem; }
.food-pair th+th,.food-pair td+td { border-left:1px solid var(--guide-line); }
.food-pair th small,.food-pair td small { display:block; color:var(--guide-muted); font-size:.8rem;
  font-weight:500; line-height:1.45; }
.food-pair th small { font-family:"PingFang SC","Microsoft YaHei",sans-serif; margin-top:.24rem; }
.food-pair td { border-top:1px dashed var(--guide-line); font-weight:600; line-height:1.45; }
.food-pair td small { margin-bottom:.14rem; }
.food-pair tbody tr:last-child { color:var(--guide-ink); background:#f2e6e8; }
.food-pair .food-pair-verdict { padding:.8rem clamp(.7rem,2vw,1.15rem); margin:0;
  background:var(--guide-beet); color:white; font-size:.94rem; font-weight:600; line-height:1.55; }
</style>
"""


def render_pair(pair, titles, subtitles, price_label, nutrition_rows, verdict):
    rows = [(price_label, [f"{d.label.price:g} 元" if d.label.price is not None else "待补充" for d in pair]),
            *nutrition_rows, ("口味", ["、".join(d.label.flavors) or "待补充" for d in pair]),
            ("偏好匹配", [f"{d.score:.1f} / 100" if d.score is not None else STATUS[d.status] for d in pair])]
    headers = "".join(f'<th scope="col">{escape(title)}<small>{escape(subtitle)}</small></th>'
                      for title, subtitle in zip(titles, subtitles))
    body = "".join("<tr>" + "".join(f"<td><small>{escape(label)}</small>{escape(v)}</td>" for v in values)
                   + "</tr>" for label, values in rows)
    st.html(f'{_STYLE}<div class="food-pair"><table aria-label="两款候选并排对照">'
            f'<thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>'
            f'<p class="food-pair-verdict">{escape(verdict)}</p></div>')

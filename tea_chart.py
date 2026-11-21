"""Display documented tea recipes on a shared, per-cup energy scale."""

from html import escape
from math import ceil, floor, isfinite, log10

import streamlit as st


def _group_key(record):
    fields = ("brand", "name", "kind", "region", "size", "temp", "scope", "source")
    required = [record.get(field) for field in fields]
    if (not all(required) or not isinstance(record.get("toppings"), list)
            or record.get("user_record") or record.get("from_receipt")):
        return None
    if any(word in str(record.get(field) or "") for field in ("size", "temp", "sugar")
           for word in ("未列", "未披露", "未说明", "未知")):
        return None
    # The public calculator can distinguish a tea or milk base even for the same menu item.
    recipe = tuple(sorted((k, v) for k, v in (record.get("chagee_recipe") or {}).items() if k != "sugar"))
    return (*required, record.get("value_type"), tuple(sorted(record["toppings"])), recipe)


def sweetness_variants(selected, records):
    """Return catalog rows only. A DIY change to published energy disconnects the chart."""
    group = _group_key(selected)
    if group is None or "能量" in (selected.get("personal_fields") or []):
        return []
    matches = {}
    for row in records:
        sugar = row.get("sugar")
        if sugar and _group_key(row) == group:
            if sugar in matches and matches[sugar].get("kcal") != row.get("kcal"):
                return []
            matches.setdefault(sugar, row)
    own = matches.get(selected.get("sugar"))
    if len(matches) < 2 or own is None or own.get("kcal") != selected.get("kcal"):
        return []
    # The brand lists its sweetening options from standard to least sweet.
    ordered = list(reversed((selected.get("chagee_options") or {}).get("sugar") or []))
    return [matches[sugar] for sugar in dict.fromkeys([*ordered, *matches]) if sugar in matches]


def _number(value):
    return type(value) in (int, float) and isfinite(value) and value >= 0


def _axis_ceiling(maximum):
    if maximum <= 0:
        return 1
    magnitude = 10 ** floor(log10(maximum))
    step = magnitude / 2
    return ceil(maximum / step) * step


_CHART_STYLE = """
<style>
.tea-energy {background:#faf8ef;color:#193c30;border:1px solid #d8dfd1;border-radius:18px;
  padding:clamp(1rem,3vw,1.55rem);margin:0;font:inherit;box-sizing:border-box}
.tea-energy h3 {font:inherit;font-size:1.15rem;font-weight:700;color:#173d30;margin:0;padding:0}
.tea-energy .tea-scale-caption,.tea-energy figcaption {font-size:.88rem;color:#496052;line-height:1.6}
.tea-energy .tea-scale-caption {margin:.18rem 0 1rem}
.tea-energy .tea-bar-list {list-style:none;margin:0;padding:0}
.tea-energy .tea-bar-row,.tea-energy .tea-axis {display:grid;grid-template-columns:6.4em minmax(0,1fr) 4em;
  align-items:center;column-gap:.7rem;list-style:none;padding:0;margin:.65rem 0;font-size:.9rem}
.tea-energy .tea-bar-name {line-height:1.35;overflow-wrap:anywhere}
.tea-energy .tea-bar-name small {display:block;font-weight:400;color:#506353}
.tea-energy .tea-active {font-weight:750}
.tea-energy .tea-track {display:block;height:.82rem;background:#e5e7dc;border-radius:0 5px 5px 0;
  border-left:1px solid #698172;overflow:hidden;box-sizing:border-box}
.tea-energy .tea-fill {display:block;height:100%;background:#a4b59d;border-radius:0 4px 4px 0}
.tea-energy .tea-active .tea-fill {background:#245943}
.tea-energy .tea-amount {text-align:right;font-variant-numeric:tabular-nums}
.tea-energy .tea-axis {margin-top:.24rem;color:#526658;font-variant-numeric:tabular-nums;font-size:.8rem;
  grid-template-columns:7.2em minmax(0,1fr) 4.5em}
.tea-energy .tea-ticks {grid-column:2;display:flex;justify-content:space-between;border-top:1px solid #bac8b9;
  padding-top:.18rem}
.tea-energy figcaption {margin-top:.9rem;border-top:1px solid #dce1d4;padding-top:.75rem}
.tea-energy figcaption strong {color:#204e39}
@media(max-width:500px){.tea-energy .tea-bar-row,.tea-energy .tea-axis{column-gap:.45rem}}
</style>
"""


def render_energy_chart(selected, variants):
    values = [r["kcal"] for r in variants if _number(r.get("kcal"))]
    if len(values) < 2:
        return
    ceiling = _axis_ceiling(max(values))
    different_dates = len({row.get("date") for row in variants}) > 1
    bars = []
    for row in variants:
        value = row.get("kcal")
        current = row["sugar"] == selected.get("sugar")
        label = escape(row["sugar"])
        if different_dates:
            label += f'<small>{escape(str(row.get("date") or "日期待核对"))}</small>'
        amount = f"{value:g}" if _number(value) else "未披露"
        width = 100 * value / ceiling if _number(value) else None
        track = (f'<span class="tea-fill" style="width:{width:.6f}%"></span>' if width is not None else "")
        bars.append(
            f'<li class="tea-bar-row{" tea-active" if current else ""}">'
            f'<span class="tea-bar-name">{"✓ " if current else ""}{label}</span>'
            f'<span class="tea-track" aria-hidden="true">{track}</span><span class="tea-amount">{amount}</span></li>'
        )
    reference = next((r for r in variants if r["sugar"] == "标准糖" and _number(r.get("kcal"))), None)
    caption = ""
    if reference and _number(selected.get("kcal")):
        delta = selected["kcal"] - reference["kcal"]
        if selected["sugar"] == "标准糖":
            description = f"当前为标准糖参考配方，每杯 {reference['kcal']:g} kcal，差值 0 kcal。"
        elif delta == 0:
            description = f"与标准糖（{reference['kcal']:g} kcal/杯）相同，差值 0 kcal。"
        else:
            direction = "少" if delta < 0 else "多"
            description = (f'{escape(selected["sugar"])}比标准糖（{reference["kcal"]:g} kcal/杯）'
                           f'每杯<strong>{direction} {abs(delta):g} kcal</strong>。')
        caption = f"<figcaption>{description}</figcaption>"
    basis = escape(selected.get("value_type") or "参考值")
    st.html(f"""{_CHART_STYLE}
    <figure class="tea-energy" aria-label="同配方不同甜度的每杯能量">
      <h3>甜度与每杯能量</h3><p class="tea-scale-caption">{escape(selected['size'])} ·
      {escape(selected['temp'])} · {basis}（kcal/杯）</p>
      <ul class="tea-bar-list">{"".join(bars)}</ul>
      <div class="tea-axis" aria-hidden="true"><div class="tea-ticks"><span>0</span>
      <span>{ceiling / 2:g}</span><span>{ceiling:g}</span></div></div>{caption}</figure>""")

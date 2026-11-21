"""Shared visual components for the food guide."""

def portion_html(amount, unit, package_size, scaled):
    symbol = {"mL": "mL", "g": "g", "份": "份"}[unit]
    figure = ""
    note = ""
    if package_size and package_size > 0:
        fraction = amount / package_size
        level = min(100, max(0, fraction * 100))
        style = "liquid" if unit == "mL" else "packet"
        figure = (f'<span class="guide-vessel {style}" aria-hidden="true">'
                  f'<i style="height:{level:.3f}%"></i></span>')
        note = f'<small>占整包的 {fraction:.0%} · 净含量 {package_size:g} {symbol}</small>'
    metrics = []
    for key, label, display_unit in (("carbs", "碳水化合物", "g"), ("sugar", "糖", "g"), ("energy", "能量", "kJ")):
        if key in scaled:
            value = scaled[key]
            display = "&lt;0.001" if 0 < value < 0.001 else f"{value:.3f}".rstrip("0").rstrip(".")
            metrics.append(f'<div><dt>{label}</dt><dd>{display}<small> {display_unit}</small></dd></div>')
        elif key == "sugar":
            metrics.append('<div><dt>糖</dt><dd class="guide-missing">数值待补</dd></div>')
    return ('<section class="guide-portion" aria-label="本次摄入量"><div class="guide-portion-dose">'
            + figure + f'<div><span>实际食用量</span><strong>{amount:g} <small>{symbol}</small></strong>{note}</div>'
            + '</div><dl>' + "".join(metrics) + '</dl></section>')

"""Read recipe-specific values from CHAGEE's public mainland ordering calculator."""

from datetime import datetime, timedelta, timezone
from math import isfinite

import httpx
import streamlit as st


SOURCE = "https://qmproductcomput.bwcj.com/"
BRAND = "霸王茶姬"
FIELDS = {
    "size": "productSpec",
    "sugar": "productBrix",
    "temp": "productTemperature",
    "bubble": "productBubble",
    "extra": "productExtra",
    "tea": "teaDregs",
    "milk": "milkDregs",
}
METRICS = {
    "kcal": "productQuantity",
    "protein": "productProtein",
    "carbs": "productCarbohydrate",
    "fat": "productFat",
    "caffeine": "productCaffeine",
    "trans_fat": "tfa",
}
CATEGORIES = {"原叶鲜奶茶": "鲜奶茶", "青云雪顶集": "奶盖茶", "活力轻果茶": "果茶", "远山鲜沏篇": "纯茶"}


def _value(raw):
    if isinstance(raw, bool):
        return None
    try:
        number = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if isfinite(number) and 0 <= number <= 1_000_000 else None


def _display_options(data):
    result = {}
    for key, field in FIELDS.items():
        raw = data.get(field)
        result[key] = (
            list(dict.fromkeys(v.strip() for v in raw.split(",") if v.strip())) if isinstance(raw, str) else []
        )
    return result


def read_recipe(client, name, selected=None):
    """Ignore a fallback product or recipe whenever it differs from the requested one."""
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        return None
    name = name.strip()
    params = {"productName": name}
    wanted = selected or {}
    for key, value in wanted.items():
        if key not in FIELDS or not isinstance(value, str):
            return None
        params[FIELDS[key]] = value
    endpoint = SOURCE + "api/product/"
    response = client.post(endpoint + "newProductDetail", json=params)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or str(body.get("code")) != "1000":
        return None
    raw = body.get("data")
    if not isinstance(raw, dict) or str(raw.get("productName", "")).strip() != name:
        return None
    recipe = {key: str(raw.get(field) or "").strip() for key, field in FIELDS.items()}
    if any(recipe[key] != value for key, value in wanted.items()):
        return None
    if not all(recipe[k] for k in ("size", "sugar", "temp")):
        return None
    option_response = client.post(endpoint + "space", params={"productName": name})
    option_response.raise_for_status()
    option_body = option_response.json()
    options = (
        _display_options(option_body["data"])
        if (
            isinstance(option_body, dict)
            and str(option_body.get("code")) == "1000"
            and isinstance(option_body.get("data"), dict)
        )
        else {}
    )
    grade = raw.get("greenGrade")
    return {
        "brand": BRAND,
        "name": name,
        "kind": CATEGORIES.get(raw.get("productType"), "其他"),
        **{k: recipe[k] for k in ("size", "sugar", "temp")},
        "region": "中国大陆",
        "scope": "品牌健康计算器" + "".join(" · " + recipe[k] for k in ("tea", "milk") if recipe[k]),
        "toppings": [recipe[k] for k in ("bubble", "extra") if recipe[k]],
        "chagee_options": options,
        "chagee_recipe": recipe,
        "date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
        "source": SOURCE,
        "grade_source": SOURCE,
        "source_label": "霸王茶姬健康计算器 · 中国大陆 · 每杯参考值",
        "grade": grade if grade in ("A", "B", "C", "D") else None,
        "grade_scheme": "霸王茶姬中国大陆健康计算器「营养选择」",
        **{key: _value(raw.get(field)) for key, field in METRICS.items()},
    }


@st.cache_data(ttl=3600, max_entries=256, show_spinner=False)
def _cached_recipe(name, selected):
    # The public service receives the menu item and recipe only.
    with httpx.Client(timeout=httpx.Timeout(6, connect=3)) as client:
        return read_recipe(client, name, dict(selected))


def recent_recipe(name, selected=None):
    try:
        return _cached_recipe(name, tuple(sorted((selected or {}).items())))
    except (httpx.HTTPError, ValueError):
        return None


def live_variant(base, changed):
    if not (
        base.get("chagee_recipe")
        and base.get("brand") == changed.get("brand") == BRAND
        and base.get("name") == changed.get("name")
        and base.get("region") == changed.get("region")
        and base.get("scope") == changed.get("scope")
    ):
        return None
    recipe = dict(base["chagee_recipe"])
    if sorted(changed.get("toppings") or []) != sorted(base.get("toppings") or []):
        # The calculator has separate fields for bubbles and extras. Only accept unambiguous public choices.
        options = base.get("chagee_options") or {}
        recipe.update(bubble="", extra="")
        for topping in changed.get("toppings") or []:
            slots = [k for k in ("bubble", "extra") if topping in options.get(k, [])]
            if len(slots) != 1 or recipe[slots[0]]:
                return None
            recipe[slots[0]] = topping
    for key in ("size", "sugar", "temp"):
        value = changed.get(key)
        if not value or value not in base.get("chagee_options", {}).get(key, []):
            return None
        recipe[key] = value
    return recent_recipe(base["name"], recipe)

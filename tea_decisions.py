"""Fresh-tea recipe editing and comparisons for the current Streamlit session."""

from hashlib import sha256
import json
from uuid import uuid4

import streamlit as st

from comparison_cards import choose_pair, pair_verdict, render_pair
from label_knowledge import watch_alerts
from nutrition import FOCUS, NUTRIENTS, label_from_payload
from shopping import DIMENSIONS, STATUS, Part, active_weights, default_profile, evaluate


KINDS = ["鲜奶茶", "纯茶", "果茶", "奶盖茶", "珍珠奶茶", "其他"]
SPEC = ("brand", "name", "kind", "size", "sugar", "temp", "region", "scope")
PROFILE, ENERGY, GRADE = "共享偏好的营养目标", "每杯能量", "同体系的已发布等级"
BRAND, KIND = "同品牌 · 不同品类", "同品类 · 不同品牌"
GRADES = ["A", "B", "C", "D"]


def spec_key(order):
    return (*[str(order.get(k) or "").strip() for k in SPEC],
            tuple(sorted(str(x).strip() for x in order.get("toppings") or [])))


def _token(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def matching_recipe(base, changed, catalogue):
    """Only the same recipe in the same market may supply facts to an edited cup."""
    target = spec_key(changed)
    if target == spec_key(base):
        return base
    if base.get("from_receipt"):
        annotated = {**base, **{k: changed.get(k) for k in ("kind", "region") if not base.get(k)}}
        if target == spec_key(annotated):
            return base
    if not (changed.get("region") or changed.get("scope")):
        return {}
    return next((r for r in catalogue if spec_key(r) == target), {})


def extra_only(base, order):
    old, new = spec_key(base), spec_key(order)
    return old[:-1] == new[:-1] and set(old[-1]) < set(new[-1])


def published_grade(order):
    if (order.get("grade") in GRADES and order.get("grade_scheme")
            and (order.get("grade_source") or order.get("source") or order.get("grade_note") or order.get("source_label"))):
        return order["grade"]
    return None


def per_100_ml(order):
    """Keep cup entries intact; compute densities only with a known drink volume."""
    densities = {}
    for field, value in (order.get("per100") or {}).items():
        key = {"total_sugar": "sugar", "kcal": "energy"}.get(field, field)
        if key in NUTRIENTS and value is not None:
            densities[key] = value * 4.184 if field == "kcal" else value
    densities.update(order.get("nutrients_per100ml") or {})
    volume = order.get("volume")
    if volume and volume > 0:
        for key in NUTRIENTS:
            field = {"sugar": "total_sugar", "energy": "kcal"}.get(key, key)
            factor = 4.184 if key == "energy" else 1
            if order.get(field) is not None:
                densities.setdefault(key, order[field] * factor * 100 / volume)
    return densities


def yuan_price(order):
    currency = str(order.get("currency") or "").strip().upper()
    if currency:
        return order.get("price") if currency in {"CNY", "RMB", "人民币"} else None
    # A bare local menu amount from another market has no known RMB value.
    if order.get("region") and "大陆" not in str(order["region"]) and "内地" not in str(order["region"]):
        return None
    return order.get("price")


def nutrition_basis(order, method, profile):
    uses_cup_data = method == ENERGY or (method == PROFILE and {"energy", "sugar"}.intersection(profile.get("goals", [])))
    if not uses_cup_data or not profile.get("weights", {}).get("nutrition"):
        return "当前评分口径"
    return "最高标示值" if order.get("value_type") == "最高标示值" else "标称值或核对值"


def _label(order):
    # Toppings can establish presence, while a short topping list cannot establish absence.
    ingredients = order.get("ingredients") or ""
    if isinstance(ingredients, list):
        ingredients = "、".join(ingredients)
    toppings = "、".join(order.get("toppings") or [])
    return label_from_payload(dict(
        name=order.get("name"), category="drink", label_state="prepared", basis="per_100_ml",
        ingredients="、".join(x for x in (ingredients, toppings) if x),
        unreadable="" if order.get("ingredients_complete") and ingredients.strip() else "配料不完整",
        allergen_text=order.get("allergen_text", ""), nutrients=per_100_ml(order),
        price=yuan_price(order), flavors=order.get("flavors", []),
    ))


def compare_orders(orders, prefs, method=PROFILE, energy_ref=200.0, scheme=None):
    """Rank eligible cups only. A grade can be compared within one named scheme."""
    profile = {**default_profile(), **prefs}
    if method != PROFILE:
        profile = {**profile, "goals": ["energy"]}
    weights = active_weights(profile)
    decisions = []
    for order in orders:
        decision = evaluate(_label(order), profile)
        decision.group = nutrition_basis(order, method, profile)
        if method != PROFILE and "nutrition" in weights:
            if method == ENERGY:
                value = order.get("kcal")
                part = (Part(None, "请补这份配方已公布的每杯千卡数。") if value is None else
                        Part(100 * energy_ref / (energy_ref + value),
                             f"每杯 {value:g} kcal，个人参考值 {energy_ref:g} kcal。"))
            else:
                grade = published_grade(order)
                part = (Part((3 - GRADES.index(grade)) * 100 / 3, f"{scheme} · {grade} 级。")
                        if scheme and grade and order.get("grade_scheme") == scheme else
                        Part(None, "请补与本组同一体系、同一配方的已发布等级及出处。"))
            decision.parts["nutrition"] = part
            if not (decision.blocked or decision.unresolved):
                scores = [decision.parts[k].score for k in weights]
                if None in scores:
                    decision.score, decision.status = None, "incomplete"
                else:
                    decision.score = sum(weights[k] * decision.parts[k].score for k in weights) / sum(weights.values())
                    decision.status = "eligible"
        decisions.append(decision)
    for basis in {d.group for d in decisions}:
        scored = sorted((d for d in decisions if d.group == basis and d.score is not None),
                        key=lambda d: d.score, reverse=True)
        last, rank = None, 0
        for pos, decision in enumerate(scored, 1):
            rounded = round(decision.score, 1)
            if rounded != last:
                rank, last = pos, rounded
            decision.rank = rank
    return decisions


def comparison_group(orders, mode, value):
    group, distinct = ("brand", "kind") if mode == BRAND else ("kind", "brand")
    group_orders = [o for o in orders if o.get(group) == value and o.get(distinct)]
    return group_orders, len({o[distinct] for o in group_orders}) >= 2


def _unique(values):
    return list(dict.fromkeys(v for v in values if v))


def _name(order):
    return " · ".join(str(v) for v in (order.get("brand"), order.get("name"), order.get("region"),
                                      order.get("size"), order.get("sugar"), order.get("temp"),
                                      "＋".join(order.get("toppings") or [])) if v)


def _metric(value, unit):
    return "待补" if value is None else f"{value:g} {unit}"


def _menu_label(order):
    details = " ｜ ".join(str(v) for v in (order.get("scope"), order.get("date")) if v)
    return " ｜ ".join(v for v in (_name(order), details) if v)


def _choose(label, value, options, key):
    options = _unique([value, *options])
    return st.selectbox(label, options, index=0 if value else None, placeholder="选择或输入后按回车",
                        accept_new_options=True, key=key) or ""


def _reference(records, prefix, initial=None):
    # Store the active starting point outside widget state so changing pages keeps the choice.
    if initial:
        st.session_state[prefix + ".initial"] = dict(initial)
    extra = st.session_state.get(prefix + ".initial")
    choices = {"manual": {}}
    for record in records:
        choices[_token(record)] = record
    if extra:
        choices[_token(extra)] = extra
    picker = prefix + ".reference"
    first = next((key for key in choices if key != "manual"), "manual")
    remembered = st.session_state.get(prefix + ".reference_saved", first)
    if not initial:
        st.session_state.pop(prefix + ".initial_signature", None)
    elif st.session_state.get(prefix + ".initial_signature") != _token(initial):
        remembered = _token(initial)
        st.session_state[picker] = remembered
        st.session_state[prefix + ".initial_signature"] = remembered
    if st.session_state.get(picker, remembered) not in choices:
        st.session_state[picker] = "manual"
    if picker not in st.session_state:
        st.session_state[picker] = remembered if remembered in choices else "manual"
    selected = st.selectbox("从哪份配方开始？", choices.keys(), key=picker,
                            format_func=lambda k: _menu_label(choices[k]) if k != "manual" else "手工录入其他饮品")
    st.session_state[prefix + ".reference_saved"] = selected
    return choices[selected], prefix + "." + selected


def _spec_inputs(base, records, prefix):
    if base.get("brand") and base.get("name"):
        brand, name, kind = base["brand"], base["name"], base.get("kind") or ""
        if not kind:
            kind = _choose("饮品品类", "", [r.get("kind") for r in records] + KINDS, prefix + ".kind")
    else:
        brand = _choose("品牌", base.get("brand"), [r.get("brand") for r in records], prefix + ".brand")
        name = st.text_input("饮品名称", value=base.get("name") or "", max_chars=100, key=prefix + ".name").strip()
        kind = _choose("饮品品类", base.get("kind"), [r.get("kind") for r in records] + KINDS, prefix + ".kind")
    region = st.text_input("本杯适用地区或门店", value=base.get("region") or "", key=prefix + ".region",
                           max_chars=100, placeholder="例如：中国大陆 · 上海")
    related = [r for r in records if r.get("brand") == brand and r.get("name") == name and r.get("region", "") == region]
    changed = dict(brand=brand, name=name, kind=kind, region=region.strip(), scope=base.get("scope") or "")
    if changed["region"] != (base.get("region") or "") and not (base.get("from_receipt") and not base.get("region")):
        changed["scope"] = ""
    st.caption("选项来自该地区这款饮品的资料。也可输入门店提供的选项或自己的设想，实际供应请核对点单页。")
    official = (base.get("chagee_options") or {}) if region == base.get("region") else {}
    for col, (key, label) in zip(st.columns(3), [("size", "杯型"), ("sugar", "甜度"), ("temp", "温度 / 冰量")]):
        with col:
            options = [*official.get(key, []), *(r.get(key) for r in related)]
            changed[key] = _choose(label, base.get(key), options, prefix + "." + key)
    saved_extras = st.session_state.get("tea.personal_toppings", {}).get((brand, region), [])
    extras = _unique([*(base.get("toppings") or []), *official.get("bubble", []), *official.get("extra", []),
                      *(t for r in related for t in r.get("toppings") or []),
                      *(t for r in related for t in r.get("topping_options") or []), *saved_extras])
    if saved_extras:
        st.caption("你在该品牌、该地区选过：" + "、".join(saved_extras) + "。能否加到本杯请核对当日菜单。")
    changed["toppings"] = st.multiselect("额外加料（保留饮品原有配方）", extras, default=base.get("toppings") or [],
                                         accept_new_options=True, placeholder="可输入自选加料后按回车",
                                         key=prefix + ".toppings")
    for link in _unique(r.get("toppings_source") for r in related):
        _cite("查看门店加料资料", link)
    return changed


def _number(label, value, key, min_value=0.0):
    default = None if value is None or key in st.session_state else float(value)
    return st.number_input(label, min_value=min_value, value=default,
                           step=0.1, key=key, placeholder="未公布或未知时留空")


def _facts(base, changed, records, prefs, prefix):
    identity = spec_key(changed)
    key = prefix + "." + _token(identity)
    source = matching_recipe(base, changed, records)
    variants = st.session_state.setdefault("tea.live_variants", {})
    if not source and base.get("chagee_options"):
        source = variants.get(identity, {})
        if not source and st.button("向霸王茶姬查询这份改配", key=key + ".lookup"):
            from tea_chagee import live_variant

            with st.spinner("正在查询这份配方的官方营养资料…"):
                result = live_variant(base, changed)
            if result:
                source = result
                variants[identity] = source
                for field in ("volume", "kcal", "total_sugar"):
                    if st.session_state.get(key + "." + field) is None and source.get(field) is not None:
                        st.session_state[key + "." + field] = float(source[field])
                st.success("已取得与当前规格相符的官方资料。")
            else:
                st.warning("本次没有取得对应规格的官方资料。可以稍后重试，或补录门店标示。")
    order = {**source, **changed, "scope": source.get("scope") or changed.get("scope") or ""}
    price = yuan_price(source)
    if base and spec_key(base) != spec_key(changed) and st.checkbox("按门店标价与改配差价试算", key=key + ".adjust"):
        left, right = st.columns(2)
        with left:
            original = _number("原配方实际总价（人民币元）", yuan_price(base), key + ".original")
        delta = right.number_input("改杯型、换料、加料的合计差价（元，可为负数）",
                                   value=None, step=0.1, key=key + ".delta", placeholder="按门店价目填写")
        order["price"] = None
        if original is not None and delta is not None:
            if original + delta >= 0:
                order["price"] = round(original + delta, 2)
                st.caption(f"本杯菜单价合计 {order['price']:.2f} 元。")
            else:
                st.warning("扣减金额超过原价，请核对差价。")
    else:
        order["price"] = _number("这份配方的实际总价（人民币元，含加料）", price, key + ".price")
    order["currency"] = "CNY"
    st.caption("价格取本杯所在门店和地区。外币菜单请留空，或填你确认的人民币结算金额。")
    if source.get("source"):
        st.caption("匹配资料：" + str(source.get("scope") or source.get("region") or "当前配方"))
        _cite("查看配方资料", source["source"])
    elif source.get("source_label"):
        st.caption("资料来源：" + str(source["source_label"]))
    elif spec_key(base) != spec_key(changed) and base:
        st.caption("这份改配没有匹配到同地区的完整配方资料。请补充门店公布的本杯数据。")
    with st.expander("补充本杯营养、口味和门店用料"):
        st.caption("请抄录适用于目前地区、杯型、甜度、温度和加料的数值。修改值会标为个人补录。")
        order["volume"] = _number("资料标示的实际饮品体积（mL）", source.get("volume"), key + ".volume", 0.1)
        for field, label in (("kcal", "本配方公布的能量（kcal / 杯）"), ("total_sugar", "本配方公布的总糖（g / 杯）")):
            density = (source.get("per100") or {}).get(field)
            if source.get(field) is None and density is not None and order["volume"]:
                order[field] = density * order["volume"] / 100
                st.caption(f"{label} · 按每 100 mL 标示与本杯体积折算为 {order[field]:g}")
            else:
                order[field] = _number(label, source.get(field), key + "." + field)
        if not published_grade(source):
            grade = st.selectbox("本配方已发布的营养等级", GRADES, index=None, key=key + ".grade")
            if grade:
                scheme = st.text_input("分级体系（与出处名称一致）", key=key + ".scheme", placeholder="例如：上海试点")
                note = st.text_input("等级出处（发布方与页码、链接或门店公示日期）", key=key + ".grade_note")
                if scheme.strip() and note.strip():
                    order.update(grade=grade, grade_note=note.strip(), grade_scheme=scheme.strip(), grade_source=note.strip())
                else:
                    st.caption("填入体系与出处后，等级才能进入比较。")
        flavors = source.get("flavors") or []
        order["flavors"] = st.multiselect("本杯口味（按实际体验或菜单填写）", _unique([*flavors, *prefs.get("flavors", [])]),
                                          default=flavors, accept_new_options=True, key=key + ".flavors",
                                          placeholder="例如：原味、微甜")
        densities = dict(source.get("nutrients_per100ml") or {})
        for nutrient in prefs.get("goals", []):
            if nutrient not in NUTRIENTS:
                continue
            title, unit = NUTRIENTS[nutrient]
            derived = per_100_ml({**order, "nutrients_per100ml": {}}).get(nutrient)
            if nutrient not in densities and derived is not None:
                st.caption(f"本配方营养密度 · {title} {derived:g} {unit}/100 mL")
                continue
            number = _number(f"门店标示的{title}（{unit} / 100 mL）", densities.get(nutrient), key + ".den." + nutrient)
            if number is not None:
                densities[nutrient] = number
            else:
                densities.pop(nutrient, None)
        order["nutrients_per100ml"] = densities
        ingredients = source.get("ingredients") or ""
        order["ingredients"] = st.text_area("这份配方的配料（门店原文）",
                                             value="、".join(ingredients) if isinstance(ingredients, list) else ingredients,
                                             key=key + ".ingredients")
        order["ingredients_complete"] = st.checkbox("已向门店核对本杯全部配料和加料", value=bool(source.get("ingredients_complete")),
                                                    key=key + ".complete")
        order["allergen_text"] = st.text_area("门店关于致敏物质和共用设备的说明", value=source.get("allergen_text") or "",
                                               key=key + ".allergens")
    changed_facts = [label for field, label in (("volume", "体积"), ("kcal", "能量"), ("total_sugar", "总糖"))
                     if order.get(field) != source.get(field)]
    if densities != (source.get("nutrients_per100ml") or {}):
        changed_facts.append("每 100 mL 营养值")
    order["personal_fields"] = _unique([*(source.get("personal_fields") or []), *changed_facts])
    if not published_grade(order):
        order["grade"] = None
        if not order.get("estimated_grade"):
            order["grade_scheme"] = None
    if extra_only(base, order) and (base.get("kcal") is not None or base.get("total_sugar") is not None):
        with st.expander("按新增小料的份量估算"):
            if st.checkbox("门店确认原饮品份量和做法不变，只额外加入这些小料", key=key + ".add_only"):
                st.caption("按门店公布的本次新增小料实际份数填写。若门店会减少原饮品或替换原料，需使用改配后的整杯资料。")
                for field, label, unit in (("kcal", "能量", "kcal"), ("total_sugar", "总糖", "g")):
                    if order.get(field) is None and base.get(field) is not None:
                        added = _number(f"新增小料的合计{label}（{unit}）", None, key + ".extra." + field)
                        if added is not None:
                            order["estimated_" + field] = base[field] + added
                            st.caption(f"原杯 {base[field]:g} + 新增小料 {added:g} = 估算 {order['estimated_' + field]:g} {unit}/杯")
    return order


def _cite(label, source, key=None):
    if isinstance(source, str) and source.startswith(("https://", "http://")):
        st.link_button(label, source, key=key)
    elif source:
        st.caption(str(source))


def _tea_reason(reason):
    return reason.replace("单包", "单杯").replace("包装", "门店资料").replace("厂家", "门店")


def _preview(base, order, flags, prefs, records):
    from tea_chart import render_energy_chart, sweetness_variants

    changed = bool(base) and spec_key(base) != spec_key(order)
    st.markdown("**这杯的配方结果**")
    fields = [("每杯能量", "kcal", "kcal"), ("每杯总糖", "total_sugar", "g"), ("单杯总价", "price", "元")]
    for col, (label, field, unit) in zip(st.columns(3), fields):
        actual, old = order.get(field), base.get(field)
        if field == "price":
            old = yuan_price(base)
        delta = f"{actual-old:+g} {unit}" if changed and actual is not None and old is not None else None
        if field != "price" and order.get("value_type"):
            label += f"（{order['value_type']}）"
        col.metric(label, _metric(actual, unit), delta=delta, delta_color="off")
    render_energy_chart(order, sweetness_variants(order, records))
    if order.get("personal_fields"):
        st.caption("个人补录或换算 · " + "、".join(order["personal_fields"]))
    for key, label, unit in (("estimated_kcal", "能量", "kcal"), ("estimated_total_sugar", "总糖", "g")):
        if order.get(key) is not None:
            st.caption(f"按新增小料与原杯相加估算 · {label} {order[key]:g} {unit}/杯。综合评分使用整杯核对值。")
    grade = published_grade(order)
    if grade:
        st.write(f"已公布等级 · {grade} 级（{order['grade_scheme']}）")
        _cite("分级出处", order.get("grade_source") or order.get("grade_note") or order.get("source") or order.get("source_label"))
    elif order.get("estimated_grade") in GRADES:
        st.write(f"按已核对的指标推算 · {order['estimated_grade']} 级（{order.get('grade_scheme') or '营养选择'}）")
        st.caption((order.get("grade_reason") or "") + " 已发布等级评分只使用品牌明确标示的等级。")
        _cite("推算依据", order.get("grade_source"))
    else:
        st.caption("营养等级尚无可核对的本配方评级。")
    if changed:
        st.caption("原配方：" + _name(base) + "。原配方每杯能量 " + _metric(base.get("kcal"), "kcal")
                   + "，每杯总糖 " + _metric(base.get("total_sugar"), "g") + "。")
    focused = _unique(k for flag in sorted(flags or []) for k in FOCUS.get(flag, ()))
    densities = per_100_ml(order)
    if focused:
        parts = []
        for nutrient in focused:
            title, unit = NUTRIENTS[nutrient]
            cup_value = order.get("total_sugar" if nutrient == "sugar" else nutrient)
            if cup_value is not None:
                parts.append(f"{title} {cup_value:g} {unit}/杯")
            elif nutrient in densities:
                parts.append(f"{title} {densities[nutrient]:g} {unit}/100 mL")
            else:
                parts.append(f"{title}待补")
        st.caption("根据你的饮食关注项：" + "，".join(parts))
    if prefs.get("allergens") or prefs.get("diets") or prefs.get("budget") is not None:
        decision = evaluate(_label(order), {**default_profile(), **prefs})
        for reason in decision.blocked + decision.unresolved:
            st.warning(_tea_reason(reason))
    if prefs.get("watch"):
        hits = watch_alerts(_label(order), prefs)
        if hits:
            st.caption("本杯配料中有你关注的：" + "、".join(hits))


def _save(order, action, uid=None):
    item = {**order, "id": uid or uuid4().hex}
    if order.get("toppings"):
        personal = st.session_state.setdefault("tea.personal_toppings", {})
        local = (order["brand"], order.get("region") or "")
        personal[local] = _unique([*personal.get(local, []), *order["toppings"]])
    if action == "ledger":
        st.session_state["tea.last_order"] = item
        return
    cart = st.session_state.setdefault("tea.cart", [])
    if uid:
        cart[:] = [item if o["id"] == uid else o for o in cart]
    else:
        cart.append(item)


def _editor(base, records, prefs, flags, prefix, uid=None):
    changed = _spec_inputs(base, records, prefix)
    order = _facts(base, changed, records, prefs, prefix)
    _preview(base, order, flags, prefs, records)
    disabled = not all(order.get(k) for k in ("brand", "name", "kind"))
    if disabled:
        st.caption("填入品牌、饮品名称和品类后即可保存。")
    add, ledger = st.columns(2)
    if add.button("保存候选修改" if uid else "加入茶饮比较", type="primary", disabled=disabled, key=prefix + ".save"):
        _save(order, "cart", uid)
        st.success("已保存到茶饮比较清单。")
    if ledger.button("将这杯带入消费记录", disabled=disabled, key=prefix + ".ledger"):
        _save(order, "ledger")
        st.success("已选好这杯，前往消费记录核对日期和实付金额。")


def _session_catalog(records):
    live = list(st.session_state.get("tea.live_variants", {}).values())
    keys = {spec_key(r) for r in live}
    return live + [r for r in records if spec_key(r) not in keys]


def render_simulator(records, prefs, flags, initial=None):
    st.subheader("DIY 点单模拟")
    st.caption("调整杯型、甜度、冰量或加料，查看当前配方的已知营养和总价。")
    catalogue = _session_catalog(records)
    st.session_state["tea.records"] = catalogue
    base, prefix = _reference(catalogue, "tea.sim", initial)
    _editor(base, catalogue, prefs, flags, prefix)


def render_comparison(prefs, flags):
    st.subheader("按我的偏好选茶饮")
    records = st.session_state.get("tea.records")
    if records is None:
        from tea_catalog import CATALOG
        records = CATALOG
    records = _session_catalog(records)
    cart = st.session_state.setdefault("tea.cart", [])
    in_cart = {spec_key(o) for o in cart}
    available = {_token(r): r for r in records if spec_key(r) not in in_cart}
    if available:
        chosen = st.multiselect("从资料库一次加入多杯", available.keys(), format_func=lambda k: _menu_label(available[k]),
                                key="tea.compare.quick", placeholder="可选同品牌不同品类，或同品类不同品牌")
        if st.button("加入所选配方", disabled=not chosen, key="tea.compare.quick_add"):
            for record_key in chosen:
                record = available[record_key]
                _save({**record, "price": yuan_price(record), "currency": "CNY"}, "cart")
            st.rerun()
    with st.expander("手工添加、编辑或移除候选饮品", expanded=not records and not cart):
        selected = st.selectbox("要编辑哪一杯？", ["new", *[o["id"] for o in cart]],
                                format_func=lambda k: "新增一杯" if k == "new" else _name(next(o for o in cart if o["id"] == k)),
                                key="tea.compare.edit")
        if selected == "new":
            base, prefix = _reference(records, "tea.compare.new")
            _editor(base, records, prefs, flags, prefix)
        else:
            base = next(o for o in cart if o["id"] == selected)
            if st.button("移除这杯候选", key="tea.compare.remove." + selected):
                cart.remove(base)
                st.rerun()
            _editor(base, records, prefs, flags, "tea.compare.edit." + selected, selected)
    if not cart:
        st.info("加入两杯同品牌不同品类、或同品类不同品牌的饮品，即可比较。")
        return
    mode = st.radio("比较方式", [BRAND, KIND], horizontal=True, key="tea.compare.mode")
    field = "brand" if mode == BRAND else "kind"
    group = st.selectbox("比较哪个品牌？" if mode == BRAND else "比较哪个品类？",
                         _unique(o[field] for o in cart), key="tea.compare.group." + field)
    items, valid = comparison_group(cart, mode, group)
    if not valid:
        st.info("这个组还需加入另一种品类。" if mode == BRAND else "这个组还需加入另一个品牌。")
        return
    grade_default = any(published_grade(o) for o in items) and not all(o.get("kcal") is not None for o in items)
    method = st.selectbox("营养分采用哪项依据？", [ENERGY, PROFILE, GRADE], index=2 if grade_default else 0,
                          key="tea.compare.measure")
    ref, scheme = 200.0, None
    if method == ENERGY:
        ref = st.number_input("每杯能量的个人评分参考值（kcal，达到此值为 50 分）", min_value=0.1,
                              value=200.0, key="tea.compare.energy_ref")
    elif method == GRADE:
        schemes = _unique(o.get("grade_scheme") for o in items if published_grade(o))
        scheme = st.selectbox("本组采用的分级体系", schemes, index=0 if schemes else None, key="tea.compare.scheme")
    profile = {**default_profile(), **prefs}
    weights = active_weights(profile if method == PROFILE else {**profile, "goals": ["energy"]})
    bases = _unique(nutrition_basis(o, method, profile) for o in items)
    if len(bases) > 1:
        st.caption("本组同时含营养上限和标称值。请选择同一种口径比较。")
        basis = st.radio("参与本轮的营养口径", bases, horizontal=True, key="tea.compare.basis")
        items, valid = comparison_group([o for o in items if nutrition_basis(o, method, profile) == basis], mode, group)
        if not valid:
            st.info("当前口径还需要另一品类的候选。" if mode == BRAND else "当前口径还需要另一品牌的候选。")
            st.write("已选：" + "、".join(_name(o) for o in items))
            return
    st.caption("权重取自首页选购偏好。当前占比：" + ("、".join(
        f"{DIMENSIONS[k]} {v/sum(weights.values()):.0%}" for k, v in weights.items()) or "仅核对限制"))
    decisions = compare_orders(items, profile, method, ref, scheme)
    distinct_field = "kind" if mode == BRAND else "brand"
    indices = choose_pair([_name(o) for o in items], "tea.compare.pair",
                          categories=[o[distinct_field] for o in items])
    pair = [decisions[i] for i in indices]
    cups = [items[i] for i in indices]
    energies = [("最高 " if o.get("value_type") == "最高标示值" and o.get("kcal") is not None else "")
                + _metric(o.get("kcal"), "kcal") for o in cups]
    nutrition_rows = [("每杯能量", energies)]
    if method == GRADE:
        nutrition_rows.append((scheme or "发布等级", [
            published_grade(o) if scheme and o.get("grade_scheme") == scheme and published_grade(o) else "待核对"
            for o in cups]))
    subtitles = [" · ".join(str(o[k]) for k in ("brand", "kind", "size", "sugar", "temp") if o.get(k))
                 for o in cups]
    render_pair(pair, [o.get("name") or "未命名茶饮" for o in cups], subtitles, "单杯价格", nutrition_rows,
                _tea_reason(pair_verdict(pair, weights, method)))
    need_price = ("budget" in weights or profile.get("budget") is not None)
    absent = [o for o in items if (need_price and yuan_price(o) is None) or ("taste" in weights and not o.get("flavors"))]
    if absent:
        with st.form("tea.compare.fill." + _token([o["id"] for o in absent])):
            st.markdown("**补全本组的门店售价与口味**")
            updates = []
            for o in absent:
                st.caption(_name(o))
                data = {}
                if need_price and yuan_price(o) is None:
                    data["price"] = _number("这杯的实际人民币总价（含加料）", None, "tea.fill.price." + o["id"])
                    data["currency"] = "CNY"
                if "taste" in weights and not o.get("flavors"):
                    data["flavors"] = st.multiselect("这杯的实际口味", profile["flavors"], accept_new_options=True,
                                                      key="tea.fill.flavors." + o["id"], placeholder="选标签或输入实际口味")
                updates.append((o, data))
            if st.form_submit_button("保存本组资料并计算"):
                for o, data in updates:
                    o.update(data)
                st.rerun()
    with st.expander("评分规则与资料口径"):
        st.write("先检查单杯预算、过敏原和饮食限制。满足限制且所选项目都有资料的饮品，依照个人权重求平均分。"
                 "显示到小数点后一位的同分饮品并列。")
        st.write(f"价格分 = 100 × {profile['reference_price']:g} ÷（{profile['reference_price']:g} + 单杯人民币价）。"
                 "选过喜欢的口味后，命中任一项得 100 分，已填口味但均未命中得 0 分。")
        if method == ENERGY:
            st.write(f"能量分 = 100 × {ref:g} ÷（{ref:g} + 每杯 kcal）。该参考值可自行调整。")
            st.caption("营养卡仅给最高标示值时，使用该上限计算保守的能量分。实际摄入量会随制作变化。")
        elif method == GRADE:
            st.write("仅比较同一体系已发布的等级。应用将 A/B/C/D 等距映射为 100/66.7/33.3/0 分，仅用于本次偏好计算。")
        else:
            st.write("共享营养目标按每 100 mL 比较，各目标等权。越少越好的项目分数 = 100 × 参考值 ÷（实际值 + 参考值），"
                     "越多越好的项目将分子中的参考值换为实际值。")
        st.caption("每份资料只适用于所列地区和配方。价格请按该配置实际人民币金额填写。")
    ranked = sorted(zip(items, decisions), key=lambda pair: pair[1].rank or (len(items) + 1))
    st.markdown("**全部候选与评分明细**")
    for order, decision in ranked:
        with st.container(border=True):
            st.markdown(f"**{_name(order)}**")
            if decision.rank:
                st.write(f"第 {decision.rank} 名 · {decision.score:.1f} 分")
            else:
                st.write(STATUS[decision.status])
            st.caption(f"{order['kind']} · 单杯价 {_metric(yuan_price(order), '元')} · 每杯能量 {_metric(order.get('kcal'), 'kcal')}"
                       + (f" · {order['grade_scheme']} {order['grade']} 级" if published_grade(order) else " · 分级待核对"))
            if order.get("scope"):
                st.caption(order["scope"])
            if order.get("value_type"):
                st.caption("营养标示口径 · " + order["value_type"])
            _cite("查看这杯的资料出处", order.get("source") or order.get("source_label"),
                  "tea.compare.source." + order["id"])
            grade_source = order.get("grade_source") or order.get("grade_note")
            if published_grade(order) and grade_source and grade_source != order.get("source"):
                _cite("查看这杯的分级依据", grade_source, "tea.compare.grade_source." + order["id"])
            if order.get("personal_fields"):
                st.caption("个人补录或换算 · " + "、".join(order["personal_fields"]))
            for reason in decision.blocked + decision.unresolved:
                st.write(_tea_reason(reason))
            for dimension, part in decision.parts.items():
                score = "待补" if part.score is None else f"{part.score:.1f} 分"
                st.caption(f"{DIMENSIONS[dimension]} {score} · " + part.detail.replace("单包", "单杯").replace("包装", "门店"))
            if st.button("选这杯用于消费记录", key="tea.compare.pick." + order["id"]):
                _save(order, "ledger", order["id"])
                st.success("已选好这杯，前往消费记录核对后保存。")

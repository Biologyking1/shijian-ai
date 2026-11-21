"""Freshly made tea lookup and review of recipe-specific nutrition evidence."""

from hashlib import sha256
from html import escape
from math import isfinite
from unicodedata import normalize
from urllib.parse import urlsplit

import streamlit as st

import tea_catalog as catalog
from tea_chart import render_energy_chart, sweetness_variants
from tea_chagee import BRAND as LIVE_BRAND, live_variant, recent_recipe
from tea_decisions import render_comparison, render_simulator, spec_key
from tea_ledger import render_ledger
from vision import VisionError, recognize_tea


NUTRIENTS = {
    "kcal": "能量（千卡）",
    "total_sugar": "总糖（克）",
    "grade_sugar": "分级用糖（果糖、葡萄糖、蔗糖和麦芽糖之和，克）",
    "nonmilk_sugar": "非乳源性糖（克）",
    "sat_fat": "饱和脂肪（克）",
    "trans_fat": "反式脂肪（克）",
    "sodium": "钠（毫克）",
    "protein": "蛋白质（克）",
    "carbs": "碳水化合物（克）",
    "fat": "脂肪（克）",
    "caffeine": "咖啡因（毫克）",
}
GRADE_NOTE = {
    "A": "在这一分级体系中优先推荐。大杯和额外小料仍会改变整杯摄入量。",
    "B": "推荐程度仅次于 A。比较同类饮品时，可进一步看单杯糖量、能量和你的实际份量。",
    "C": "至少一项分级指标落在 C 档。可以比较同系列其他甜度的标示，或点小杯。",
    "D": "至少一项分级指标落在最低推荐档。偶尔想喝时，可选小杯，或比较其他有营养资料的配方。",
}


def _norm(value):
    return "".join(normalize("NFKC", str(value or "")).casefold().split())


def _https(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url or "")
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username)
    except ValueError:
        return False


def _numbers(record, basis, volume):
    """Keep the printed basis available even when cup volume is missing."""
    known = {
        k: v for k in NUTRIENTS if type(v := record.get(k)) in (int, float) and isfinite(v) and 0 <= v <= 1_000_000
    }
    valid_volume = type(volume) in (int, float) and isfinite(volume) and 0 < volume <= 10000
    if basis == "per_100ml":
        return ({k: v * volume / 100 for k, v in known.items()} if valid_volume else {}), known
    if basis == "per_cup":
        return known, ({k: v * 100 / volume for k, v in known.items()} if valid_volume else {})
    return {}, {}


def _configuration(record):
    extras = record.get("toppings")
    parts = [record.get(k) for k in ("size", "sugar", "temp")]
    if isinstance(extras, list) and extras:
        parts.append("加" + "、".join(extras))
    return " · ".join(str(v) for v in parts if v) or "规格见来源"


def _spec(record):
    label = f"{_configuration(record)} ｜ {record.get('scope') or record.get('region') or '适用门店待核对'}"
    if record.get("source_provider") == "boohee":
        return "薄荷健康 · " + label
    return ("已核对 · " if record.get("user_record") else "") + label


def _order_candidates(order, records):
    """Only shortlist recipes that document all the details visible on the order."""
    fields = [key for key in ("size", "sugar", "temp") if order.get(key)]
    has_toppings = isinstance(order.get("toppings"), list)
    if not (fields or has_toppings):
        return []
    return [
        index
        for index, record in enumerate(records)
        if all(_norm(record.get(key)) == _norm(order[key]) for key in fields)
        and (
            not has_toppings
            or isinstance(record.get("toppings"), list)
            and sorted(map(_norm, record["toppings"])) == sorted(map(_norm, order["toppings"]))
        )
    ]


def _open_diy(record):
    st.session_state["tea.initial_order"] = dict(record)
    st.session_state["tea.route"] = "DIY 点单"


def _catalog_pick(key="tea.catalog.pick"):
    picked = st.session_state.get(key)
    if picked:
        st.session_state["tea.brand"], st.session_state["tea.name"] = picked
        st.session_state["tea.query"] = picked
        st.session_state["tea.query.region"] = st.session_state.get("tea.catalog.region", "") if key == "tea.catalog.pick" else ""
        st.session_state.pop("tea.slip", None)


def _receipt_input(settings):
    st.caption("优先裁到杯贴上的品牌、品名、杯型和甜度，避开姓名、电话和订单号。点击识别后，照片会发送给百灵。")
    camera = st.toggle("打开摄像头拍杯贴", key="tea.camera")
    shot = st.camera_input("拍摄单杯订单标签", key="tea.shot") if camera else None
    file = st.file_uploader("上传杯贴或单杯订单照片", type=["png", "jpg", "jpeg", "webp"], key="tea.receipt.file")
    photo = shot if shot is not None else file
    fingerprint = sha256(photo.getvalue()).hexdigest() if photo is not None else None
    if fingerprint != st.session_state.get("tea.receipt.id"):
        st.session_state["tea.receipt.id"] = fingerprint
        if st.session_state.pop("tea.slip", None):
            for key in ("tea.brand", "tea.name", "tea.query"):
                st.session_state.pop(key, None)
    if shot is not None and file is not None:
        st.caption("本次使用刚拍摄的杯贴。")
    if not settings.api_key:
        st.caption("当前可直接填写品牌与品名。")
    if st.button("识别杯贴", disabled=photo is None or not settings.api_key, key="tea.scan"):
        try:
            with st.spinner("正在抄录品牌与点单规格…"):
                order = recognize_tea(photo.getvalue(), settings)
        except VisionError as exc:
            st.error(str(exc))
        else:
            st.session_state["tea.slip"] = order
            st.session_state["tea.brand"] = order.get("brand", "")
            st.session_state["tea.name"] = order.get("name", "")
            st.session_state.pop("tea.query", None)
            st.success("请对照杯贴核对品牌与完整品名，再查询对应配方。")
    if photo is not None:
        with st.expander("对照本次选择的杯贴照片"):
            st.image(photo)


def _recipe_summary(record):
    def metric(field, unit):
        value = record.get(field)
        if value is None:
            return '<span class="tea-unknown">待补</span>'
        return f'{value:g} <small>{unit}</small>'

    grade = record.get("grade") or record.get("estimated_grade")
    origin = ("个人核对的标示" if record.get("user_record") else "品牌标示") if record.get("grade") else "按指标推算"
    grade_name = escape(str(grade)) if grade in GRADE_NOTE else "待核对"
    mark = grade_name + " 级" if grade in GRADE_NOTE else grade_name
    help_text = (f"{origin} · {record.get('grade_scheme') or '营养选择'}" if grade in GRADE_NOTE
                 else "暂无可核实的等级")
    basis = record.get("value_type") or ("已核对数值" if record.get("user_record") else "参考值")
    notes = " · ".join(str(record[k]) for k in ("region", "scope", "date") if record.get(k))
    st.html(f"""
        <style>
        .tea-recipe {{background:var(--guide-card);border:1px solid var(--guide-line);border-radius:4px;
          color:var(--guide-ink);padding:clamp(1rem,3vw,1.55rem);overflow-wrap:anywhere}}
        .tea-recipe .tea-brand,.tea-recipe .tea-sub {{color:var(--guide-muted);font-size:.88rem;line-height:1.6}}
        .tea-recipe .tea-head {{display:flex;justify-content:space-between;gap:1rem;align-items:center}}
        .tea-recipe h3 {{margin:.2rem 0;padding:0;color:var(--guide-ink);font-size:clamp(1.5rem,4vw,2.2rem);line-height:1.2}}
        .tea-recipe .tea-grade {{text-align:center;background:#e3ebda;color:#25482d;min-width:4.8rem;
          padding:.46rem .65rem;border-radius:.85rem;line-height:1.4;font-size:.76rem}}
        .tea-recipe .tea-grade b {{display:block;font-size:1.55rem}}
        .tea-recipe .tea-grade[data-grade="C"],.tea-recipe .tea-grade[data-grade="D"]
          {{background:#f1e4ce;color:#66491b}}
        .tea-recipe dl {{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem;
          margin:1rem 0 .75rem;border-block:1px dashed var(--guide-line);padding:.85rem 0}}
        .tea-recipe dt {{font-size:.84rem;color:var(--guide-muted)}}
        .tea-recipe dd {{margin:.15rem 0 0;color:var(--guide-ink);font-family:var(--guide-mono);font-size:1.8rem;font-weight:700;line-height:1.24;
          font-variant-numeric:tabular-nums}}
        .tea-recipe dd small,.tea-recipe .tea-unknown {{font-size:.94rem;font-weight:550}}
        .st-key-tea_sweetness_control [role="radiogroup"] {{display:flex;flex-wrap:wrap;gap:.5rem}}
        .st-key-tea_sweetness_control [role="radiogroup"] label {{margin:0;padding:.43rem .72rem;
          min-height:40px;border:1px solid var(--guide-line);border-radius:9px;background:var(--guide-card)}}
        .st-key-tea_sweetness_control [role="radiogroup"] label:has(input:checked)
          {{background:#f3e2e5;border-color:var(--guide-beet);color:var(--guide-ink)}}
        .st-key-tea_sweetness_control [role="radiogroup"] label:focus-within {{outline:2px solid var(--guide-beet);outline-offset:2px}}
        </style>
        <section class="tea-recipe" aria-label="当前规格营养摘要"><div class="tea-head"><div>
        <div class="tea-brand">{escape(record['brand'])} · {escape(record.get('kind') or '现制茶饮')}</div>
        <h3>{escape(record['name'])}</h3><div>{escape(_configuration(record))}</div></div>
        <div class="tea-grade" data-grade="{grade_name}">营养等级<b>{mark}</b></div></div>
        <dl><div><dt>每杯能量 · {escape(basis)}</dt><dd>{metric('kcal', 'kcal')}</dd></div>
        <div><dt>每杯总糖 · {escape(basis)}</dt><dd>{metric('total_sugar', 'g')}</dd></div></dl>
        <div class="tea-sub">{escape(help_text)}</div><div class="tea-sub">{escape(notes)}</div></section>""")


def _show_record(record, prefs, flags, variants):
    render_energy_chart(record, variants)
    grade = record.get("grade") or record.get("estimated_grade")
    if grade in GRADE_NOTE:
        st.caption(GRADE_NOTE[grade])
    if record.get("grade_reason"):
        st.caption(record["grade_reason"])
    totals = {k: record[k] for k in NUTRIENTS if record.get(k) is not None}
    per100 = record.get("per100") or {}
    per100g = record.get("per100g") or {}
    if totals or per100 or per100g:
        with st.expander("查看完整营养数据"):
            if record.get("user_record") and record.get("volume"):
                st.caption(f"该规格的实际饮品体积为 {record['volume']:g} mL。")
            if per100g:
                st.table([{"项目": NUTRIENTS[k], "每 100 g": f"{v:g}"} for k, v in per100g.items() if k in NUTRIENTS])
                if record.get("mass"):
                    st.caption(f"按该配方每杯饮品净重 {record['mass']:g} g 换算整杯。")
                else:
                    st.caption("缺少该配方的整杯饮品净重，暂时只能查看每 100 g 的原数。")
            if totals:
                st.table([{"项目": NUTRIENTS[k], "每杯": f"{value:g}"} for k, value in totals.items()])
            if per100:
                st.table([{"项目": NUTRIENTS[k], "每 100 mL": f"{v:g}"} for k, v in per100.items() if k in NUTRIENTS])
                if not totals:
                    st.caption("需有这个配方的实际毫升数，才能换算整杯摄入量。")
    links = set()
    for key, title in (("source", "查看该规格资料"), ("grade_source", "查看等级依据")):
        url = record.get(key)
        if _https(url) and url not in links:
            st.link_button(title, url)
            links.add(url)
    if record.get("source_label"):
        st.caption("资料出处 · " + record["source_label"])
    if flags.intersection({"glucose", "lipids", "pressure"}):
        focus = [
            NUTRIENTS[key]
            for flag, key in (("glucose", "total_sugar"), ("lipids", "sat_fat"), ("pressure", "sodium"))
            if flag in flags
        ]
        st.caption("按你选填的饮食关注项，请核对每杯的" + "、".join(focus) + "；缺项可向门店询问。")
    if prefs.get("allergens") or prefs.get("diets"):
        st.caption("你已填写饮食限制。下单前请核对奶基底、小料过敏原和门店共线情况。")
    if "sugar" in prefs.get("goals", []):
        if record.get("total_sugar") is None:
            st.caption("你偏好少糖。这份资料缺少整杯总糖量，可向门店核对奶基底、果酱和小料的含糖情况。")
        else:
            st.caption(
                f"你偏好少糖。此规格每杯总糖{('最高' if record.get('value_type') == '最高标示值' else '约')} {record['total_sugar']:g} 克，比较杯型时可直接对照整杯克数。"
            )
    st.button("用此规格开始 DIY", key="tea.use.record", on_click=_open_diy, args=(record,))


def _card_editor(brand, name, settings, seed):
    # A new query or card gets its own widget identities, so unconfirmed values do not migrate.
    ns = f"tea.card.{brand}.{name}."
    with st.expander("补录品牌营养卡或薄荷健康「查奶茶」结果"):
        provider = st.radio("资料来自哪里？", ["品牌营养卡或点单页", "薄荷健康 · 查奶茶"],
                            horizontal=True, key=ns + "provider")
        boohee = provider == "薄荷健康 · 查奶茶"
        if boohee:
            ns += "boohee."
            st.caption("在薄荷健康「查奶茶」中选中相同品牌、完整品名和规格。可手填或上传结果截图，保存后在本次会话显示为第三方参考。")
        st.caption("请只录入一个规格的一列数值。截图可裁去账号、头像和订单资料，点击「抄录营养卡」后会将图片发送给百灵。")
        photo = st.file_uploader("薄荷查询结果截图" if boohee else "品牌营养卡照片",
                                 type=["jpg", "jpeg", "png", "webp"], key=ns + "photo")
        photo_id = sha256(photo.getvalue()).hexdigest() if photo is not None else None
        if st.session_state.get(ns + "photo_id") != photo_id:
            st.session_state[ns + "photo_id"] = photo_id
            st.session_state.pop(ns + "read", None)
            st.session_state[ns + "version"] = st.session_state.get(ns + "version", 0) + 1
        if photo is not None:
            st.image(photo, width=260)
        if st.button("抄录营养卡", key=ns + "scan", disabled=photo is None or not settings.api_key):
            try:
                with st.spinner("正在抄录营养卡…"):
                    read = recognize_tea(photo.getvalue(), settings, card=True)
                if not boohee and read.get("provider") == "boohee":
                    raise VisionError("请在资料来源选择「薄荷健康 · 查奶茶」，再上传该结果。")
                if boohee and not (read.get("brand") and read.get("name")):
                    raise VisionError("截图需包含茶饮品牌和完整品名，可重新截取或对照原页手动填写。")
                if (read.get("brand") and _norm(read["brand"]) != _norm(brand)) or (
                    read.get("name") and _norm(read["name"]) != _norm(name)
                ):
                    raise VisionError("营养卡上的品牌或品名与当前查询不同。请切换到卡片对应的饮品后再录入。")
                st.session_state[ns + "read"] = read
                st.session_state[ns + "version"] = st.session_state.get(ns + "version", 0) + 1
            except VisionError as exc:
                st.error(str(exc))
        base = st.session_state.get(ns + "read", {} if boohee else seed)
        form = ns + str(st.session_state.get(ns + "version", 0))
        with st.form(form):
            st.write(f"{brand} · {name}")
            kind = st.selectbox(
                "茶饮品类", ["鲜奶茶", "珍珠奶茶", "果茶", "纯茶", "奶盖茶", "其他"], index=None, key=form + "kind"
            )
            a, b, c = st.columns(3)
            size = a.text_input("杯型", value=base.get("size", ""), key=form + "size", max_chars=30)
            sugar = b.text_input("甜度", value=base.get("sugar", ""), key=form + "sugar", max_chars=30)
            temp = c.text_input("冰量或温度", value=base.get("temp", ""), key=form + "temp", max_chars=30)
            toppings = st.text_input(
                "额外小料（多项以顿号分隔，无额外小料填「无」，未注明可留空）" if boohee else "额外小料（以顿号分隔，无可留空）",
                value="无" if boohee and base.get("toppings") == [] else "、".join(base.get("toppings") or []),
                key=form + "toppings",
                max_chars=120,
            )
            region = st.text_input(
                "资料适用的地区或门店", placeholder="例如：中国内地 · 上海，或填「来源未注明」", key=form + "region", max_chars=100
            )
            scope = st.text_input(
                "适用配方说明（选填）",
                value=base.get("scope", ""),
                placeholder="例如：点单页标注的标准冰原配方",
                key=form + "scope",
                max_chars=120,
            )
            basis = st.radio(
                "营养卡数值基准",
                ["per_cup", "per_100ml", "per_100g"],
                index={"per_cup": 0, "per_100ml": 1, "per_100g": 2}.get(base.get("basis")),
                format_func=lambda s: {"per_cup": "每杯", "per_100ml": "每 100 mL", "per_100g": "每 100 g"}[s],
                horizontal=True,
                key=form + "basis",
            )
            volume = st.number_input(
                "该配方实际饮品体积（mL，可留空）",
                min_value=1.0,
                max_value=10000.0,
                value=base.get("volume") if 1 <= (base.get("volume") or 0) <= 10000 else None,
                key=form + "ml",
            )
            mass = st.number_input(
                "该配方整杯饮品净重（g，按每 100 g 换算整杯时填写）", min_value=1.0, max_value=10000.0,
                value=base.get("mass") if 1 <= (base.get("mass") or 0) <= 10000 else None, key=form + "mass",
            )
            cols = st.columns(2)
            numbers = {
                k: cols[i % 2].number_input(
                    label, min_value=0.0, max_value=1_000_000.0, value=base.get(k), format="%.3f", key=form + k
                )
                for i, (k, label) in enumerate(NUTRIENTS.items())
            }
            sweetener = None if boohee else st.radio(
                "食品添加剂中的甜味剂（GB 2760）",
                ["资料未说明", "明确使用", "明确未使用"],
                index={True: 1, False: 2}.get(base.get("sweetener"), 0),
                horizontal=True,
                key=form + "sweet",
            )
            published = "未标示" if boohee else st.selectbox(
                "该规格明确标示的中国「营养选择」等级",
                ["未标示", "A", "B", "C", "D"],
                index=["未标示", "A", "B", "C", "D"].index(base.get("grade") or "未标示"),
                key=form + "grade",
            )
            source = st.text_input(
                "薄荷结果页出处" if boohee else "品牌资料出处",
                value=f"{brand} · {name}" if boohee else "",
                placeholder="例如：小程序的产品营养详情页，或对应的 HTTPS 链接",
                max_chars=450,
                key=form + "source",
            )
            checked = st.checkbox("已对照原页核对品牌、完整品名、适用市场、杯型、甜度、加料和计量单位", key=form + "checked")
            save = st.form_submit_button("保存这份核对资料")
        if not save:
            return
        if not checked or not kind or not source.strip() or not region.strip():
            st.warning("请填写品类、适用范围、资料出处，并核对后勾选确认。")
            return
        if not boohee and ("薄荷健康" in source or "boohee.com" in source.casefold()):
            st.warning("薄荷健康的查询结果请通过「薄荷健康 · 查奶茶」录入。")
            return
        if any(v is not None for v in numbers.values()) and not basis:
            st.warning("请选择原页的数值基准（每杯、每 100 mL 或每 100 g）。")
            return
        if boohee and not (size.strip() or scope.strip() or volume or mass):
            st.warning("请填写结果页标出的杯型、每杯毫升数、每杯净重或适用配方说明；未披露的规格可在说明中注明。")
            return
        if not any(v is not None for v in numbers.values()) and published == "未标示":
            st.warning("请至少填写薄荷结果上的一项营养数值。" if boohee else "请至少填写一项营养数值或品牌明确标示的等级。")
            return
        per100g = {}
        if basis == "per_100g":
            per100g = {k: v for k, v in numbers.items() if v is not None}
            totals = {k: v * mass / 100 for k, v in per100g.items()} if mass else {}
            cup, per100 = _numbers(totals, "per_cup", volume)
        else:
            cup, per100 = _numbers(numbers, basis, volume)
        estimation, reason = (None, "") if boohee else catalog.grade_drink(
            per100.get(catalog.GRADE_SUGAR_FIELD),
            per100.get("sat_fat"),
            per100.get("trans_fat"),
            {"明确使用": True, "明确未使用": False}.get(sweetener),
        )
        extras = [v.strip() for v in toppings.replace("，", "、").replace(",", "、").split("、") if v.strip()]
        if boohee and not extras:
            extras = None
        elif boohee and extras == ["无"]:
            extras = []
        record = dict(
            brand=brand,
            name=name,
            kind=kind,
            size=size.strip(),
            sugar=sugar.strip(),
            temp=temp.strip(),
            toppings=extras,
            scope=scope.strip(),
            region=region.strip(),
            grade=None if published == "未标示" else published,
            estimated_grade=estimation,
            grade_scheme=None if boohee else ("中国营养选择（品牌标示）" if published != "未标示" else catalog.GRADE_RULE_NAME),
            grade_reason=reason if published == "未标示" else "",
            grade_source=catalog.GRADE_RULE_SOURCE if not boohee and published == "未标示" else "",
            volume=volume,
            mass=mass,
            basis=basis,
            per100g=per100g,
            source=source.strip() if _https(source.strip()) else "",
            source_label=("第三方 · 薄荷健康「查奶茶」 · " if boohee else "") + source.strip(),
            source_provider="boohee" if boohee else "brand",
            user_record=True,
            per100=per100,
            **cup,
        )
        if boohee:
            record["value_type"] = "薄荷健康第三方参考"
        key = (brand, name, size, sugar, temp, toppings, region, scope)
        if boohee:
            key += ("boohee", volume, mass)
        st.session_state.setdefault("tea.custom", {})[key] = record
        st.session_state["tea.show_saved"] = key
        st.session_state.pop("tea.query.region", None)
        st.rerun()


def _select_sweetness(variant_key, sweetness_key, indices):
    st.session_state[variant_key] = indices[st.session_state[sweetness_key]]


def _filter_catalog(changed=None):
    state = st.session_state
    if changed == "region":
        state["tea.catalog.brand"] = ""
    if changed in ("region", "brand"):
        state["tea.catalog.category"] = ""
    state["tea.catalog.pick"] = None
    state["tea.brand"] = state.get("tea.catalog.brand", "")
    state["tea.name"] = ""
    state.pop("tea.query", None)
    state.pop("tea.query.region", None)
    state.pop("tea.slip", None)


def _query_inputs(settings):
    method = st.radio("如何提供茶饮信息？", ["填写品牌与品名", "拍摄或上传杯贴"], horizontal=True, key="tea.entry")
    if method == "拍摄或上传杯贴":
        _receipt_input(settings)
    else:
        brand_count = len({brand for brand, _ in catalog.DIRECTORY})
        st.caption(f"茶饮目录收录 {brand_count} 个品牌、{len(catalog.DIRECTORY)} 款饮品。每个品牌的同名饮品按一款计。")
        area, left, right = st.columns(3)
        regions = sorted({region for info in catalog.DIRECTORY.values() for region in info["regions"]})
        region = area.selectbox("资料适用地区", ["", *regions], format_func=lambda v: v or "全部地区",
                                key="tea.catalog.region", on_change=_filter_catalog, args=("region",))
        in_region = catalog.find_drinks(region=region)
        brands = sorted({brand for brand, _ in in_region})
        chosen_brand = left.selectbox("按品牌筛选", ["", *brands], format_func=lambda v: v or "全部品牌",
                                      key="tea.catalog.brand", on_change=_filter_catalog, args=("brand",))
        categories = sorted({kind for key in in_region if not chosen_brand or key[0] == chosen_brand
                             for kind in catalog.DIRECTORY[key]["categories"]})
        category = right.selectbox("按品类筛选", ["", *categories], format_func=lambda v: v or "全部品类",
                                   key="tea.catalog.category", on_change=_filter_catalog)
        only = st.checkbox("只看有营养数值或等级的饮品", key="tea.catalog.evidence", on_change=_filter_catalog)
        evidenced = set(catalog.find_drinks(chosen_brand, category, region=region, evidence_only=True))
        items = sorted(evidenced) if only else catalog.find_drinks(chosen_brand, category, region=region)
        count = len(evidenced)
        st.caption(f"当前可查 {len(items)} 款，其中 {count} 款有已收录规格的营养数值或等级。")
        st.selectbox(
            "从已收录饮品中选择（也可在下方输入）",
            items,
            index=None,
            format_func=lambda p: " · ".join(p) + ("" if p in evidenced else
                                                   "（仅菜单）" if catalog.DIRECTORY[p]["menus"] else "（营养待补）"),
            key="tea.catalog.pick",
            on_change=_catalog_pick,
        )
    left, right = st.columns(2)
    brand = left.text_input("茶饮品牌", key="tea.brand", max_chars=80, placeholder="例如：霸王茶姬").strip()
    name = right.text_input("饮品名称", key="tea.name", max_chars=100, placeholder="例如：伯牙绝弦").strip()
    slip = st.session_state.get("tea.slip", {})
    if method == "拍摄或上传杯贴" and slip:
        st.caption("杯贴抄录 · " + _configuration(slip))
    if catalog.canonical_brand(brand) == LIVE_BRAND:
        st.caption("点击查询会把品名发给霸王茶姬中国大陆健康计算器，取得当前参考配方。其他规格可在 DIY 中查询。")
    if st.button("查询营养资料", key="tea.search", type="primary", disabled=not brand or not name):
        st.session_state["tea.query"] = (brand, name)
        st.session_state.pop("tea.query.region", None)
        st.session_state.pop("tea.show_saved", None)
        if catalog.canonical_brand(brand) == LIVE_BRAND:
            with st.spinner("正在核对品牌健康计算器…"):
                current = recent_recipe(name)
            if current:
                live = st.session_state.setdefault("tea.live_variants", {})
                live[spec_key(current)] = current
                if method == "拍摄或上传杯贴" and slip:
                    changed = {
                        **current,
                        **{k: slip[k] for k in ("size", "sugar", "temp", "toppings") if k in slip},
                    }
                    if spec_key(changed) != spec_key(current):
                        with st.spinner("正在核对杯贴写明的规格…"):
                            match = live_variant(current, changed)
                        if match:
                            live[spec_key(match)] = match
            else:
                st.info("品牌计算器本次未返回可核实的数据。下方仍可查收录资料或补录营养卡。")
    return method, brand, name, slip


def tea_lookup(settings, prefs, flags):
    has_query = st.session_state.get("tea.query") == (st.session_state.get("tea.brand"), st.session_state.get("tea.name"))
    inputs = st.expander("查询饮品或更换完整规格", expanded=not has_query)
    with inputs:
        method, brand, name, slip = _query_inputs(settings)
    if st.session_state.get("tea.query") != (brand, name):
        return
    brand = catalog.canonical_brand(brand)
    same_slip = method == "拍摄或上传杯贴" and bool(slip)
    if same_slip:
        slip = {**slip, "brand": brand, "name": name}
    current = [
        r
        for r in st.session_state.get("tea.live_variants", {}).values()
        if _norm(r["brand"]) == _norm(brand) and _norm(r["name"]) == _norm(name)
    ]
    current_keys = {spec_key(r) for r in current}
    records = [*current, *(r for r in catalog.exact_match(brand, name) if spec_key(r) not in current_keys)]
    custom = st.session_state.get("tea.custom", {})
    records.extend(
        r for r in custom.values() if _norm(r["brand"]) == _norm(brand) and _norm(r["name"]) == _norm(name)
    )
    market = st.session_state.get("tea.query.region")
    if market:
        records = [r for r in records if r.get("region") == market]
    menu = catalog.menu_entry(brand, name)
    if records:
        compatible = _order_candidates(slip, records) if same_slip else []
        if same_slip:
            if compatible:
                st.caption("已优先列出符合杯贴可读规格的资料。请继续核对适用市场，以及杯贴没有写明的选项。")
            else:
                st.warning("尚不能把杯贴与具体配方对应。下列是同名饮品的参考资料，所列数值可能与你这杯不同。")
        saved = custom.get(st.session_state.pop("tea.show_saved", None))
        rev = len(records)
        options = compatible + [i for i in range(rev) if i not in compatible]
        key = f"tea.variants.{brand}.{name}.{rev}.{tuple(compatible)}"
        if saved in records:
            st.session_state[key] = records.index(saved)
        selection = inputs.selectbox(
            "查看哪个规格的资料？",
            options,
            format_func=lambda i: _spec(records[i]),
            key=key,
        )
        selected = records[selection]
        variants = sweetness_variants(selected, records)
        _recipe_summary(selected)
        if variants:
            indices = {row["sugar"]: records.index(row) for row in variants}
            sweetness_key = key + ".sweetness"
            st.session_state[sweetness_key] = selected["sugar"]
            with st.container(key="tea_sweetness_control"):
                st.radio("切换同配方甜度", list(indices), horizontal=True, key=sweetness_key,
                         on_change=_select_sweetness, args=(key, sweetness_key, indices))
        _show_record(selected, prefs, flags, variants)
    else:
        if menu:
            st.subheader(f"{brand} · {name}")
            st.write("品牌菜单已收录这款饮品，当前缺少可核实的对应规格营养数据。")
            st.caption("所属品类 · " + "、".join(sorted(menu["categories"])))
            for region, source in menu["menus"]:
                if not market or region == market:
                    st.link_button(f"查看{region}品名出处", source)
        else:
            st.info("资料库尚无这个完整品名的已核实配方。可查看品牌点单页，或补录该杯的营养资料。")
        similar = catalog.find_drinks(brand, term=name) if not menu else []
        if similar:
            key = f"tea.suggestions.{brand}.{name}"
            st.selectbox(
                "按品类或部分品名找到的饮品",
                similar,
                index=None,
                key=key,
                format_func=lambda p: p[1],
                on_change=_catalog_pick,
                args=(key,),
            )
    url = catalog.BRAND_LOOKUP.get(brand)
    if _https(url) and (records or not menu):
        st.link_button("查看品牌资料页", url)
    if same_slip:
        initial = {k: v for k, v in slip.items() if k != "grade"}
        initial.update(from_receipt=True, currency="CNY")
        if slip.get("grade"):
            confirmed = st.checkbox(
                f"我已核对杯贴，确认这杯标有中国「营养选择」{slip['grade']} 级", key="tea.slip.grade." + repr(slip)
            )
            if confirmed:
                initial.update(
                    grade=slip["grade"],
                    grade_scheme="中国营养选择（品牌标示）",
                    grade_note="本次订单杯贴，经用户对照照片确认",
                )
                st.write(GRADE_NOTE[slip["grade"]])
        st.button("带入杯贴规格，核对点单", key="tea.use.slip", on_click=_open_diy, args=(initial,))
    _card_editor(brand, name, settings, slip if same_slip else {})


def tea_home(settings, prefs, flags):
    with st.container(key="tea_functions"):
        route = st.radio("现制奶茶 · 选择功能", ["查一杯奶茶", "DIY 点单", "比较与推荐", "个人茶饮账本"],
                         horizontal=True, width="stretch", key="tea.route")
    records = [*catalog.CATALOG, *st.session_state.get("tea.custom", {}).values()]
    st.session_state["tea.records"] = records
    route_key = {"查一杯奶茶": "lookup", "DIY 点单": "diy", "比较与推荐": "compare", "个人茶饮账本": "ledger"}[route]
    with st.container(key="guide_view_tea_" + route_key):
        if route == "查一杯奶茶":
            tea_lookup(settings, prefs, flags)
        elif route == "DIY 点单":
            render_simulator(records, prefs, flags, initial=st.session_state.pop("tea.initial_order", None))
        elif route == "比较与推荐":
            render_comparison(prefs, flags)
        else:
            render_ledger()

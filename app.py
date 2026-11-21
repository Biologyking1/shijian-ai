import os
from io import BytesIO
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

from nutrition import (
    Basis, CATEGORIES, EXPLANATIONS, NUTRIENTS, FoodLabel, calculate_bmi, label_from_payload,
    portion_reference, review_food, scale_nutrients,
)
from vision import MAX_PHOTOS, VisionError, VisionSettings, recognize_label
from label_knowledge import render_label_checks, restriction_check, watch_alerts
from product_workspace import (
    FIELD_LABELS, Product, batch_intake, data_value, evidence_panel, select_product, supplement_photos,
)
from shopping_views import compare_decisions, profile_panel, single_decision


BASIS_LABELS = {
    Basis.UNKNOWN: "未确认", Basis.GRAMS: "每 100 克", Basis.MILLILITERS: "每 100 毫升", Basis.SERVING: "每份",
}
STATE_LABELS = {"unknown": "未确认", "as_sold": "包装原状", "prepared": "冲调后"}
UNIT_LABELS = {"g": "克", "mL": "毫升", "份": "份"}
HEALTH_OPTIONS = {
    "血糖偏高或糖尿病": "glucose", "血脂偏高": "lipids", "血压偏高或高血压": "pressure",
    "其他饮食限制": "other", "暂无": "none", "不确定": "unknown", "不愿填写": "skip",
}
DEMO_LABEL = {
    "name": "柠檬茶饮料（演示样品）", "category": "drink", "basis": "per_100_ml", "label_state": "as_sold",
    "package_size": 500, "package_unit": "mL", "ingredients": "水、白砂糖、红茶、柠檬汁",
    "nutrients": {"energy": 136, "protein": 0, "fat": 0, "carbs": 8, "sodium": 12},
    "price": 4.5, "claims": ["低脂"], "flavors": ["柠檬味"],
}


def setting(name: str, default: str = "") -> str:
    from_environment = os.getenv(name)
    if from_environment is not None:
        return from_environment.strip()
    try:
        return str(st.secrets.get(name, default)).strip()
    except FileNotFoundError:
        return default


def share_app(url: str) -> None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        return
    with st.expander("分享网页 · 二维码"):
        st.link_button("打开分享链接", url)
        try:
            import qrcode
        except ImportError:
            st.caption("当前运行环境缺少二维码组件，仍可复制上方链接。")
            return
        qr = qrcode.make(url)
        png = BytesIO()
        qr.save(png, format="PNG")
        st.image(png.getvalue(), width=210, caption="用手机扫码打开食鉴 AI")
        st.download_button("下载二维码", png.getvalue(), "food-label-ai.png", mime="image/png")


def profile() -> tuple[set[str], int | None, float | None]:
    st.header("个人信息（选填）")
    st.caption("愿意填写时，请按实际情况选择，方便我们提醒你关注相关成分。也可以直接选择下方入口。个人信息仅用于本次会话。")
    answers = st.session_state.setdefault("personal_answers", {})
    for key, saved in answers.items():
        if key not in st.session_state:
            st.session_state[key] = saved
    with st.expander("年龄、性别、身高和体重"):
        left, right = st.columns(2)
        age = left.number_input("年龄（岁）", 1, 120, value=None, step=1, placeholder="选填", key="person_age")
        sex = right.selectbox("性别", ("女", "男", "其他", "不愿填写"), index=None, placeholder="选填", key="person_sex")
        height = left.number_input("身高（厘米）", 40.0, 250.0, value=None, placeholder="选填", key="person_height")
        weight = right.number_input("体重（公斤）", 2.0, 500.0, value=None, placeholder="选填", key="person_weight")
        bmi = calculate_bmi(height, weight)
        if bmi is not None:
            st.write(f"**BMI {bmi:g}**")
    choices = st.multiselect("你有需要通过饮食管理的情况吗？", list(HEALTH_OPTIONS),
                             key="health_flags", placeholder="可多选，也可以跳过")
    answers.update(person_age=age, person_sex=sex, person_height=height, person_weight=weight, health_flags=choices)
    flags = {HEALTH_OPTIONS[choice] for choice in choices}
    if flags.intersection({"none", "unknown", "skip"}) and len(flags) > 1:
        st.warning("请选择具体情况，或单独选择「暂无」「不确定」或「不愿填写」。")
        flags = set()
    return flags, age, bmi


def seed_editor(label: FoodLabel, source: str) -> None:
    st.session_state.update({
        "draft_source": source, "active_label": None, "unreadable": label.unreadable,
        "food_name": label.name, "category": label.category, "ingredients": label.ingredients,
        "basis": BASIS_LABELS[label.basis], "label_state": label.label_state,
        "package_size": label.package_size, "package_unit": label.package_unit,
        "serving_size": label.serving_size, "serving_unit": label.serving_unit,
        "edit_price": label.price, "edit_claims": "\n".join(label.claims),
        "edit_flavors": "、".join(label.flavors), "edit_allergens": label.allergen_text,
        **{f"nutrient_{key}": label.nutrients.get(key) for key in NUTRIENTS},
    })
    st.session_state.pop("portion", None)
    st.session_state.pop("portion_choice", None)


def save_camera_shot() -> None:
    shot = st.session_state.camera_shot
    if shot is not None:
        st.session_state.camera_photos.append(shot.getvalue())
        st.session_state.camera_open = False


def label_input(vision_settings: VisionSettings) -> None:
    st.header("2. 上传照片或录入标签")
    st.caption("可以分别拍摄营养成分表、配料表和包装正面。照片须来自同一款食品。")
    images = st.file_uploader("从相册或文件选图", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    shots = st.session_state.setdefault("camera_photos", [])
    photo_count = len(images) + len(shots)
    if photo_count >= MAX_PHOTOS:
        st.session_state.camera_open = False
    if st.toggle("打开相机拍照", key="camera_open", disabled=photo_count >= MAX_PHOTOS):
        st.caption("请允许浏览器使用摄像头，对准标签并拍照。拍好的照片会加入下方列表。")
        st.camera_input("拍摄食品包装", key="camera_shot", on_change=save_camera_shot)
    if shots:
        for index, column in enumerate(st.columns(len(shots))):
            column.image(shots[index], caption=f"实拍照片 {index + 1}")
            column.button(f"移除照片 {index + 1}", key=f"remove_shot_{index}",
                          on_click=shots.pop, args=(index,))
    if photo_count > MAX_PHOTOS:
        st.warning(f"已选择 {photo_count} 张，请移除多余照片后再识别。")
    else:
        st.caption(f"已选 {photo_count} / {MAX_PHOTOS} 张照片")
    if not vision_settings.api_key:
        st.caption("图片识别尚未配置。可以载入示例或手动录入标签。")
    elif photo_count:
        st.caption("点击识别后，处理过的包装照片将发送给配置的模型服务。")
    scan, demo, manual = st.columns(3)
    can_scan = 1 <= photo_count <= MAX_PHOTOS and bool(vision_settings.api_key)
    if scan.button("识别照片", key="scan", type="primary", disabled=not can_scan):
        try:
            with st.spinner("正在识别标签…"):
                photos = tuple([image.getvalue() for image in images] + shots)
                label = recognize_label(list(photos), vision_settings)
            st.session_state.single_product = Product(label, "照片识别", photos)
        except VisionError as error:
            st.error(str(error))
    if demo.button("载入示例", key="load_demo"):
        st.session_state.single_product = Product(label_from_payload(DEMO_LABEL), "示例")
    if manual.button("手动录入", key="manual", disabled=photo_count > MAX_PHOTOS):
        photos = tuple([image.getvalue() for image in images] + shots)
        st.session_state.single_product = Product(label_from_payload({}), "手动录入", photos)


def label_editor(item: Product, *, shopping=False) -> None:
    if st.session_state.get("editor_uid") != item.uid or "food_name" not in st.session_state:
        seed_editor(item.label, item.source)
        st.session_state.editor_uid = item.uid
        st.session_state.active_label = item.confirmed
        st.session_state.verified_uncertain = item.confirmed is not None
        st.session_state.partial_ingredients = any(word in item.label.unreadable for word in ("配料", "原料"))
    source = st.session_state.draft_source
    st.subheader("核对标签")
    if source == "示例":
        st.caption("以下是演示数据，可直接生成建议。")
    if "识别" in source and item.confirmed is None:
        st.info("请对照原图核对商品、价格、数值与单位。无法确认的值请留空，保存后才参与评价。")
        if item.original.uncertain_fields:
            st.warning("需要复核 · " + "、".join(FIELD_LABELS.get(k, k) for k in item.original.uncertain_fields))
        if st.session_state.unreadable:
            st.text(st.session_state.unreadable)
    supplement_photos(item)
    evidence_panel(item)

    with st.form("label_form"):
        left, right = st.columns(2)
        name = left.text_input("食品名称", max_chars=100, key="food_name")
        category = right.selectbox("食品类别", CATEGORIES.keys(), format_func=CATEGORIES.__getitem__, key="category")
        ingredients = st.text_area("配料表", max_chars=2500, key="ingredients", placeholder="没看清的内容可以留空")
        partial = st.checkbox("配料表只读到了部分内容", key="partial_ingredients")
        with st.expander("价格、正面声称、口味与致敏提示", expanded=shopping):
            price = st.number_input("整包实际售价（人民币元）", min_value=0.0, value=None,
                                    step=0.1, key="edit_price", help="价签须与商品及规格相符。仅在已确认时填写。")
            claims = st.text_area("包装正面的营养宣传语（每行一句）", key="edit_claims", max_chars=1000)
            flavors = st.text_input("口味描述（用顿号隔开）", key="edit_flavors", max_chars=200)
            allergens = st.text_area("致敏物质与共线生产提示（包装原文）", key="edit_allergens", max_chars=1200)
        basis = left.selectbox("营养成分表按什么份量标示？", BASIS_LABELS.values(), key="basis")
        state = right.selectbox("食物状态", STATE_LABELS.keys(), format_func=STATE_LABELS.__getitem__, key="label_state")
        with st.expander("整包净含量和标签份量（选填）"):
            size_col, unit_col = st.columns(2)
            package_size = size_col.number_input("整包净含量", min_value=0.0, step=1.0, key="package_size")
            package_unit = unit_col.selectbox("整包单位", ["g", "mL"], index=None, key="package_unit")
            serving_size = size_col.number_input("标签每份大小", min_value=0.0, step=1.0, key="serving_size")
            serving_unit = unit_col.selectbox("每份单位", ["g", "mL"], index=None, key="serving_unit")
        st.caption("填包装上的实际数值，未标注请留空。能量用千焦，钠用毫克，其余用克。")
        value_columns = st.columns(2)
        nutrients = {
            key: value_columns[index % 2].number_input(f"{title}（{unit}）", min_value=0.0,
                                                       step=0.01, format="%.3f", key=f"nutrient_{key}")
            for index, (key, (title, unit)) in enumerate(NUTRIENTS.items())
        }
        verified = False
        if item.original.uncertain_fields:
            verified = st.checkbox("已逐项核实保留的存疑数据，无法确认的项目已留空", key="verified_uncertain")
        submitted = st.form_submit_button("确认并保存这款商品" if shopping else "确认标签并生成建议",
                                          type="primary", key="apply_label")

    if submitted:
        label = label_from_payload({
            "name": name, "category": category, "ingredients": ingredients,
            "basis": next(key.value for key, title in BASIS_LABELS.items() if title == basis),
            "label_state": state, "package_size": package_size, "package_unit": package_unit,
            "serving_size": serving_size, "serving_unit": serving_unit, "nutrients": nutrients,
            "price": price, "claims": claims.splitlines(), "allergen_text": allergens,
            "flavors": flavors.replace("，", "、").replace(",", "、").split("、"),
            "evidence": {**item.original.evidence, **item.linked},
            "unreadable": "配料表不完整" if partial else "",
        }, photo_count=len(item.photos))
        remaining = [
            FIELD_LABELS[k] for k in item.original.uncertain_fields
            if data_value(label, k) not in (None, "", [], "unknown")
            and data_value(label, k) == data_value(item.original, k)
        ]
        if remaining and not verified:
            st.warning("请对照原图复核后勾选确认，或清除这些存疑值：" + "、".join(remaining))
            return
        if shopping and not label.name:
            st.warning("请填写品名或能区分商品与规格的简称。")
            return
        if not shopping and not (label.nutrients or label.ingredients or label.claims or label.allergen_text
                                 or label.price is not None):
            st.session_state.active_label = None
            st.warning("请至少录入一项标签信息再生成建议。")
            return
        item.confirmed = label
        st.session_state.active_label = label
        st.session_state.pop("portion", None)
        st.session_state.pop("portion_choice", None)


def portion_value(label: FoodLabel) -> tuple[float, str] | None:
    reference = portion_reference(label)
    if reference is None:
        st.info("请核对营养成分表的标示口径，确认后才能换算食用份量。")
        return None
    amount, unit = reference
    unit_label = UNIT_LABELS[unit]
    options = {f"标签标示份量 · {amount:g} {unit_label}": amount}
    use_serving = label.basis is Basis.SERVING
    if label.serving_size and label.serving_unit == unit and label.serving_size != amount:
        amount = label.serving_size
        options[f"包装标示的一份 · {amount:g} {unit_label}"] = amount
        use_serving = True
    package_matches = (label.package_size and label.package_unit == unit and label.label_state != "prepared")
    if package_matches:
        if label.package_size >= 0.002:
            options[f"半包 · {label.package_size / 2:g} {unit_label}"] = label.package_size / 2
        options[f"整包 · {label.package_size:g} {unit_label}"] = label.package_size
    if len(options) > 1:
        st.selectbox("快速选择份量", options.keys(), index=None, key="portion_choice",
                     placeholder="也可以直接输入下方份量", on_change=apply_quick_portion, args=(options,))
    if "portion" not in st.session_state:
        st.session_state.portion = float(amount)
    result = st.number_input(f"这次吃多少（{unit_label}）", min_value=0.0, max_value=1_000_000.0, value=None,
                             step=0.1 if unit == "份" else 1.0, format="%.3f", key="portion")
    upper = float(max(label.package_size if package_matches else 2 * amount, result or 0, 1))
    st.session_state.drag_portion = float(result or 0)
    st.slider(f"拖动调整食用量（{unit_label}）", 0.0, upper, step=0.1 if unit == "份" or upper < 10 else 1.0,
              key="drag_portion", on_change=apply_dragged_portion)
    if use_serving:
        st.caption("默认使用包装标示的一份作为参考，按实际吃的量调整即可。")
    else:
        st.caption("默认用标签标示的份量试算，可以改成实际份量。")
    return (result, unit) if result is not None else None


def apply_dragged_portion() -> None:
    st.session_state.portion = st.session_state.drag_portion
    st.session_state.portion_choice = None


def apply_quick_portion(options: dict[str, float]) -> None:
    choice = st.session_state.portion_choice
    if choice in options:
        st.session_state.portion = options[choice]


def open_intake_calculator(item: Product) -> None:
    st.session_state.single_product = item
    st.session_state.work_route = "单品解读"
    st.session_state.reading_focus = "食用量与建议"
    st.session_state.editor_uid = None


def format_nutrient(value: float, unit: str) -> str:
    if 0 < value < 0.001:
        return f"<0.001 {unit}"
    return f"{value:.3f}".rstrip("0").rstrip(".") + f" {unit}"


def show_review(label: FoodLabel, flags: set[str], age: int | None, bmi: float | None, prefs: dict) -> None:
    st.header("3. 看解读和食用建议")
    st.subheader(label.name or "当前食品")
    review = review_food(label, flags)
    blocked, unknown = restriction_check(label, prefs)
    if blocked or unknown:
        st.warning("请先核实饮食限制。下表只换算标签上的营养值。")
        for reason in [*blocked, *unknown]:
            st.text(reason)
    if review.focus:
        st.write("**本次重点** · " + "、".join(NUTRIENTS[key][0] for key in review.focus))
    if bmi is not None and age is not None and age >= 18:
        st.caption(f"当前 BMI {bmi:g}，仅供了解体重情况。食用量按标签和你输入的份量换算。")
    if age is not None and age < 18:
        st.caption("未成年人可查看标签解读和份量换算。")

    st.markdown("**吃多少**")
    if label.label_state == "prepared":
        st.info("这些数据按冲调后的状态标示，请输入冲调后实际吃或喝的量。")
    portion = portion_value(label) if label.nutrients else None
    scaled = {}
    if portion:
        scaled = scale_nutrients(label, *portion) if portion[0] else dict.fromkeys(label.nutrients, 0)
        if "sugar" in scaled:
            st.caption(f"这次摄入糖 {scaled['sugar']:g} 克，约相当于 {scaled['sugar'] / 4:.2f}".rstrip("0").rstrip(".")
                       + " 块方糖（每块按 4 克作重量类比，包含食品中天然存在的糖）。")
    keys = dict.fromkeys((*review.focus, *label.nutrients, "sugar"))
    records = []
    for key in keys:
        name, unit = NUTRIENTS[key]
        records.append({"营养成分": name, "包装标示": format_nutrient(label.nutrients[key], unit)
                        if key in label.nutrients else "未标注或未识别",
                        "这次摄入": format_nutrient(scaled[key], unit) if key in scaled else "—"})
    if label.nutrients:
        st.dataframe(pd.DataFrame(records).set_index("营养成分"), width="stretch")
        st.caption(f"包装标示口径 · {BASIS_LABELS[label.basis]}")
    elif label.ingredients:
        st.caption("目前只有配料数据，补充营养成分表后可换算份量。")
    else:
        st.caption("补充营养成分表后，可换算实际摄入量。")

    with st.expander("营养成分怎么理解", expanded=True):
        explanation_keys = review.focus or tuple(key for key in EXPLANATIONS if key in label.nutrients)
        for key in explanation_keys:
            if key in label.nutrients:
                st.write(EXPLANATIONS[key])
        if review.missing:
            st.caption("需要留意但没有可用数值的项目 · " + "、".join(review.missing))

    if blocked or unknown:
        return
    st.markdown("**怎么吃**")
    st.write(review.how)
    for consideration in review.considerations:
        st.write(consideration)
    st.markdown("**可以换成什么**")
    if label.category == "drink" and (prefs.get("allergens") or prefs.get("diets")):
        st.write("如果是为了解渴，可选白水。")
    elif prefs.get("allergens") or prefs.get("diets"):
        st.write("可将准备替换的食品加入「多款比较」，逐款核对配料与致敏提示后再选。")
    else:
        st.write(review.alternative)
    if flags.intersection({"glucose", "pressure", "lipids", "other"}):
        st.caption("如已有医生或营养师给出的饮食计划，份量与替代食物请按该计划安排。")


def main() -> None:
    st.set_page_config(page_title="食鉴 AI", page_icon="🥗", layout="centered")
    st.title("食鉴 AI")
    share_app(setting("PUBLIC_APP_URL"))
    flags, age, bmi = profile()
    prefs = profile_panel()
    st.header("选择食品类型")
    packaged, tea = st.columns(2)
    packaged.markdown("**预包装食品**")
    packaged.caption("只接收预包装商品的包装、背标、价签或货架照片，以及对应的商品描述。")
    tea.markdown("**现制奶茶**")
    tea.caption("只接收现制茶饮的杯贴、订单或品牌营养卡，以及对应的品牌、品名和点单规格。")
    area = st.radio("进入哪个专区？", ["预包装食品", "现制奶茶"], index=None, horizontal=True, key="food_area")
    if area is None:
        return
    settings = VisionSettings(setting("LING_API_KEY"), setting("LING_BASE_URL", "https://api.ant-ling.com/v1"),
                              setting("LING_MODEL", "Ling-3.2-flash"),
                              direct_connection=setting("LING_DIRECT_CONNECTION").lower() == "true")
    if area == "现制奶茶":
        from tea_views import tea_home
        tea_home(settings, prefs, flags)
        return
    route = st.radio("预包装食品 · 选择功能", ["单品解读", "多款比较", "货架购物助手"], horizontal=True, key="work_route",
                     captions=["看懂标签，换算食用量", "比较价格、营养和口味", "按预算从现场候选中选购"])
    basket = st.session_state.setdefault("basket", {})
    if route == "单品解读":
        label_input(settings)
        item = st.session_state.get("single_product")
        if item is None:
            return
        label_editor(item)
        if item.confirmed:
            st.divider()
            focus = st.radio("想查看哪项结果？", ["食用量与建议", "宣传语、配料与过敏原", "购买匹配度"],
                             horizontal=True, key="reading_focus")
            if focus == "宣传语、配料与过敏原":
                render_label_checks(item.confirmed, prefs)
            else:
                matches = watch_alerts(item.confirmed, prefs)
                if matches:
                    st.info("发现你关注的配料 · " + "、".join(matches))
                if focus == "食用量与建议":
                    show_review(item.confirmed, flags, age, bmi, prefs)
                else:
                    single_decision(item.confirmed, prefs)
            if st.button("加入比较清单", disabled=item.uid in basket, key="add_to_basket"):
                basket[item.uid] = item
                st.success("已加入，可在上方选择「多款比较」。")
        return

    shelf = route == "货架购物助手"
    st.header("在预算和饮食限制内选一款" if shelf else "按我的偏好比较商品")
    with st.expander("拍摄货架、上传标签或手动添加" if shelf else "上传多款商品或手动添加", expanded=not basket):
        batch_intake(basket, settings, shelf)
    item = select_product(basket)
    if item is None:
        return
    with st.expander("核对所选商品的标签和价签", expanded=item.confirmed is None):
        label_editor(item, shopping=True)
    if item.confirmed:
        st.button("打开这款的食用量计算器", key="inspect_candidate", on_click=open_intake_calculator, args=(item,))
        with st.expander("这款商品的营销声称、配料与饮食提醒"):
            render_label_checks(item.confirmed, prefs)
    confirmed = [record for record in basket.values() if record.confirmed]
    if len(confirmed) != len(basket):
        st.caption(f"已核对 {len(confirmed)} / {len(basket)} 款。待核对商品会在保存后加入比较。")
    if not confirmed:
        return
    real = [record for record in confirmed if record.source != "示例"]
    if real and len(real) != len(confirmed):
        st.caption("当前按实际录入的商品比较，演示商品已隐藏。")
    candidates = real or confirmed
    if not real:
        st.caption("正在比较演示商品。价格和标签数据用于体验。")
    if shelf:
        st.caption("本次在架候选中选购一包。可在偏好档案中设置预算、过敏原及饮食限制。")
        by_id = {record.uid: record for record in candidates}
        skip = st.multiselect("缺货或本次不考虑的商品", list(by_id), format_func=lambda uid: by_id[uid].label.name,
                              key="unavailable")
        candidates = [r for r in candidates if r.uid not in skip]
    if candidates:
        compare_decisions([r.confirmed for r in candidates], prefs)
    else:
        st.info("目前没有可购买的候选商品。")


main()

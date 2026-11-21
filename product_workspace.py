"""A user's current products, original photos and comparison intake."""
from dataclasses import dataclass, field
from io import BytesIO
from uuid import uuid4

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

from nutrition import FoodLabel, NUTRIENTS, label_from_payload
from vision import MAX_BATCH_PHOTOS, VisionError, recognize_products


FIELD_LABELS = {
    "name": "品名", "price": "整包价格（元）", "claims": "正面营养声称", "ingredients": "配料表",
    "allergen_text": "致敏物质与共线提示", "flavors": "口味描述", "package_size": "净含量",
    "package_unit": "净含量单位", "basis": "营养标示口径", "label_state": "食物状态",
    "serving_size": "每份大小", "serving_unit": "每份单位", "category": "食品类别",
    **{key: f"{name}（{unit}）" for key, (name, unit) in NUTRIENTS.items()},
}


@dataclass
class Product:
    original: FoodLabel
    source: str
    photos: tuple[bytes, ...] = ()
    confirmed: FoodLabel | None = None
    uid: str = field(default_factory=lambda: uuid4().hex)
    linked: dict[str, int] = field(default_factory=dict)

    @property
    def label(self):
        return self.confirmed or self.original


def data_value(label, key):
    if key in NUTRIENTS:
        return label.nutrients.get(key)
    return getattr(label, key)


def display_value(value):
    if value is None or value == "" or value == [] or value == "unknown":
        return "待补充"
    if isinstance(value, (list, tuple)):
        return "、".join(value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(getattr(value, "value", value))


def evidence_panel(item):
    with st.expander("查看数据与原始照片"):
        label = item.label
        key = st.selectbox("选择要核对的数据", FIELD_LABELS, format_func=lambda k:
                           f"{FIELD_LABELS[k]} · {display_value(data_value(label, k))}",
                           key=f"evidence_{item.uid}")
        changed = data_value(label, key) != data_value(item.original, key)
        if changed:
            st.caption(f"已人工修改。最初记录为 {display_value(data_value(item.original, key))}。")
        if not item.photos:
            st.caption(f"这条记录来自{item.source}。当前没有原始照片。")
            return
        index = item.linked.get(key, item.original.evidence.get(key))
        if index and 1 <= index <= len(item.photos):
            st.caption(f"{FIELD_LABELS[key]} 对应原图 {index}。")
        else:
            index = None
            st.caption("这项数据还没有定位到具体照片，可选择原图核对。")
        source = st.selectbox("查看原图", range(1, len(item.photos) + 1), index=(index or 1) - 1,
                              format_func=lambda n: f"原图 {n}", key=f"source_{item.uid}_{key}")
        try:
            with Image.open(BytesIO(item.photos[source - 1])) as img:
                if img.width * img.height > 50_000_000:
                    raise ValueError
                st.image(ImageOps.exif_transpose(img), caption=f"原图 {source}")
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            st.warning("这张图片无法显示，请重新上传清晰的包装照片。")
        if st.button("将当前照片关联到所选数据", key=f"link_{item.uid}_{key}"):
            item.linked[key] = source
            st.rerun()


def supplement_photos(item):
    if not st.checkbox("补充这款商品的原图", key=f"more_{item.uid}"):
        return
    extra = st.file_uploader("上传同一规格的清晰近照", type=["jpeg", "jpg", "webp", "png"],
                             accept_multiple_files=True, key=f"extra_{item.uid}")
    if st.button("附到这款商品，供核对时查看", disabled=not extra, key=f"attach_{item.uid}"):
        photos = list(item.photos)
        for file in extra:
            data = file.getvalue()
            if data not in photos:
                photos.append(data)
        item.photos = tuple(photos)
        st.success("可在「查看数据与原始照片」中把字段关联到补充照片，再根据清晰的标签修正数据。")


def demo_products():
    common = {"category": "drink", "basis": "per_100_ml", "label_state": "as_sold",
              "package_size": 500, "package_unit": "mL"}
    variants = [
        ("原味无糖茶", 4.5, "水、红茶", "原味", 0, 7, "无糖"),
        ("蜜桃茶饮料", 3.2, "水、白砂糖、红茶、桃汁", "蜜桃味", 7.5, 12, ""),
        ("低糖柠檬茶", 5.0, "水、柠檬汁、红茶、白砂糖", "柠檬味", 3, 8, "低糖"),
    ]
    for name, price, ingredients, flavor, sugar, sodium, claim in variants:
        label = label_from_payload(dict(common, name=name, price=price, ingredients=ingredients,
                                        flavors=[flavor], claims=[claim] if claim else [],
                                        nutrients={"sugar": sugar, "carbs": sugar, "sodium": sodium,
                                                   "fat": 0, "protein": 0}))
        yield Product(label, "示例", confirmed=label)


def batch_intake(basket, settings, shelf):
    st.subheader("添加货架候选商品" if shelf else "添加待比较商品")
    st.caption("货架照片可同时包含多件商品和价签。可追加各商品的正反面近照，帮助区分规格和价格。"
               if shelf else "一起上传多款商品的包装正面、营养成分表、配料表或价签。每款商品会生成独立草稿。")
    files = st.file_uploader(f"选择照片（最多 {MAX_BATCH_PHOTOS} 张）", type=["jpg", "jpeg", "png", "webp"],
                             accept_multiple_files=True, key="batch_files")
    shot = None
    if st.toggle("打开相机拍货架或标签", key="batch_camera_open"):
        shot = st.camera_input("拍摄货架或包装", key="batch_shot")
    photos = [*files, *([shot] if shot else [])]
    if len(photos) > MAX_BATCH_PHOTOS:
        st.warning(f"请将本批照片减少至 {MAX_BATCH_PHOTOS} 张以内。")
    if not settings.api_key:
        st.caption("当前可用现场手动录入或演示商品；配置百灵后可自动识别多款商品。")
    first, second = st.columns(2)
    if first.button("识别本批商品", key="batch_scan", type="primary",
                    disabled=not settings.api_key or not 1 <= len(photos) <= MAX_BATCH_PHOTOS):
        original_photos = tuple(photo.getvalue() for photo in photos)
        try:
            with st.spinner("正在区分商品、价格和标签来源…"):
                labels = recognize_products(list(original_photos), settings)
            added = []
            for label in labels:
                if any(r.original.name == label.name and r.photos == original_photos for r in basket.values()):
                    continue
                item = Product(label, "货架识别" if shelf else "多商品识别", original_photos)
                basket[item.uid] = item
                added.append(item.uid)
            if added:
                st.session_state.basket_product = added[0]
                st.success(f"新增 {len(added)} 款待核对商品。")
            elif labels:
                st.info("这批照片中的商品已在当前清单。")
            else:
                st.warning("没有辨认出独立商品，请补拍品名和价签或手动录入。")
        except VisionError as error:
            st.error(str(error))
    if second.button("手动添加商品", key="basket_manual", disabled=len(photos) > MAX_BATCH_PHOTOS):
        item = Product(label_from_payload({}), "人工录入", tuple(photo.getvalue() for photo in photos))
        basket[item.uid] = item
        st.session_state.basket_product = item.uid
    if not basket and st.button("体验三款演示饮料", key="basket_demo"):
        for item in demo_products():
            basket[item.uid] = item


def select_product(basket):
    if not basket:
        return None
    def describe(uid):
        item = basket[uid]
        name = item.label.name or "待补充品名"
        status = "已核对" if item.confirmed else "待核对"
        return f"{name} · {item.source} · {status}"

    uid = st.selectbox("选择商品核对或修改", list(basket), key="basket_product", format_func=describe)
    item = basket[uid]
    if st.button("从候选清单移除这款", key="remove_candidate"):
        del basket[uid]
        st.rerun()
    return item

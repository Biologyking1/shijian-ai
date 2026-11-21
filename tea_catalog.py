"""Published fresh-tea servings. Nutrients refer to one whole order."""

import json
import math
import unicodedata
from bisect import bisect_left
from copy import deepcopy
from pathlib import Path


GRADE_RULE_NAME = "中国营养学会 T/CNSS 045—2025《现制饮料营养选择标识规范》表 1"
GRADE_RULE_SOURCE = "https://www.cnsoc.org/notice/files/%40CmsXh_ec3afa08-6f83-482b-aa2c-d8526166f73e.pdf"
GRADE_SUGAR_FIELD = "grade_sugar"
SHANGHAI_MENU = "https://mzj.sh.gov.cn/lnb-xw/20240415/fb979f6266cc4bd39483ca8b1652af61.html"
SHANGHAI_ORDER = "https://news.xinmin.cn/2024/03/03/32599845.html"
MISSING_TEA = "https://www.missingtea.com.tw/upload/web/2026NutritionFacts-0122.pdf"
BRAND_LOOKUP = {
    "霸王茶姬": "https://qmproductcomput.bwcj.com/",
    "喜茶": "https://www.heytea.com/",
    "奈雪的茶": "https://www.naixue.com/",
    "清心福全": "https://www.chingshin.tw/product/fresh-milk-tea",
    "思茶": MISSING_TEA,
}


def _record(brand, name, kind, size, sugar, temp, *, region, scope, source, date,
            kcal=None, grade=None, volume=None, total_sugar=None, protein=None,
            **details):
    return {
        "brand": brand, "name": name, "kind": kind, "size": size, "sugar": sugar,
        "temp": temp, "toppings": [], "region": region, "scope": scope,
        "source": source, "date": date, "kcal": kcal, "volume": volume,
        "total_sugar": total_sugar, "protein": protein, "grade": grade,
        "grade_scheme": "上海疾控 2024 年试点" if grade else None,
        "grade_source": source if grade else None, **details,
    }


CATALOG = [
    _record("霸王茶姬", "伯牙绝弦", "鲜奶茶", "中杯", "不另外加糖", "标准冰",
            region="中国大陆", scope="中国大陆 · 2023 年品牌计算器公开示例，整杯约值",
            source="https://www.bbtnews.com.cn/2023/0908/488706.shtml",
            date="2023-09-08", kcal=130, protein=2.8, carbs=6.7),
    _record("霸王茶姬", "伯牙绝弦", "鲜奶茶", "中杯", "少糖", "报道未列冰量",
            region="中国大陆", scope="上海 · 2024 年 3 月点单示例，冰量未披露",
            source=SHANGHAI_ORDER, date="2024-03-03", grade="B"),
    _record("霸王茶姬", "伯牙绝弦", "鲜奶茶", "报道未列杯型", "标准糖", "报道未列冰量",
            region="中国大陆", scope="上海 · 2024 年 4 月实访，杯型及温度未披露",
            source=SHANGHAI_MENU, date="2024-04-15", grade="C"),
    *[_record("霸王茶姬", name, "纯茶", "中杯", "不另外加糖", "冷饮",
              region="中国大陆", scope="上海 · 2024 年 3 月点单示例，仅注明冷饮",
              source=SHANGHAI_ORDER, date="2024-03-03", grade="A")
      for name in ("酌红袍", "云中绿")],
    _record("奈雪的茶", "龙井知春", "纯茶", "报道未列杯型", "报道未列甜度", "报道未列冰量",
            region="中国大陆", scope="上海前滩铁狮门店 · 2024 年 4 月，报道未列具体定制选项",
            source="https://www.xinhuanet.com/food/20240425/231e651e65414afcbefc98be74aa576d/c.html",
            date="2024-04-25", grade="B", kcal=69),
    _record("喜茶", "减脂小奶茉", "鲜奶茶", "检测报道未列杯型", "检测报道未列甜度", "检测报道未列冰量",
            region="中国大陆", scope="中国大陆 · SGS 公布了 GI 检测，热量与等级待查喜茶 GO",
            source="https://www.sgsonline.com.cn/case/article/detail-5482.html", date="2025-01-22"),
    _record("喜茶", "多肉葡萄冻", "果茶", "报道未列杯型", "报道未列甜度", "推荐冰量",
            region="中国大陆", scope="中国大陆 · 2023 年电子配料表，整杯约值，杯型及糖度未披露",
            source="https://xinwen.bjd.com.cn/content/s653b7235e4b0ec2b81cea2b6.html",
            date="2023-10-26", kcal=140, carbs=34),
]

# Brands report both sizes independently. Never scale a medium cup to a large.
for name, kind, slug, medium, large in (
    ("鲜奶茶", "鲜奶茶", "fresh-milk-tea", (247, 40), (375, 61)),
    ("珍珠奶茶", "珍珠奶茶", "pearl-milk-tea", (475, 33), (720, 50)),
    ("乌龙奶茶", "经典奶茶", "oolong-milk-tea", (417, 38), (633, 58)),
):
    url = f"https://www.chingshin.tw/product/{slug}"
    for size, (kcal, sugar_g) in (("中杯", medium), ("大杯", large)):
        CATALOG.append(_record(
            "清心福全", name, kind, size, "少糖", "正常冰",
            region="中国台湾", scope="中国台湾 · 品牌官网正常冰配方，该品最高甜度为少糖",
            source=url, date="2026-11-20 核对", kcal=kcal, total_sugar=sugar_g,
            topping_options=["珍珠", "粉圆", "椰果", "布丁", "仙草冻", "暗黑水晶"] if name == "乌龙奶茶" else [],
            toppings_source=url if name == "乌龙奶茶" else None,
        ))

for name, kind, medium, large in (
    ("醇厚红茶拿铁", "鲜奶茶", (199, 32), (258, 41)),
    ("黑糖红茶拿铁", "鲜奶茶", (334, 68), (434, 88)),
    ("珍珠淡雅奶茶", "珍珠奶茶", (572, 45), (743, 54)),
    ("鲜柠檬清茶", "果茶", (196, 43), (255, 56)),
):
    for size, (kcal, sugar_g) in (("中杯", medium), ("大杯", large)):
        CATALOG.append(_record(
            "思茶", name, kind, size, "全糖", "去冰", region="中国台湾",
            scope="中国台湾 · 品牌 2026 年现场调饮表，热量及总糖为全糖去冰的最高标示值",
            source=MISSING_TEA, date="2026-01", kcal=kcal, total_sugar=sugar_g,
            value_type="最高标示值",
        ))


CATALOG[:0] = json.loads(Path(__file__).with_name("chagee_snapshot.json").read_text(encoding="utf-8"))


def _normalize(text):
    return "".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())


def exact_match(brand, name):
    """Return exact brand AND product candidates. Caller must confirm the serving."""
    brand, name = _normalize(brand), _normalize(name)
    return [deepcopy(row) for row in CATALOG
            if _normalize(row["brand"]) == brand and _normalize(row["name"]) == name]


def grade_drink(grade_sugar, saturated_fat, trans_fat, sweetener):
    """Use g/100 mL. Sugar is fructose + glucose + sucrose + maltose (§3.4)."""
    items = {"四种糖之和": grade_sugar, "饱和脂肪": saturated_fat, "反式脂肪酸": trans_fat}
    missing = [key for key, value in items.items() if value is None]
    if sweetener is None:
        missing.append("是否使用甜味剂")
    if missing:
        return None, "缺少" + "、".join(missing) + "，无法推算。"
    if type(sweetener) is not bool:
        return None, "请确认是否使用 GB 2760 中的甜味剂。"
    for key, value in items.items():
        if type(value) not in (int, float) or value < 0 or (isinstance(value, float) and not math.isfinite(value)):
            return None, f"请核对{key}的每 100 mL 克数。"
    # Each merged cell in Table 1 sets the first permissible (best) class.
    grades = {
        "四种糖之和": "ABCD"[bisect_left((0.5, 5, 11.5), grade_sugar)],
        "饱和脂肪": "ABD"[bisect_left((0.75, 2.5), saturated_fat)],
        "反式脂肪酸": "C" if trans_fat > 0.3 else "A",
        "甜味剂": "B" if sweetener else "A",
    }
    grade = max(grades.values())
    reasons = "、".join(key for key, rating in grades.items() if rating == grade)
    return grade, f"按{GRADE_RULE_NAME}推算，决定等级的指标为{reasons}。"

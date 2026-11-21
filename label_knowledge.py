"""Explain transcribed label text and compare it with the user's stated preferences."""
import re
import unicodedata
from math import isclose

from nutrition import Basis, NUTRIENTS, FoodLabel, portion_reference, scale_nutrients


NUTRITION_STANDARD = "https://www.nhc.gov.cn/sps/c100088/201111/714fdca49f15450580fc03a2ee3163f9/files/1732844863395_24655.pdf"
TRANSITION = "https://www.nhc.gov.cn/sps/c100087/202509/470fa4ff5de14dd38619223cce9da4e7.shtml"
ALLERGEN_GUIDE = "https://www.nhc.gov.cn/zwgk/zcjd/201402/544c0539b95d4d35b99ffbc105579071.shtml"
STANDARDS_DATABASE = "https://sppt.cfsa.net.cn:8086/db"

MILK = r"牛奶|牛乳|生乳|羊奶|羊乳|驼乳|乳粉|奶粉|乳清|酪蛋白|酪朊酸|奶酪|奶油|黄油|炼乳|酸奶|酸乳|乳蛋白|乳制品|奶制品|乳固体|奶源|(?<![a-z])(?:milk|whey|casein)(?![a-z])"
EGG = r"鸡蛋|鸭蛋|鹌鹑蛋|鹅蛋|蛋粉|蛋清|蛋黄|蛋液|蛋制品|卵白蛋白|(?<![a-z])eggs?(?![a-z])"
SOY = r"大豆|黄豆|豆腐|豆浆|豆乳|黄豆酱|(?<![a-z])soy(?:bean)?s?(?![a-z])"
WHEAT = r"小麦|斯佩耳特麦|面筋|普通面粉|高筋面粉|低筋面粉|中筋面粉|(?<![a-z])wheat(?![a-z])"
FISH = r"鱼(?!香|腥草)|魚|鲑|鳕|鲣|鲭|鳗|(?<![a-z])fish(?![a-z])"
CRUSTACEAN = r"虾|蟹|磷虾|甲壳类|甲壳动物|(?<![a-z])(?:shrimp|prawn|crab)s?(?![a-z])"
MOLLUSK = r"贝类|贝肉|扇贝|牡蛎|蚝油|贻贝|文蛤|鱿鱼|乌贼|章鱼|软体动物"
NUTS = r"坚果|木本坚果|树坚果|核桃|腰果|榛子|榛果|扁桃仁|巴旦木|杏仁|夏威夷果|碧根果|开心果|松子|巴西坚果"
ALLERGEN_PATTERNS = {
    "乳及乳制品": MILK, "蛋类": EGG, "大豆": SOY, "花生": r"花生|落花生|peanuts?",
    "坚果": NUTS, "小麦": WHEAT, "甲壳类": CRUSTACEAN, "鱼类": FISH,
    "芝麻": r"芝麻|胡麻|sesame", "软体贝类": MOLLUSK,
}
ALLERGEN_OPTIONS = tuple(ALLERGEN_PATTERNS)
DIET_OPTIONS = ("纯素", "蛋奶素", "无麸质", "避免添加糖", "限制乳糖")
SUCROSE = r"白砂糖|绵白糖|冰糖|红糖|黑糖|蔗糖|砂糖"
ADDED_SUGARS = SUCROSE + r"|白糖|果葡糖浆|葡萄糖浆|麦芽糖浆|玉米糖浆|糖浆|果糖|葡萄糖|麦芽糖|蜂蜜|海藻糖"
PRESERVATIVES = r"山梨酸钾|苯甲酸钠|脱氢乙酸钠|丙酸钙|双乙酸钠|纳他霉素|乳酸链球菌素"
SWEETENERS = r"三氯蔗糖|赤藓糖醇|木糖醇|麦芽糖醇|山梨糖醇|阿斯巴甜|甜菊糖苷|安赛蜜|乙酰磺胺酸钾|甜蜜素"
MEAT = r"猪肉|牛肉|羊肉|鸡肉|鸭肉|猪油|牛油|鸡油|鸡粉|肉粉|肉松|肉汤|骨汤|明胶|吉利丁|火腿|培根|鸡胸|猪骨|牛骨"
ANIMAL = "|".join([MEAT, MOLLUSK, FISH, CRUSTACEAN])
GLUTEN = WHEAT + r"|黑麦|大麦|青稞|裸麦|麸质"
DIET_PATTERNS = {
    "纯素": "|".join([ANIMAL, MILK, EGG, "蜂蜜|蜂王浆|虫胶|胭脂虫红"]),
    "蛋奶素": ANIMAL, "无麸质": GLUTEN, "避免添加糖": ADDED_SUGARS,
    "限制乳糖": r"(?<!无)(?<!低)(?<!零)(?<!0)乳糖(?!酶|醇)",
}

# Exact aliases keep compound names such as 三氯蔗糖 distinct from 蔗糖.
_NOTES = [
    ("水 饮用水 纯净水", "作液体基底或用于溶解其他配料。", "饮用水或经处理的水。", "其他配料和营养表决定这瓶饮品的糖和能量。"),
    ("白砂糖 白糖 蔗糖 绵白糖 冰糖 红糖", "提供甜味，也影响质地。", "通常来自甘蔗或甜菜。", "查看糖一栏和实际份量，单凭配料次序无法算出克数。"),
    ("果葡糖浆 玉米糖浆 葡萄糖浆 麦芽糖浆", "增甜，也能保湿或调节稠度。", "常由淀粉加工为含单糖或双糖的糖浆。", "属于配方中的糖来源，可结合糖和碳水化合物两栏阅读。"),
    ("蜂蜜", "增甜并带来蜂蜜风味。", "蜜蜂采集花蜜等酿成。", "作为配料使用时也会带入糖，纯素者通常会避开。"),
    ("食盐 食用盐 精制盐 海盐", "调咸味。", "主要成分是氯化钠。", "看钠一栏可以合并考虑盐及其他含钠配料。"),
    ("谷氨酸钠 味精", "增强鲜味。", "常由发酵制得谷氨酸，再制成钠盐。", "会带入钠，实际克数看营养表。"),
    ("红茶 绿茶 茶叶 茶粉 红茶粉", "提供茶的颜色、香气和滋味。", "茶树叶经不同工艺制成。", "通常含咖啡因，实际含量要看产品资料。"),
    ("柠檬汁 浓缩柠檬汁", "提供酸味和果汁风味。", "由柠檬榨汁，浓缩汁还去除了部分水。", "含量要看果汁比例标示。"),
    ("牛奶 牛乳 生牛乳 乳粉 全脂乳粉 脱脂乳粉 奶粉", "提供乳香、蛋白质和其他乳固体。", "来自乳；乳粉再经脱水制成。", "涉及乳过敏。乳糖含量需另查，脱脂仅指脂肪。"),
    ("乳清粉 乳清蛋白 乳清蛋白粉", "提供乳固体或补充蛋白质。", "从乳清干燥、分离或浓缩得到。", "涉及乳过敏。不同产品残留乳糖量有差异。"),
    ("酪蛋白 酪蛋白酸钠 酪朊酸钠", "提供乳蛋白或帮助分散油脂。", "来源为乳中的酪蛋白。", "在植脂末等复合配料中也可能出现，涉及乳过敏。"),
    ("大豆蛋白 大豆分离蛋白", "提供蛋白质并调节质地。", "从大豆提取或分离。", "涉及大豆过敏。"),
    ("大豆磷脂", "帮助油和水混合。", "来源为大豆。", "大豆过敏者请核对包装提示。"),
    ("卵磷脂 磷脂", "常作乳化剂。", "可来自大豆、葵花籽、蛋黄等，名称本身未指明来源。", "有相应过敏或纯素要求时可向厂家核实。"),
    ("明胶 吉利丁", "形成凝胶或改善质地。", "由动物组织中的胶原制得；物种需厂家说明。", "纯素、蛋奶素或特定动物来源限制者需留意。"),
    ("黄原胶", "增稠并改善悬浮稳定性。", "由微生物发酵糖类原料得到。", "配料名称无法给出添加量。"),
    ("卡拉胶", "增稠、凝胶或稳定乳化体系。", "从红藻提取。", "是否允许用于该食品及用量需结合食品类别查标准。"),
    ("果胶", "帮助果酱等食品凝胶或稳定质地。", "常从柑橘皮、苹果渣等提取。", "含有果胶无法证明食品中的果汁比例。"),
    ("羧甲基纤维素钠 纤维素胶", "增稠并稳定食品质地。", "由纤维素加工制成的衍生物。", "实际用量需看配方资料。"),
    ("柠檬酸", "调节酸度。", "可由微生物发酵制得，也天然存在于多种水果中。", "名称无法证明产品含柠檬汁。"),
    ("柠檬酸钠", "调节酸度、缓冲酸味。", "柠檬酸的钠盐。", "可带入钠，总量看营养表。"),
    ("山梨酸钾 苯甲酸钠 丙酸钙", "用于防腐，帮助抑制特定微生物。", "分别为相应有机酸的盐。", "适用范围和限量随添加剂、食品类别而变化。"),
    ("三氯蔗糖", "以很小用量提供甜味。", "以蔗糖为起始原料加工制成的甜味剂。", "应与白砂糖区分，核对总糖还需看营养表。"),
    ("赤藓糖醇 木糖醇 麦芽糖醇 山梨糖醇", "提供甜味或改善口感。", "属于糖醇，具体原料与工艺随品种而异。", "含糖醇的食品也可能有其他碳水来源。"),
    ("阿斯巴甜", "以很小用量提供甜味。", "由氨基酸衍生物制成。", "含苯丙氨酸，苯丙酮尿症患者需核对标签提示。"),
    ("安赛蜜 乙酰磺胺酸钾 甜菊糖苷", "以很小用量提供甜味。", "甜菊糖苷通常源于甜叶菊；安赛蜜为合成甜味剂。", "成品仍可能含糖，查看糖一栏。"),
    ("食用香精 食品用香精", "提供或增强香气。", "由香料和其他辅料配制，配方可有多种来源。", "水果风味不能证明含有相应水果。"),
    ("麦芽糊精", "提供载体、增加固形物或调节口感。", "由淀粉部分水解制得，淀粉来源可不同。", "会贡献碳水化合物。"),
    ("全麦粉 小麦粉 面粉", "为面食、饼干等提供结构和淀粉。", "通常由小麦磨制；全麦粉保留胚乳、胚芽和麸皮。", "涉及小麦和麸质，关注配方中全麦粉比例。"),
    ("淀粉 玉米淀粉 马铃薯淀粉 木薯淀粉", "增稠或构成食品骨架。", "从谷物或块茎等植物取得，具体来源看名称。", "计入碳水化合物，单写淀粉时来源仍需确认。"),
    ("鸡蛋 蛋黄 蛋清 全蛋粉", "提供结构、乳化性或蛋白质。", "来自禽蛋。", "涉及蛋类过敏，纯素者需留意。"),
    ("棕榈油 菜籽油 葵花籽油 大豆油 植物油", "提供脂肪或改善香气和口感。", "从相应的植物油料提取。", "总脂肪和饱和脂肪以营养表为准。"),
    ("抗坏血酸 维生素C", "可补充维生素 C，也可用于抗氧化。", "为维生素 C，商业制备可使用发酵工艺。", "实际功能和含量可查包装标示。"),
]
INGREDIENT_NOTES = {name.casefold(): (role, source, caution)
                    for aliases, role, source, caution in _NOTES for name in aliases.split()}


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def ingredient_entries(ingredients: str) -> list[str]:
    text = re.sub(r"^\s*(?:配料表?|原料表?)\s*:\s*", "", _clean(ingredients))
    entries = []
    for part in re.split(r"[、,;；。\n:()（）\[\]【】]+", text):
        name = re.sub(r"\s*[≥≤<>]?\s*\d+(?:\.\d+)?\s*%\s*$", "", part).strip()
        if name and name not in entries:
            entries.append(name)
    return entries


def ingredient_note(name: str) -> tuple[str, str, str]:
    return INGREDIENT_NOTES.get(_clean(name).casefold(), (
        "本地词条暂未收录此名称，请先核对包装上的完整名称和括号内子配料。",
        "原料来源待确认，可凭完整名称、产品及批次向生产商查询。",
        "如果标为食品添加剂，可在下方标准平台按名称检索 GB 2760；需结合食品类别核对。",
    ))


# Keep the scope of coordinated lists, e.g. "不含花生、芝麻；可能含牛奶和大豆".
_MARKER = re.compile(
    r"(?P<possible>不(?:能)?保证不含有?|不能排除|无法排除|不排除|可能(?:含有?|带入|存在)?|或含有?|"
    r"(?:生产线|生产设备|设备|车间|工厂)[^,;。]{0,18}?(?:加工|生产|处理)(?:过|含有?)?|"
    r"同线|共线|共用|may\s+(?:also\s+)?contain|shared\s+(?:equipment|facility))"
    r"|(?P<absent>不含有?|未含有?|无(?=麸质)|does\s+not\s+contain|free\s+from)"
    r"|(?P<negative>无添加|不添加|未添加|未检出|不使用)"
    r"|(?P<present>含有|含(?=[乳奶蛋虾鱼小花大坚芝])|(?<![a-z])contains?\b)", re.I,
)
_NO_CONTACT = re.compile(
    r"不(?:与|和)(?P<shared>[^，,;。并]{1,45}?)(?:共线|同线|共用(?:设备|生产线))"
    r"|不(?:处理|加工|生产)(?P<dedicated>[^，,;。并]{1,45}?)的专(?:用生产)?线"
    r"|(?:本厂|本工厂|本车间|本生产线)不(?:处理|加工)(?P<facility>[^,;。并]{1,45})"
)


def _declaration_parts(text: str):
    named_no_contact = []
    def capture(match):
        named_no_contact.append(match[match.lastgroup])
        return ";"
    other = _NO_CONTACT.sub(capture, _clean(text))
    return list(_segments(other)), named_no_contact


def _product_gluten_free(label: FoodLabel) -> bool:
    # Only accept a stand-alone product declaration. A supplier's cert for a
    # single ingredient, or a negated claim, does not describe the finished food.
    return any(re.fullmatch(r"(?:本品|本产品)?(?:已获(?:得)?)?(?:认证)?(?:无麸质|不含麸质|gluten[- ]free)"
                            r"(?:产品|食品|认证)?[。！!]?", _clean(part), re.I)
               for text in [*label.claims, label.allergen_text]
               for part in re.split(r"[,，。;；\n]", text))


def _segments(text: str):
    text = re.sub(r"无麸质(?=燕麦|大米|小麦|面粉)", "", text)
    for clause in re.split(r"[;。\n.!！]+", _clean(text)):
        # "无乳糖牛奶" describes a dairy ingredient. A bare "无" is therefore
        # restricted to entire declarations here instead of negating arbitrary names.
        clause = re.sub(r"^\s*无(?=(?:花生|坚果|牛奶|乳制品|鸡蛋|大豆|芝麻|小麦)(?:成分)?\s*$)", "不含", clause)
        clause = re.sub(r"\b(milk|dairy|egg|soy|wheat|peanut|gluten)[ -]free\b",
                        r"free from \1", clause, flags=re.I)
        state, start = "present", 0
        for marker in _MARKER.finditer(clause):
            content = clause[start:marker.start()]
            if marker.lastgroup == "present" and state == "possible" and not re.search(r"[,，]", content):
                continue
            if content.strip():
                yield state, content
            state, start = marker.lastgroup, marker.end()
        if clause[start:].strip():
            yield state, clause[start:]


def _hit(pattern: str, text: str) -> str:
    if pattern in (SUCROSE, ADDED_SUGARS):
        text = re.sub(SWEETENERS + r"|低聚果糖|低聚麦芽糖|葡萄糖酸[钠钙锌]|聚葡萄糖", " ", text)
    if pattern == FISH:
        text = re.sub(r"鱿鱼|章鱼|墨鱼|鲍鱼|娃娃鱼", " ", text)
    if MILK in pattern:
        text = re.sub(r"植物奶油|可可黄油|椰子奶粉|椰奶粉", " ", text)
    # Short allergen group names occur alone in allergen declarations.
    short = []
    if MILK in pattern:
        short.extend(["乳", "奶"])
    if EGG in pattern:
        short.append("蛋")
    if WHEAT in pattern:
        short.append("面粉")
    if short:
        boundaries = r"(?:^|[、,:\s和及与])(" + "|".join(short) + r")(?=$|[、,:\s和及与类])"
        simple = re.search(boundaries, text)
        if simple:
            return simple[1]
    match = re.search(pattern, text, re.I)
    return match[0] if match else ""


def _evidence(pattern: str, pieces) -> tuple[str, str]:
    possible = ""
    for state, text in pieces:
        if state in ("negative", "absent"):
            continue
        name = _hit(pattern, text)
        if name and state == "present":
            return "present", name
        if name:
            possible = name
    return ("possible", possible) if possible else ("", "")


def watch_alerts(label: FoodLabel, prefs: dict) -> list[str]:
    aliases = {
        "味精": r"味精|谷氨酸钠", "谷氨酸钠": r"味精|谷氨酸钠",
        "代糖": SWEETENERS, "甜味剂": SWEETENERS, "防腐剂": PRESERVATIVES,
        "蔗糖": SUCROSE, "添加糖": ADDED_SUGARS, "食盐": r"食盐|食用盐|氯化钠",
    }
    declarations, _ = _declaration_parts(label.allergen_text)
    pieces = list(_segments(label.ingredients)) + declarations
    return [term for term in prefs.get("watch", []) if term.strip() and
            _evidence(aliases.get(_clean(term), re.escape(_clean(term))), pieces)[0]]


def _partial_ingredients(label: FoodLabel) -> bool:
    return not label.ingredients.strip() or bool(
        re.search(r"配料|原料|过敏|致敏|不完整|截断|缺页", label.unreadable) or
        re.search(r"看不清|模糊|未知|不详|无法辨认|不全|不完整|缺失|[…?？]|\.\.\.",
                  label.ingredients + " " + label.allergen_text)
    )


def restriction_check(label: FoodLabel, prefs: dict) -> tuple[list[str], list[str]]:
    """Return exclusions and outstanding evidence separately for a shopping comparison."""
    blocked, unresolved = [], []
    ingredients = list(_segments(label.ingredients))
    declarations, noncontact = _declaration_parts(label.allergen_text)
    for option in prefs.get("allergens", []):
        if not _clean(option):
            continue
        pattern = ALLERGEN_PATTERNS.get(option, re.escape(_clean(option)))
        state, name = _evidence(pattern, ingredients + declarations)
        if state == "present":
            blocked.append(f"{option}过敏提醒：配料或致敏原提示列有「{name}」。")
        elif state == "possible":
            blocked.append(f"{option}过敏提醒：包装提示可能接触「{name}」，请避开或先向厂家确认。")
        elif option not in ALLERGEN_PATTERNS:
            unresolved.append(f"{option}过敏：仅按自定义名称核对，其他别名、衍生原料及交叉接触需人工确认。")
        elif not label.allergen_text.strip() or _partial_ingredients(label):
            unresolved.append(f"{option}过敏：需补充完整配料及致敏物质提示，核实交叉接触。")
        elif not (any(state == "absent" and _hit(pattern, text) for state, text in declarations)
                  and any(_hit(pattern, name) for name in noncontact)):
            unresolved.append(f"{option}过敏：需核实产品是否含该原料，以及生产线是否共线加工。")

    for option in prefs.get("diets", []):
        pattern = DIET_PATTERNS.get(option)
        if not pattern:
            unresolved.append(f"{option}尚无本地筛查规则，请人工核对。")
            continue
        pieces = ingredients if option in ("限制乳糖", "避免添加糖") else ingredients + declarations
        state, name = _evidence(pattern, pieces)
        if state == "present":
            blocked.append(f"{option}：标签列有「{name}」，请按你的饮食要求避开或确认用量。")
        elif state == "possible":
            unresolved.append(f"{option}：包装提示可能接触「{name}」，请核实。")
        elif _partial_ingredients(label):
            unresolved.append(f"{option}：配料或提示不完整，需补全后再判断。")
        elif option == "限制乳糖" and _evidence(MILK, ingredients)[0]:
            unresolved.append("限制乳糖：含乳原料的剩余乳糖量需看专门标示，并结合个人耐受量。")
        elif option == "无麸质" and not _product_gluten_free(label):
            unresolved.append("无麸质：核对无麸质标示、燕麦等原料来源和生产线交叉接触。")
        elif option in ("蛋奶素", "纯素") and any(
                re.search(r"香精|磷脂|酶制剂|脂肪酸甘油酯|复合|调味料|甘油|起酥油|植脂末|人造奶油|奶精", text)
                for state, text in ingredients if state == "present"):
            unresolved.append(f"{option}：部分配料的原料来源未展开，需向厂家确认。")
    return blocked, unresolved


# GB 28050—2011 Annex C. High-protein and high-fibre rules also accept
# an energy-normalized concentration, handled separately below.
_UPPER_LIMITS = (
    (r"(?:0|零|无|不含)糖(?!添加|精|醇)", "零糖", "sugar", 0.5, 0.5),
    (r"低糖", "低糖", "sugar", 5, 5),
    (r"(?:0|零|无|不含)脂(?:肪)?", "零脂肪", "fat", 0.5, 0.5),
    (r"低脂(?:肪)?", "低脂肪", "fat", 3, 1.5),
    (r"(?:0|零|无|不含)(?:反式脂肪酸?|反式脂肪|反式)", "零反式脂肪", "trans_fat", 0.3, 0.3),
    (r"(?:0|零|无|不含)(?:盐|钠)", "无钠（盐）", "sodium", 5, 5),
    (r"极低(?:盐|钠)", "极低钠（盐）", "sodium", 40, 40),
    (r"(?<!极)低(?:盐|钠)", "低钠（盐）", "sodium", 120, 120),
)


def _per_hundred(label: FoodLabel, nutrient: str) -> tuple[float, str] | None:
    reference = portion_reference(label)
    if not reference or reference[1] not in ("g", "mL") or nutrient not in label.nutrients:
        return None
    return scale_nutrients(label, 100, reference[1])[nutrient], reference[1]


def _missing(nutrient: str) -> str:
    return f"缺少可用于换算的{NUTRIENTS[nutrient][0]}数值或标示基准。请核对每 100 g/mL 一栏，按份标示时还需每份克数或毫升数。"


def _upper_check(label: FoodLabel, title: str, nutrient: str, solid: float, liquid: float) -> str:
    reading = _per_hundred(label, nutrient)
    if reading is None:
        message = _missing(nutrient)
    else:
        value, unit = reading
        threshold = solid if unit == "g" else liquid
        n_name, n_unit = NUTRIENTS[nutrient]
        verdict = "落在" if value <= threshold else "超出"
        message = f"标签折合每 100 {unit} 含{n_name} {value:g} {n_unit}，{verdict}参考上限 {threshold:g} {n_unit}。"
        if solid != liquid:
            message += f"按{'固体' if unit == 'g' else '液体'}口径试算，请核实食品形态。"
    if nutrient == "sugar":
        source = _evidence(ADDED_SUGARS, _segments(label.ingredients))[1]
        if source:
            message += f"配料列有「{source}」，单凭配料名称无法算出总糖量。"
        elif reading is None:
            message += "碳水化合物总量无法代替糖值。"
    return f"{title} · {message}"


def _high_check(label: FoodLabel, nutrient: str, solid: float, liquid: float, by_energy: float) -> str:
    """Apply all three alternative bases; energy comparison can use a labeled serving."""
    name = NUTRIENTS[nutrient][0]
    reading = _per_hundred(label, nutrient)
    energy = label.nutrients.get("energy")
    per_energy = None
    if energy and nutrient in label.nutrients:
        per_energy = label.nutrients[nutrient] * 420 / energy
    evidence, matches = [], []
    if reading is not None:
        value, unit = reading
        limit = solid if unit == "g" else liquid
        evidence.append(f"按{'固体' if unit == 'g' else '液体'}试算，每 100 {unit} 为 {value:g} g，参考下限 {limit:g} g")
        matches.append(value >= limit)
    if per_energy is not None:
        evidence.append(f"每 420 kJ 为 {per_energy:.2f} g，参考下限 {by_energy:g} g")
        matches.append(per_energy >= by_energy)
    if any(matches):
        result = "达到其中一个参考条件。"
    elif reading is None or per_energy is None:
        result = "缺少完整的含量、重量/体积基准或同列能量值，尚不能核对全部条件。"
    else:
        result = "按上述形态和能量口径均低于参考下限。"
    return f"高{name} · " + ("；".join(evidence) + "。" if evidence else "") + result


def _ingredient_claim(label: FoodLabel, title: str, pattern: str, needed: str) -> str:
    state, name = _evidence(pattern, _segments(label.ingredients))
    if state == "present":
        return f"{title} · 配料列有「{name}」，与这项说法存在需要复核的线索。{needed}"
    if state == "possible":
        return f"{title} · 标签仅提示可能接触「{name}」，不能据此判断生产时是否添加。{needed}"
    return f"{title} · 当前配料文字未见已收录的对应名称。{needed}"


_CLAIM_NAMES = {value[0]: key for key, value in NUTRIENTS.items()}
_CLAIM_NAMES.update({"总糖": "sugar", "糖分": "sugar", "反式脂肪酸": "trans_fat", "饱和脂肪酸": "sat_fat"})
_AMOUNT = r"\d+(?:\.\d+)?"
_MEASURE = re.compile(rf"每(?:(?P<size>{_AMOUNT})(?P<unit>毫升|ml|克|g)|(?P<item>份|瓶|袋|包|盒|罐))")
_VALUE = re.compile(
    r"(?<!蔗)(?<!乳)(?<!果)(?<!麦芽)(?<!添加)(?P<nutrient>"
    + "|".join(sorted(_CLAIM_NAMES, key=len, reverse=True))
    + rf")(?:含量)?(?:为|约为|约|达|[:=])?(?P<amount>{_AMOUNT})(?P<unit>千焦|千卡|毫克|克|kj|kcal|mg|g)"
)


def _one_amount_claim(label, part, measure, reading):
    name = reading["nutrient"]
    nutrient = _CLAIM_NAMES[name]
    if not measure:
        return f"{name}含量 · 宣传语未注明每份、整包或每 100 g/mL 的基准，需补充原文。"
    if nutrient not in label.nutrients:
        return f"{name}含量 · 营养表缺少{name}一栏，需补充标示值。"
    if ("冲调后" in part and label.label_state != "prepared") or (
            "冲调前" in part and label.label_state != "as_sold"):
        return f"{name}含量 · 宣传所指的冲调状态与已录入的营养表状态尚未对应。"
    item = measure["item"]
    if not item:
        size = float(measure["size"])
        unit = "mL" if measure["unit"] in ("毫升", "ml") else "g"
    elif item == "份":
        size, unit = ((1, "份") if label.basis == Basis.SERVING
                      else (label.serving_size, label.serving_unit))
    else:
        if label.label_state != "as_sold":
            return f"{name}含量 · 每{item}核对需要出售时的营养表及该单件的净含量。"
        size, unit = label.package_size, label.package_unit
    if not size or not unit:
        return f"{name}含量 · 请补充与「每{item or '个标示单位'}」对应的重量或体积。"
    try:
        value = scale_nutrients(label, size, unit)[nutrient]
    except ValueError:
        return f"{name}含量 · 基准或单位无法对应，请核对营养表及所用重量或体积。"
    printed_unit = reading["unit"]
    target_unit = NUTRIENTS[nutrient][1]
    if nutrient == "energy":
        conversions = {"kj": 1, "千焦": 1, "kcal": 4.184, "千卡": 4.184}
    else:
        grams = 1000 if target_unit == "mg" else 1
        conversions = {"g": grams, "克": grams, "mg": grams / 1000, "毫克": grams / 1000}
    if printed_unit not in conversions:
        return f"{name}含量 · 请核对宣传语上{name}的单位。"
    amount = float(reading["amount"]) * conversions[printed_unit]
    verdict = "数值一致" if isclose(amount, value, rel_tol=1e-10, abs_tol=1e-10) else "数值不同"
    return (f"{name}含量 · 「{measure[0]}」按标签折合 {value:g} {target_unit}，"
            f"宣传标示 {amount:g} {target_unit}，{verdict}。请按同一状态及包装单位核实。")


def _quantified_claims(label: FoodLabel, text: str) -> list[str]:
    checks = []
    for part in re.split(r"[,，;；。]", text):
        # A comparator or a range does not assert equality with one amount.
        if re.search(r"减少|增加|降低|减糖|减盐|减脂|不少于|不多于|至少|至多|不高于|不低于|[<>≤≥]|[~-]\d|以上|以下", part):
            continue
        measures = list(_MEASURE.finditer(part))
        for reading in _VALUE.finditer(part):
            before = [measure for measure in measures if measure.end() <= reading.start()]
            checks.append(_one_amount_claim(label, part, before[-1] if before else None, reading))
    return checks


def check_claim(label: FoodLabel, claim: str) -> list[str]:
    text = re.sub(r"\s", "", _clean(claim)).casefold()
    results = _quantified_claims(label, text)
    pieces = list(_segments(label.ingredients))
    formulation = (
        (r"(?:不|未|无|零|0)添(?:加)?(?:蔗糖|白砂糖)|(?:零|0|无)蔗糖添加",
         "未添加蔗糖", SUCROSE, "需核对完整配方和复合配料的来源。其他糖需另查。"),
        (r"(?:不|未|无|零|0)添(?:加)?糖|(?:零|0|无)添加食糖|(?:0|零|无)糖添加|无添加白糖",
         "未添加糖", ADDED_SUGARS, "需核对添加记录和复合配料；天然存在的糖也会计入总糖。"),
        (r"(?:不含|无|0|零)蔗糖(?!添加)",
         "无蔗糖", SUCROSE, "糖一栏通常给出总糖，单项蔗糖含量需专门数据。"),
        (r"(?:不含|不添加|未添加|未用|无添加|无|0添加|零添加|0|零)防腐剂",
         "防腐剂声称", PRESERVATIVES, "需查完整配料、复合配料和生产商工艺资料。"),
        (r"(?:不含|不添加|无添加|无|0添加|零添加|0|零)(?:代糖|甜味剂)",
         "甜味剂声称", SWEETENERS, "需核对完整配方及复合配料的成分。"),
    )
    for pattern, title, ingredient_pattern, needed in formulation:
        if re.search(pattern, text):
            results.append(_ingredient_claim(label, title, ingredient_pattern, needed))
            text = re.sub(pattern, " ", text)
    if re.search(r"不添加|无添加|零添加|0添加", text):
        results.append("添加声称 · 请核实「添加」具体指哪种物质，再核对完整配料和生产记录。")
    if re.search(r"减[少低]?(?:糖|盐|钠|脂|能量)|(?:糖|盐|钠|脂肪|能量)(?:减|降低)", text):
        results.append("比较声称 · 需提供参照食品、同状态同基准的两组数值和声称的变化幅度。")
        text = re.sub(r"减[少低]?(?:糖|盐|钠|脂|能量)", " ", text)
    for pattern, title, nutrient, solid, liquid in _UPPER_LIMITS:
        if re.search(pattern, text):
            results.append(_upper_check(label, title, nutrient, solid, liquid))
    for pattern, nutrient, solid, liquid, energy in (
        (r"(?:高|富含)蛋白", "protein", 12, 6, 6),
        (r"(?:高|富含)(?:膳食)?纤维", "fiber", 6, 3, 3),
    ):
        if re.search(pattern, text):
            results.append(_high_check(label, nutrient, solid, liquid, energy))
    if re.search(r"低卡|零卡|0卡|低热量|(?:零|0|低|无)能量", text):
        energy = _per_hundred(label, "energy")
        number = (f"每 100 {energy[1]} 标示能量 {energy[0]:g} kJ。"
                  if energy else _missing("energy"))
        results.append("能量声称 · " + number + "还需核实食品形态及脂肪供能占比，详见附录 C。")
    if "全麦" in text:
        match = _evidence(r"全麦粉|全小麦粉|全麦", pieces)[1]
        results.append((f"全麦 · 配料列有「{match}」。" if match else "全麦 · 可读配料尚未找到全麦名称。")
                       + "全麦比例要看含量标示或生产商的配方说明。")
    if re.search(r"低乳糖|无乳糖|0乳糖|零乳糖", text):
        results.append("乳糖声称 · 需核对乳品类别、单项乳糖含量和基准。总糖和乳糖酶配料不能直接给出剩余乳糖。")
    if not results:
        results.append("待核实 · 请记录宣传语的具体对象、数值或比较对象，再索取相应配方、含量检测或认证资料。")
    return results


def render_label_checks(label: FoodLabel, prefs: dict) -> None:
    import streamlit as st

    st.subheader("过敏原与饮食提醒")
    if label.allergen_text:
        st.text(label.allergen_text)
    current = prefs.get("allergens") or prefs.get("diets")
    blocked, unresolved = restriction_check(label, prefs)
    for item in blocked:
        st.warning(item)
    for item in unresolved:
        st.info(item)
    if current and not blocked and not unresolved:
        st.write("已核对所选限制，当前文字未匹配已收录的冲突配料。请结合完整包装确认。")
    elif not current:
        st.caption("在个人偏好中选择过敏原或饮食要求，即可对照当前食品。")
    terms = watch_alerts(label, prefs)
    if terms:
        st.info("命中你关注的配料词：" + "、".join(terms) + "。请核对包装原文。")
    st.caption(f"筛查只覆盖已录入文字和已收录别名。过敏者请核对实物标签，必要时向厂家确认交叉接触。[致敏物质标示说明]({ALLERGEN_GUIDE})")

    st.subheader("配料百科")
    entries = ingredient_entries(label.ingredients)
    if entries:
        st.text(label.ingredients)
        selected = st.selectbox("选择要了解的配料", entries)
        for field, value in zip(("常见作用", "常见来源", "阅读提示"), ingredient_note(selected)):
            st.write(f"**{field}**　{value}")
        st.caption(f"资料检索 · [食品安全国家标准数据检索平台]({STANDARDS_DATABASE})")
    else:
        st.caption("录入配料表后，可逐项查看配料的用途和常见来源。")

    st.subheader("包装宣传语核对")
    if label.claims:
        for claim in label.claims:
            st.text(claim)
            for result in check_claim(label, claim):
                st.write(result)
        state = {"as_sold": "出售时", "prepared": "冲调后", "unknown": "未确认"}.get(label.label_state, "未确认")
        st.caption(f"营养表状态为「{state}」。数值试算须与宣传所指食品及状态一致。"
                   "参考范围为中国大陆一般预包装食品 GB 28050—2011。其他市场、特殊食品及采用新版标准的包装须另外核对。"
                   "GB 28050—2025 自 2027 年 3 月 16 日实施。这里呈现标签线索，最终判定还需完整资料。"
                   f" [2011 版附录 C]({NUTRITION_STANDARD}) · [新版实施说明]({TRANSITION})")
    else:
        st.caption("在标签中录入包装正面的宣传原文后，可查看配料或营养数值能支持哪些说法。")

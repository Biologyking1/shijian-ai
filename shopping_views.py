import streamlit as st

from comparison_cards import choose_pair, packaged_nutrition_rows, pair_verdict, render_pair
from label_knowledge import ALLERGEN_OPTIONS, DIET_OPTIONS, watch_alerts
from nutrition import NUTRIENTS, FoodLabel
from shopping import (
    DIMENSIONS, GOALS, STATUS, Decision, active_weights, default_profile, evaluate,
    export_profile, import_profile, nutrition_per_yuan, rank_products, unit_values,
)


FLAVOR_OPTIONS = ["原味", "清淡", "微甜", "柠檬味", "蜜桃味", "草莓味", "巧克力味", "咸香", "微辣", "麻辣"]


def _widget(name: str, initial):
    key = "shopping.pref." + name
    if key not in st.session_state:
        st.session_state[key] = initial
    return key


def _set_profile_widgets(profile):
    for key, value in profile.items():
        if key in {"references", "weights"}:
            for sub_key, sub_value in value.items():
                st.session_state[f"shopping.pref.{key}.{sub_key}"] = sub_value
        else:
            st.session_state["shopping.pref." + key] = value


def _custom_tags(title, name, options, previous):
    options = list(dict.fromkeys([*options, *previous]))
    tags = st.multiselect(title, options, key=_widget(name, previous),
                          accept_new_options=True, max_selections=32, placeholder="选择或输入后按回车")
    return list(dict.fromkeys(x.strip() for x in tags if x.strip()))


def profile_panel() -> dict:
    prefs = st.session_state.get("shopping.profile", default_profile())
    with st.expander("我的选购偏好 · 预算、营养、口味和限制"):
        if st.checkbox("从本地文件导入偏好", key="shopping.import.open"):
            upload = st.file_uploader("选择偏好 JSON 文件", type=["json"], key="shopping.import.file")
            if st.button("应用导入的偏好", disabled=upload is None, key="shopping.import.apply"):
                try:
                    if upload.size > 32_768:
                        raise ValueError("偏好文件超过 32 KB。")
                    imported = import_profile(upload.getvalue())
                except ValueError as error:
                    st.error(str(error))
                else:
                    prefs = imported
                    _set_profile_widgets(imported)
                    st.success("已应用文件中的选购偏好。")

        budget = st.number_input("单件食品或单杯茶饮最多花多少元？", min_value=0.0, max_value=1_000_000.0, value=None,
                                 step=0.1, placeholder="不限", key=_widget("budget", prefs["budget"]))
        goals = st.multiselect("希望优先满足哪些营养目标？", list(GOALS), format_func=lambda k: GOALS[k][0],
                               key=_widget("goals", prefs["goals"]), placeholder="选填")
        flavors = _custom_tags("喜欢哪些口味？", "flavors", FLAVOR_OPTIONS, prefs["flavors"])
        allergens = _custom_tags("必须避开的过敏原", "allergens", ALLERGEN_OPTIONS, prefs["allergens"])
        diets = st.multiselect("必须满足的饮食限制", DIET_OPTIONS, key=_widget("diets", prefs["diets"]),
                               placeholder="选填")
        watch = _custom_tags("希望看提示的配料", "watch", ["咖啡因", "代糖", "味精"], prefs["watch"])
        st.caption("命中过敏原或饮食限制会影响推荐资格。关注配料用于提醒。")
        st.markdown("**选购时，各项对你有多重要？**")
        weights = {k: st.slider(f"{title}权重", 0, 100, key=_widget("weights." + k, prefs["weights"][k]))
                   for k, title in DIMENSIONS.items()}
        refs = dict(prefs["references"])
        ref_price = prefs["reference_price"]
        if st.checkbox("调整评分参考值", key="shopping.scales.open"):
            st.caption("所填参考值对应单项 50 分，用于表达购物偏好。营养数量按每 100 g 或每 100 mL 计算。")
            ref_price = st.number_input("单件价格参考值（元）", min_value=0.01, max_value=1_000_000.0,
                                        step=0.1, key=_widget("reference_price", float(ref_price)))
            for goal in goals:
                title, unit = NUTRIENTS[goal]
                refs[goal] = st.number_input(f"{title}参考值（{unit}）", min_value=0.001, max_value=1_000_000.0,
                                             step=0.1, format="%.3f",
                                             key=_widget("references." + goal, float(refs[goal])))
        prefs = dict(weights=weights, goals=goals, references=refs, reference_price=ref_price,
                     budget=budget, flavors=flavors, allergens=allergens, diets=diets, watch=watch)
        st.session_state["shopping.profile"] = prefs
        weights_used = active_weights(prefs)
        if weights_used:
            st.caption("本次实际占比 · " + "，".join(
                f"{DIMENSIONS[k]} {w / sum(weights_used.values()):.0%}" for k, w in weights_used.items()))
        else:
            st.caption("当前只核对预算、过敏原和饮食限制。启用至少一项评分维度后即可查看匹配分。")
        st.caption("偏好保存在当前会话中。下载后可以在下次打开页面时导入，文件包含你填写的饮食限制。")
        if any(len(x) > 80 for x in [*watch, *flavors, *allergens]):
            st.warning("每个自定义标签请控制在 80 个字符以内，以便保存偏好。")
        else:
            st.download_button("下载我的选购偏好", export_profile(prefs), "食鉴-选购偏好.json",
                               mime="application/json", key="shopping.export", on_click="ignore")
    return prefs


def _method(prefs: dict):
    with st.expander("匹配分如何计算"):
        st.write("先检查单包预算、过敏原和饮食限制。超限或限制信息不足时，先展示原因。"
                 "参与打分的项目必须都有数据，缺少其中一项即暂缓综合评分。")
        st.write("各营养目标等权平均。希望越少越好的营养成分得分为 100 × 参考值 ÷（参考值 + 实际值）。"
                 "希望越多越好的项目把分子换为实际值。营养量统一换算为每 100 g 或 100 mL。")
        st.write(f"价格使用单包价，按越低越好的公式打分，当前参考价为 {prefs['reference_price']:g} 元。"
                 "口味标签匹配任一喜欢的口味得 100 分，有口味标签但均未匹配得 0 分。")
        st.write("综合分为各单项分的加权平均，权重为零的项目、未选择目标的营养项和未选择喜好的口味项均跳过。"
                 "同一营养口径与食品状态下才比较综合分。显示到小数点后一位时分数相同的候选并列。")
        st.caption("匹配分表示食品与你购物偏好的符合程度。可以在选购偏好中调整单项 50 分对应的参考值。")


def _details(decision: Decision, prefs):
    for reason in decision.blocked:
        st.text("不符合 · " + reason)
    for reason in decision.unresolved:
        st.text("待核对 · " + reason)
    hits = watch_alerts(decision.label, prefs)
    if hits:
        st.text("关注配料提示 · " + "、".join(hits))
    cap = prefs["budget"]
    if cap is not None and decision.label.price is not None and decision.label.price <= cap:
        st.caption(f"单包价格在 {cap:g} 元预算内。")
    st.text(unit_values(decision.label))
    value = nutrition_per_yuan(decision.label, prefs)
    if value is not None:
        st.write(f"**营养性价比** · {value:.1f} 营养偏好分/元")
        st.caption(f"按包装原状每 100 {decision.label.package_unit} 的营养偏好分，除以购买相同份量的价格。"
                   "适合用相同目标、相同计量单位比较。")
    elif decision.label.price is not None:
        st.caption("计算营养性价比需要非零单价、净含量、同单位的原状营养数据，以及已选择的营养目标。")
    weights = active_weights(prefs)
    for key, part in decision.parts.items():
        weight = weights[key] / sum(weights.values())
        value = "待补充" if part.score is None else f"{part.score:.1f} 分"
        st.text(f"{DIMENSIONS[key]} · {value} · 占 {weight:.0%}\n{part.detail}")


def single_decision(label: FoodLabel, prefs: dict) -> None:
    result = evaluate(label, prefs)
    st.subheader("这包适合我买吗？")
    if result.status == "blocked":
        st.error("这包不符合已设限制，建议换一款。")
    elif result.status == "unresolved":
        st.warning("先核对限制所需的信息，再决定是否购买。")
    elif result.status == "incomplete":
        st.info("先补齐下方标出的评分资料，再判断这包是否合适。")
    elif result.status == "unscored":
        st.info("当前仅检查限制。已录入的信息未触发排除条件。")
    elif round(result.score, 1) >= 50:
        st.success(f"可以考虑这包 · 当前偏好匹配 {result.score:.1f}/100")
    else:
        st.info(f"建议再比较一款 · 当前偏好匹配 {result.score:.1f}/100")
    if result.score is not None:
        st.caption("50 分是本工具中「可以考虑」的起点，取决于你设置的参考值和权重。")
    _details(result, prefs)
    _method(prefs)


def compare_decisions(labels, prefs) -> None:
    st.subheader("按我的偏好选购")
    results = rank_products(labels, prefs)
    if not results:
        st.info("加入候选食品后即可查看预算、限制及偏好匹配结果。")
        return
    if len(results) >= 2:
        names = [r.label.name or "未命名食品" for r in results]
        indices = choose_pair(names, "shopping.pair")
        pair = [results[i] for i in indices]
        weights = active_weights(prefs)
        goals = prefs["goals"] if "nutrition" in weights else []
        nutrition_title = GOALS[goals[0]][0] if len(goals) == 1 else "营养目标"
        states = {"as_sold": "包装原状", "prepared": "冲调后", "unknown": "状态待核对"}
        render_pair(pair, [names[i] for i in indices], [states[r.label.label_state] for r in pair],
                    "单包价格", packaged_nutrition_rows(pair, goals), pair_verdict(pair, weights, nutrition_title))
        st.markdown("**全部候选**")
    by_group: dict[str, list[Decision]] = {}
    for result in results:
        if result.rank is not None:
            by_group.setdefault(result.group, []).append(result)
    if by_group:
        for group, candidates in by_group.items():
            titles = "、".join(r.label.name or "未命名食品" for r in candidates if r.rank == 1)
            st.text(f"{group} · {len(candidates)} 款可评分 · 组内首选 {titles}")
    else:
        st.info("当前没有符合限制且资料齐全的可评分候选。请查看每款食品的原因。")
    rows = []
    for idx, result in enumerate(results, 1):
        value = nutrition_per_yuan(result.label, prefs)
        rows.append({
            "候选": f"{idx}. {result.label.name or '未命名食品'}", "状态": STATUS[result.status],
            "组内排名": str(result.rank) if result.rank else "—", "匹配分": (
                f"{result.score:.1f}" if result.score is not None else "—"),
            "单包价（元）": f"{result.label.price:g}" if result.label.price is not None else "待补充",
            "营养性价比（偏好分/元）": f"{value:.1f}" if value is not None else "—",
            "比较口径": result.group,
        })
        if prefs["watch"]:
            rows[-1]["关注词命中"] = "、".join(watch_alerts(result.label, prefs)) or "暂无命中"
    st.dataframe(rows, width="stretch", hide_index=True)
    for idx, result in enumerate(results, 1):
        with st.expander(f"候选 {idx} · {result.label.name or '未命名食品'} · {STATUS[result.status]}"):
            _details(result, prefs)
    _method(prefs)

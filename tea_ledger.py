from pathlib import Path

import streamlit as st


_ASSETS = Path(__file__).with_name("tea_ledger_component")
_CONTENT = {ext: (_ASSETS / f"ledger.{ext}").read_text(encoding="utf-8") for ext in ("html", "css", "js")}


def render_ledger() -> None:
    st.subheader("个人茶饮账本")
    st.caption("记录茶饮实付、退款和可用资金。账本保存在此浏览器，使用同一浏览器配置的人也能查看。换设备或清理浏览数据前，请导出备份。")
    order = st.session_state.get("tea.last_order")
    draft = {}
    if isinstance(order, dict):
        for field in ("brand", "name", "price"):
            value = order.get(field)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                draft[field] = str(value)[:160]
    ledger = st.components.v2.component("private_tea_ledger", **_CONTENT)
    ledger(key="private_tea_ledger", data=draft)

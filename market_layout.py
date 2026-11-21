"""Page headings and category navigation for the shopping guide."""

import streamlit as st


AREAS = {
    "预包装食品": ("enter_food", "packaged-food.webp", "食品包装、背标、价签或货架，也可手填标签。"),
    "现制奶茶": ("enter_tea", "tea-cup.webp", "杯贴、订单或品牌营养卡，也可输入茶饮名称。"),
}


def masthead():
    st.html('<div class="guide-brand"><span class="guide-brand-leaf" aria-hidden="true"></span>'
            '<span>食鉴 <b>AI</b></span></div>', width="content")


def home_heading():
    st.html("""
        <header class="guide-intro">
          <img src="app/static/supermarket-shelves.webp" width="1440" height="960"
               alt="超市食品货架上陈列着成排的罐装食品和价签">
          <div class="guide-intro-copy">
            <h1>看懂标签，<br>再做选择。</h1>
            <p>同一瓶饮料，喝半瓶和喝整瓶，差多少？</p>
          </div>
        </header>
        <p class="guide-welcome">站在货架前，两款零食该选哪款？拍下包装，读懂配料，看看「低糖」的说法有没有标签支持。选好份量，算算吃进去多少，再按预算和口味比较。想喝奶茶时，也能换个甜度看每杯能量差多少，把实付金额记进茶饮账本。</p>
    """)


def home_entries():
    for area, (key, photo, caption) in AREAS.items():
        st.button(f"![](app/static/{photo}) **{area}** {caption}", key=key, width="stretch",
                  on_click=st.session_state.update, args=({"food_area": area},))


def area_heading(area):
    st.html(f'<header class="guide-area-title"><h1>{area}</h1><p>{AREAS[area][2]}</p></header>')

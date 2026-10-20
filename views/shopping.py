"""🛒 장보기 페이지

1) 다시 사기 탭: 소진·폐기한 재료, 기한 지난/임박 재료를 한 줄씩 보여 주고, 고른 것만 한 번에 담기 / 안 살래요
2) 장바구니 탭   : 장바구니 목록(산 재료 체크, 수량 수정, 삭제) + 직접 추가(이름·수량·단위)
3) 냉장고 넣기 : 체크한 항목의 수량·유통기한을 확인하고 한 번에 냉장고에 넣기
"""

import streamlit as st

import classifier
import fridge_store
import shopping_store as shop

st.title("🛒 장보기")

# 화면이 다시 그려질 때마다 파일에서 최신 데이터를 읽어 온다.
fridge_items = fridge_store.load_items()
data = shop.load()


# ---------------------------------------------------------------
# 공통 도우미
# ---------------------------------------------------------------
def finish(ok, message):
    """결과 메시지를 기억해 두고 화면을 새로 그린다. (메시지는 다음 화면 맨 위에 표시)"""
    st.session_state.flash = (ok, message)
    st.rerun()


def known_info(name):
    """이 재료의 분류·단위를 알아낸다.

    냉장고(또는 "다 씀" 기록)에 같은 이름이 있으면 그 값을 쓰고, 없으면 자동 분류한다.
    """
    key = fridge_store.normalize_name(name)
    for item in reversed(fridge_items):  # 최근에 넣은 기록부터
        if fridge_store.normalize_name(item["name"]) == key and item.get("category"):
            return {
                "category": item["category"], "storage": item["storage"],
                "unit": item["unit"], "tip": item.get("tip", ""),
            }
    return classifier.classify(name)


# 직전 작업의 결과 메시지 표시 (한 번 보여 주고 지운다)
if "flash" in st.session_state:
    ok, message = st.session_state.pop("flash")
    (st.success if ok else st.warning)(message)


# ---------------------------------------------------------------
# 탭 3개: 다시 사기 / 장바구니(리스트 + 직접 추가) / 냉장고 넣기
# key를 주면 버튼을 눌러 화면이 다시 그려져도 보던 탭이 유지된다.
# ---------------------------------------------------------------
TAB_PUT = "🧊 냉장고 넣기"
# 팝업에서 [예]를 누르면 냉장고 넣기 탭으로 넘긴다. (탭을 그리기 전에 바꿔야 해서 여기서 처리)
if st.session_state.pop("goto_put", False):
    st.session_state.shop_tab = TAB_PUT
# on_change="rerun": 고른 탭을 st.session_state.shop_tab으로 읽고 바꿀 수 있게 한다.
tab_rebuy, tab_cart, tab_put = st.tabs(
    ["🔁 다시 사기", "🛒 장바구니", TAB_PUT], key="shop_tab", on_change="rerun"
)

with tab_rebuy:
    # ---------------------------------------------------------------
    # 1) 다시 사기 (추천 목록)
    # ---------------------------------------------------------------
    candidates = shop.candidates(fridge_items, data)
    if candidates:
        st.caption(f"다시 살 만한 재료 {len(candidates)}개")

    if not candidates:
        st.caption("추천할 재료가 없어요.")
    else:
        # 후보를 한 줄씩: [선택] 이름·이유 | 수량 입력칸(−/＋) | 단위
        # 수량은 칸을 한 번 눌러 바로 고치거나 −/＋로 바꾼다. 단위는 냉장고에 있던 단위로 고정이다.
        chosen = []
        for candidate in candidates:
            key = candidate["keys"][0]  # 입력칸 key를 구분하기 위한 값
            col_chk, col_name, col_qty, col_unit = st.columns([0.5, 3, 1.6, 0.7], vertical_alignment="center")
            picked = col_chk.checkbox(
                f"{candidate['name']} 선택", key=f"cand_chk_{key}", label_visibility="collapsed"
            )
            col_name.markdown(f"**{candidate['name']}** :gray[{candidate['detail']}]")
            quantity = col_qty.number_input(
                f"{candidate['name']} 수량", min_value=0.1, value=1.0, step=1.0, format="%g",
                key=f"cand_qty_{key}", label_visibility="collapsed",
            )
            col_unit.write(candidate["unit"])
            if picked:
                chosen.append((candidate, quantity))

        col_add, col_skip, _ = st.columns([1.3, 1.6, 2])
        if col_add.button("고른 재료 담기", type="primary", key="cand_add", disabled=not chosen):
            added, already = [], []
            for candidate, quantity in chosen:
                ok, _ = shop.add_item(data, candidate["name"], quantity, candidate["unit"], candidate["kind"])
                shop.mark_handled(data, candidate["keys"])
                (added if ok else already).append(candidate["name"])
            message = f"🛒 담았어요: {', '.join(added)}" if added else ""
            if already:
                message += f" (이미 있음: {', '.join(already)})"
            finish(bool(added), message.strip())
        if col_skip.button("고른 재료 안 살래요", key="cand_skip", disabled=not chosen):
            for candidate, _ in chosen:
                shop.mark_handled(data, candidate["keys"])
            finish(True, f"추천에서 뺐어요: {', '.join(c['name'] for c, _ in chosen)}")


with tab_cart:
    # ---------------------------------------------------------------
    # 2) 장바구니 (장보기 리스트)
    # ---------------------------------------------------------------
    st.subheader("🛒 장바구니")

    # 마트에서 이 재료를 찾을 수 있는 코너 (재료 종류로 정한다)
    AISLE_BY_CATEGORY = {
        "채소": "채소 코너", "과일": "과일 코너", "육류": "정육 코너", "해산물": "수산 코너",
        "유제품·계란": "유제품·계란 코너", "곡류·면": "쌀·면 코너", "양념·소스": "양념·소스 코너",
        "가공·냉동식품": "가공식품 코너", "밀키트·간편식": "간편식 코너", "음료": "음료 코너",
    }


    def aisle(name):
        """재료 이름으로 마트 코너를 알려 준다. 냉동 보관 재료는 냉동식품 코너, 모르면 빈 글자."""
        if "빵" in name:  # 식빵·모닝빵 등은 종류가 곡류라도 빵 코너에 있다.
            return "빵 코너"
        info = known_info(name)
        if info["category"] == "가공·냉동식품" and info["storage"] == "냉동":
            return "냉동식품 코너"
        return AISLE_BY_CATEGORY.get(info["category"], "")


    def on_check_change(item_id):
        """체크박스를 누르면 바로 저장한다."""
        checked = st.session_state[f"shop_chk_{item_id}"]
        shop.set_checked(data, item_id, checked)
        # 방금 체크해서 장바구니 재료를 전부 샀다면 냉장고에 넣을지 묻는다.
        if checked and all(item["checked"] for item in data["items"]):
            st.session_state.put_ask = True


    def on_qty_change(item_id):
        """수량을 고치면 바로 저장한다. (냉장고 넣기 탭에도 이 수량이 나온다)"""
        shop.set_quantity(data, item_id, st.session_state[f"shop_qty_{item_id}"])
        st.session_state.pop(f"buy_qty_{item_id}", None)  # 냉장고 넣기 탭 수량칸도 새 수량으로 다시 채운다


    if not data["items"]:
        st.info("장바구니가 비어 있어요.")
    else:
        # 진행도: 몇 개 중 몇 개를 샀는지 막대로 보여 준다.
        done = len(shop.checked_items(data))
        total = len(data["items"])
        st.progress(done / total, text=f"{total}개 중 {done}개 샀어요")

    # 장바구니 체크박스를 [삭제] 버튼과 비슷한 크기로 키운다.
    # key가 shop_chk_로 시작하는 체크박스에만 st-key-shop_chk_... 이름표가 붙어서 그것만 고른다.
    st.html(
        """<style>
        [class*="st-key-shop_chk_"] label > div:first-of-type {
            width: 2rem; height: 2rem; border-radius: 0.4rem;
        }
        [class*="st-key-shop_chk_"] label > div:first-of-type svg {
            width: 1.3rem; height: 1.3rem;
        }
        </style>"""
    )

    # 안 산 재료를 위에, 산(체크한) 재료를 아래에 둔다. 두 묶음 사이에는 구분선
    todo = [item for item in data["items"] if not item["checked"]]
    got = [item for item in data["items"] if item["checked"]]
    for item in todo + got:
        if got and item is got[0] and todo:
            st.divider()
        # 한 줄: 이름 | 마트 코너 | 수량 입력칸 | 단위(고정) | 체크박스(산 재료면 v) | 삭제
        col_name, col_aisle, col_qty, col_unit, col_chk, col_del = st.columns(
            [1.4, 1.4, 1.6, 0.7, 0.5, 1], vertical_alignment="center"
        )
        where = aisle(item["name"])
        if where:
            col_aisle.caption(f"📍 {where}")
        # 산 재료는 이름에 줄을 긋고 흐리게 보여 준다.
        if item["checked"]:
            col_name.markdown(f":gray[~~{item['name']}~~]")
        else:
            col_name.markdown(f"**{item['name']}**")
        col_qty.number_input(
            f"{item['name']} 수량", min_value=0.1, value=float(item["quantity"]), step=1.0, format="%g",
            key=f"shop_qty_{item['id']}", on_change=on_qty_change, args=(item["id"],),
            label_visibility="collapsed",
        )
        col_unit.write(item["unit"])
        # 체크박스 글자는 숨기고 네모 칸만 보여 준다. (label_visibility="collapsed")
        col_chk.checkbox(
            f"{item['name']} 샀어요",
            value=item["checked"],
            key=f"shop_chk_{item['id']}",
            on_change=on_check_change,
            args=(item["id"],),
            label_visibility="collapsed",
        )
        if col_del.button("삭제", key=f"shop_del_{item['id']}"):
            shop.remove_items(data, [item["id"]])
            finish(True, f"'{item['name']}'을(를) 장바구니에서 뺐어요.")


    # ---------------------------------------------------------------
    # 3) 직접 추가
    # 이름을 입력하고 Enter를 누르면 추천 단위를 채워 준다. (냉장고 추가와 같은 방식)
    # ---------------------------------------------------------------
    st.subheader("✏️ 직접 추가")

    SHOP_ADD_DEFAULTS = {
        "shop_name": "", "shop_quantity": 1.0, "shop_unit": classifier.DEFAULT_UNIT,
        "shop_units": classifier.common_units(None),  # 고를 수 있는 단위 (재료 종류에 흔한 단위만)
    }
    for k, v in SHOP_ADD_DEFAULTS.items():
        st.session_state.setdefault(k, v)


    def on_shop_name_change():
        """이름이 바뀌면 추천 단위를 채우고, 고를 수 있는 단위를 그 재료에 흔한 단위로 줄인다."""
        state = st.session_state
        name = state.shop_name.strip()
        if not name:
            state.shop_units = classifier.common_units(None)
            return
        with st.spinner(f"'{name}' 단위 추천 중..."):
            info = known_info(name)
        state.shop_units = classifier.common_units(info["category"], info["unit"])
        state.shop_unit = info["unit"]


    def on_shop_add_click():
        """[담기] 버튼: 직접 입력한 항목을 장보기 리스트에 담는다."""
        state = st.session_state
        name = state.shop_name.strip()
        if not name:
            state.flash = (False, "재료 이름을 입력해 주세요.")
            return
        state.flash = shop.add_item(data, name, state.shop_quantity, state.shop_unit, shop.SOURCE_MANUAL)
        if state.flash[0]:
            for k, v in SHOP_ADD_DEFAULTS.items():
                state[k] = v


    with st.container(border=True):
        col_name, col_qty, col_unit, col_btn = st.columns([3, 1.5, 1.2, 1])
        col_name.text_input("이름", key="shop_name", on_change=on_shop_name_change, placeholder="예: 두부")
        col_qty.number_input("수량", min_value=0.1, step=1.0, format="%g", key="shop_quantity")
        if st.session_state.shop_unit not in st.session_state.shop_units:
            st.session_state.shop_unit = st.session_state.shop_units[0]
        col_unit.selectbox("단위", st.session_state.shop_units, key="shop_unit")
        col_btn.write("")  # 버튼을 입력칸 높이에 맞추기 위한 빈 줄
        col_btn.button("담기", key="shop_add", type="primary", on_click=on_shop_add_click)


with tab_put:
    # ---------------------------------------------------------------
    # 4) 냉장고 넣기: 장바구니에서 체크한(산) 재료를 확인하고 한 번에 냉장고에 넣기
    # ---------------------------------------------------------------
    bought = shop.checked_items(data)
    if not bought:
        st.caption("장바구니에서 산 재료를 체크하면 여기에 나와요.")
    else:
        st.caption("유통기한을 비워 두면 '기한 없음'으로 들어가요. 넣지 않을 재료는 체크를 풀어 주세요.")

        # 한 줄씩: [넣기] 이름 | 수량 입력칸 | 단위(고정) | 유통기한 날짜칸
        rows = []
        for item in bought:
            col_chk, col_name, col_qty, col_unit, col_date = st.columns(
                [0.5, 1.8, 1.6, 0.7, 2], vertical_alignment="center"
            )
            put = col_chk.checkbox(
                f"{item['name']} 넣기", value=True, key=f"buy_chk_{item['id']}", label_visibility="collapsed"
            )
            col_name.markdown(f"**{item['name']}**")
            quantity = col_qty.number_input(
                f"{item['name']} 수량", min_value=0.1, value=float(item["quantity"]), step=1.0, format="%g",
                key=f"buy_qty_{item['id']}", label_visibility="collapsed",
            )
            col_unit.write(item["unit"])  # 장보기에 담은 단위 그대로
            # value=None: 처음에는 날짜를 비워 둔다. (비워 두면 기한 없음)
            expiry = col_date.date_input(
                f"{item['name']} 유통기한", value=None, key=f"buy_exp_{item['id']}",
                label_visibility="collapsed", format="YYYY-MM-DD",
            )
            rows.append((item, put, quantity, expiry))

        if st.button("완료", type="primary", key="shop_done"):
            added, separate, skipped = [], [], []
            with st.spinner("냉장고에 넣는 중..."):
                for item, put, quantity, expiry in rows:
                    if not put:
                        skipped.append(item["name"])
                        continue
                    name, unit = item["name"], item["unit"]
                    # 같은 이름이 다른 단위로만 있으면 따로 줄이 생긴다는 걸 알려 주기 위해 미리 확인
                    if fridge_store.find_all_by_name(fridge_items, name) and not fridge_store.find_in_fridge_by_name(
                        fridge_items, name, unit=unit
                    ):
                        separate.append(name)
                    fridge_store.add_item(
                        fridge_items, name, expiry, float(quantity), unit,
                        known_info(name), allow_new_unit=True,
                    )
                    added.append(name)
            shop.remove_items(data, [item["id"] for item in bought])

            message = ""
            if added:
                message += f"🧊 냉장고에 넣었어요: {', '.join(added)}. "
            if skipped:
                message += f"넣지 않고 리스트에서 뺐어요: {', '.join(skipped)}. "
            if separate:
                message += f"({', '.join(separate)}은(는) 단위가 달라서 따로 추가됐어요.)"
            finish(True, message.strip())


# ---------------------------------------------------------------
# 장바구니를 전부 체크하면 뜨는 팝업: [예] → 냉장고 넣기 탭으로
# 열린 상태를 put_ask에 기억해 두고, 화면을 다시 그릴 때마다 팝업을 다시 띄운다.
# ---------------------------------------------------------------
def close_put_ask():
    st.session_state.pop("put_ask", None)


@st.dialog("냉장고에 넣을까요?", on_dismiss=close_put_ask)
def put_ask_dialog():
    st.write("장바구니의 재료를 모두 샀어요. 냉장고에 넣을까요?")
    col_yes, col_no = st.columns(2)
    if col_yes.button("예", type="primary", key="put_yes", width="stretch"):
        close_put_ask()
        st.session_state.goto_put = True
        st.rerun()  # 팝업을 닫고 화면 전체를 다시 그린다.
    if col_no.button("아니요", key="put_no", width="stretch"):
        close_put_ask()
        st.rerun()


if st.session_state.get("put_ask"):
    put_ask_dialog()

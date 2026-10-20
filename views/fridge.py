"""🧊 냉장고 페이지: 냉장고 칸 그림 하나로 재료를 보고 관리한다.

- 맨 위: 유통기한 상태별 개수 + [+ 재료 추가] (팝업)
- 가운데: 냉장고 칸 그림 (fridge_board.py)
  - 재료 카드를 끌어서 칸을 옮기고,
  - 누르면 상세 팝업에서 사용·소진·폐기, 유통기한별 묶음을 다룬다.

app.py의 사이드바 메뉴에서 "냉장고"를 고르면 이 파일이 실행된다.
"""

from datetime import date

import streamlit as st

import classifier
import fridge_store as store
import shopping_store as shop
from fridge_board import fridge_board

st.title("🧊 냉장고")

# 화면이 다시 그려질 때마다 파일에서 최신 목록을 읽어 온다.
items = store.load_items()

# 분류 기능이 생기기 전에 넣은 재료가 있으면 한 번만 분류해 둔다.
for old_item in store.unclassified_items(items):
    with st.spinner(f"'{old_item['name']}' 분류 중..."):
        store.set_classification(items, old_item["id"], classifier.classify(old_item["name"]))

state = st.session_state

# ---------------------------------------------------------------
# 화면 상태 관리
# Streamlit은 버튼을 누를 때마다 코드를 다시 실행한다.
# 그래서 "팝업 안에서 지금 어떤 입력창(사용/수정/삭제)이 열려 있는지"를
# st.session_state(새로 실행돼도 유지되는 저장 공간)에 기억해 둔다.
#
# 열려 있는 팝업도 기억해 두고(dialog_item, add_open), 화면을 그릴 때마다 다시 연다.
# 팝업의 ✕를 누르거나 작업이 끝나면 지워서 닫는다.
# ---------------------------------------------------------------
state.setdefault("action", None)       # 예: {"kind": "use", "item_id": "...", "batch_id": None}
state.setdefault("dialog_item", None)  # 상세 팝업이 열린 재료 id
state.setdefault("add_open", False)    # 재료 추가 팝업이 열려 있는지
state.setdefault("rebuy", None)        # 장보기에 추가할지 묻는 중인 재료 정보


def open_action(kind, item_id, batch_id=None):
    """버튼을 눌렀을 때 해당 재료(또는 묶음)의 입력창을 연다."""
    state.action = {"kind": kind, "item_id": item_id, "batch_id": batch_id}


def close_action():
    """열려 있는 입력창을 닫는다."""
    state.action = None


def is_open(kind, item_id, batch_id=None):
    """지금 이 입력창이 열려 있어야 하는지 확인한다."""
    return state.action == {"kind": kind, "item_id": item_id, "batch_id": batch_id}


def finish(result):
    """작업 결과를 처리한다.

    성공하면 메시지를 기억해 두고 페이지를 새로 그린다. (팝업이 닫히고 메시지는 맨 위에 표시)
    실패하면 팝업을 닫지 않고 그 자리에 이유를 보여 준다.
    """
    ok, message = result
    if not ok:
        st.warning(message)
        return
    state.flash = (ok, message)
    close_dialogs()
    st.rerun()


def close_dialogs():
    """팝업과 그 안의 입력창을 닫는다. (팝업 ✕를 눌렀을 때도 실행)"""
    state.dialog_item = None
    state.add_open = False
    close_action()


# ---------------------------------------------------------------
# 유통기한 배지
# 상태마다 색과 아이콘을 정해 두고, Streamlit의 배지 문법 :색-badge[글자]로 표시한다.
# ---------------------------------------------------------------
STATUS_STYLE = {
    store.STATUS_EXPIRED: ("red", "🔴", "기한 지남"),
    store.STATUS_SOON: ("orange", "🟠", f"{store.SOON_DAYS}일 이내"),
    store.STATUS_OK: ("green", "🟢", "여유"),
    store.STATUS_NO_EXPIRY: ("gray", "⚪", "기한 없음"),
}


def expiry_badge(expiry_str):
    """유통기한 상태에 맞는 색깔 D-day 배지 (마크다운 글자)"""
    color, icon, _ = STATUS_STYLE[store.expiry_status(expiry_str)]
    return f":{color}-badge[{icon} {store.d_day_label(expiry_str)}]"


WEEK_DAYS = 7  # 맨 위 요약의 "7일 이내" (3일 이내와 겹치지 않게 4~7일 남은 재료)


def summary_badges():
    """맨 위 한 줄 요약: 기한 지남 / 3일 이내 / 7일 이내 재료 개수 배지 (여유·기한 없음은 표시하지 않음)"""
    groups = store.expiry_summary(items)
    week = [
        item for item in groups[store.STATUS_OK]
        if store.days_left(store.earliest_batch(item)["expiry"]) <= WEEK_DAYS
    ]
    return (
        f":red-badge[🔴 기한 지남 {len(groups[store.STATUS_EXPIRED])}] "
        f":orange-badge[🟠 {store.SOON_DAYS}일 이내 {len(groups[store.STATUS_SOON])}] "
        f":yellow-badge[🟡 {WEEK_DAYS}일 이내 {len(week)}]"
    )


# ---------------------------------------------------------------
# 1) 재료 추가 (팝업)
# 이름을 입력하고 Enter를 누르거나 다른 칸을 누르면(on_change) 바로 분류해서
# 종류·보관 방법·추천 단위를 채워 준다. 사용자는 "추가"를 누르기 전에 바꿀 수 있다.
# 여러 재료를 연달아 넣을 수 있게 추가한 뒤에도 팝업은 열어 둔다. (닫으면 칸 그림이 새로 그려짐)
#
# 입력칸 값은 key 이름으로 st.session_state에 들어 있다. (예: st.session_state.add_name)
# 콜백 함수에서 이 값을 바꾸면 화면의 입력칸 값도 바뀐다.
# ---------------------------------------------------------------
ADD_DEFAULTS = {
    "add_name": "",
    "add_expiry": date.today(),
    "add_no_expiry": False,
    "add_quantity": 1.0,
    "add_category": classifier.DEFAULT_CATEGORY,
    "add_storage": classifier.DEFAULT_STORAGE,
    "add_unit": classifier.DEFAULT_UNIT,
    "add_tip": "",
    "add_suggested": None,  # 자동 분류가 추천한 값 (사용자가 바꿨는지 비교용)
    "add_existing": None,   # 같은 이름이 이미 있으면 {"name": 이름, "units": [단위들]}
    "add_confirm": None,    # 단위가 달라서 확인을 기다리는 중이면 안내 문구
}
for key, value in ADD_DEFAULTS.items():
    state.setdefault(key, value)


def reset_add_inputs():
    """추가가 끝나면 입력칸을 처음 상태로 되돌린다."""
    for key, value in ADD_DEFAULTS.items():
        state[key] = value


def on_name_change():
    """이름 칸이 바뀌었을 때: 분류하고 추천 값을 입력칸에 채운다."""
    name = state.add_name.strip()
    state.add_confirm = None  # 이름이 바뀌면 이전 확인 창은 닫는다.
    if not name:
        reset_add_inputs()
        return

    same_name = store.find_all_by_name(store.load_items(), name)
    if same_name:
        # 이미 있는 재료면 기존 기록(첫 번째 줄)의 분류·단위를 그대로 채운다. 바꾸는 건 자유.
        first = same_name[0]
        values = {
            "category": first["category"], "storage": first["storage"],
            "unit": first["unit"], "tip": first.get("tip", ""),
        }
        state.add_existing = {"name": first["name"], "units": [item["unit"] for item in same_name]}
        state.add_suggested = None
    else:
        with st.spinner(f"'{name}' 분류 중..."):
            values = classifier.classify(name)
        state.add_existing = None
        state.add_suggested = values

    state.add_category = values["category"]
    state.add_storage = values["storage"]
    state.add_unit = values["unit"]
    state.add_tip = values["tip"]


def on_unit_change():
    """단위를 바꾸면 이전 확인 창은 닫는다. (다시 '추가'를 누를 때 새로 확인)"""
    state.add_confirm = None


def with_gwa(word):
    """이름 뒤에 '과' 또는 '와'를 붙인다. 마지막 글자에 받침이 있으면 '과', 없으면 '와'.

    예: '우유' → "'우유'와", '연근' → "'연근'과"
    한글 글자는 (코드값 - 0xAC00) % 28 이 0이 아니면 받침이 있다.
    """
    last = word[-1]
    if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0:
        return f"'{word}'과"
    return f"'{word}'와"


def cancel_confirm():
    state.add_confirm = None


def on_add_click(confirmed=False):
    """'추가' 버튼: 입력한 값으로 재료를 추가한다. 결과는 팝업 안(add_msg)에 보여 준다.

    confirmed: 단위가 달라 따로 추가된다는 확인 창에서 '이대로 추가'를 눌렀으면 True
    """
    name = state.add_name.strip()
    if not name:
        state.add_msg = (False, "재료 이름을 입력해 주세요.")
        return

    # 이름을 입력하고 Enter 없이 바로 '추가'를 누른 경우에도 분류가 되도록 한 번 더 확인한다.
    if state.add_suggested is None and state.add_existing is None:
        on_name_change()

    # 같은 이름이 있는데 고른 단위가 기존 단위와 다르면, 바로 추가하지 않고 먼저 확인을 받는다.
    existing = state.add_existing
    if existing and state.add_unit not in existing["units"] and not confirmed:
        state.add_confirm = f"냉장고에 있는 {with_gwa(existing['name'])} 단위가 달라요. 이대로 추가할까요?"
        return

    classification = {"category": state.add_category, "storage": state.add_storage, "tip": state.add_tip}
    expiry = None if state.add_no_expiry else state.add_expiry
    ok, message = store.add_item(
        store.load_items(), name, expiry, state.add_quantity, state.add_unit, classification,
        allow_new_unit=confirmed,
    )

    if ok:
        suggested = state.add_suggested
        # 추천과 다르게 고쳤으면 기억해 두고, 다음에 같은 이름을 넣을 때 그 값을 추천한다.
        if suggested and (state.add_category, state.add_storage, state.add_unit) != (
            suggested["category"], suggested["storage"], suggested["unit"]
        ):
            classifier.remember(name, state.add_category, state.add_storage, state.add_unit, state.add_tip)
        elif suggested and suggested["source"] == "default":
            message += " (자동 분류에 실패해서 기본값으로 넣었어요. 재료를 눌러 '수정'에서 바꿀 수 있어요.)"
        reset_add_inputs()
    state.add_msg = (ok, message)


@st.dialog("재료 추가", on_dismiss=close_dialogs)
def add_dialog():
    """[+ 재료 추가] 팝업. 닫으면 페이지를 다시 그려 칸 그림에 새 재료가 나온다."""
    if "add_msg" in state:
        ok, message = state.pop("add_msg")
        (st.success if ok else st.warning)(message)

    st.text_input(
        "이름", key="add_name", on_change=on_name_change,
        placeholder="예: 우유 (입력 후 Enter를 누르면 자동 분류)",
    )
    if state.add_suggested and state.add_suggested["source"] == "default":
        st.caption("⚠️ 자동 분류에 실패했어요. 종류와 보관 방법을 직접 골라 주세요.")

    col_cat, col_storage = st.columns(2)
    col_cat.selectbox("종류", classifier.CATEGORIES, key="add_category")
    col_storage.selectbox("보관 방법", classifier.STORAGES, key="add_storage")
    if state.add_tip:
        st.caption(f"💡 {state.add_tip}")

    col_date, col_none = st.columns([2, 1])
    with col_none:
        st.write("")  # 체크박스를 날짜 칸 높이에 맞추기 위한 빈 줄
        no_expiry = st.checkbox(
            "기한 없음", key="add_no_expiry", help="소금·간장처럼 기한이 없거나 모를 때 체크하세요."
        )
    with col_date:
        st.date_input("유통기한", key="add_expiry", disabled=no_expiry)

    col_qty, col_unit = st.columns([2, 1])
    col_qty.number_input("수량", min_value=0.1, step=1.0, format="%g", key="add_quantity")
    col_unit.selectbox("단위", store.UNITS, key="add_unit", on_change=on_unit_change)

    st.button("추가", type="primary", on_click=on_add_click)

    # 단위가 달라 따로 추가되는 경우의 확인 창
    if state.add_confirm:
        st.warning(state.add_confirm)
        st.caption("단위가 다르면 따로 추가돼요.")
        col_ok, col_cancel = st.columns(2)
        col_ok.button("이대로 추가", on_click=on_add_click, kwargs={"confirmed": True})
        col_cancel.button("취소", key="cancel_add_confirm", on_click=cancel_confirm)


# ---------------------------------------------------------------
# 2) 재료 상세 팝업 (칸 그림에서 재료를 누르면 열림)
#   [사용] 쓴 양 입력 / [소진] 전부 씀 / [폐기] 버림 (기한 지남·3일 이내일 때만)
#   재료가 없어지거나 폐기하면 "장보기 리스트에 추가할까요?" 팝업을 띄운다.
# ---------------------------------------------------------------
def ask_rebuy(item, result, source):
    """소진·폐기 결과를 처리한다. 성공하면 "장보기 리스트에 추가할까요?" 팝업을 띄운다.

    source: 장보기에 담을 때 출처 (소진 = SOURCE_USED, 폐기 = SOURCE_DISCARDED)
    """
    ok, message = result
    if not ok:
        st.warning(message)
        return
    state.rebuy = {
        "item_id": item["id"], "name": item["name"], "unit": item["unit"],
        "source": source, "message": message,
        "gone": item["status"] == store.STATUS_USED,  # 재료가 냉장고에서 없어졌는지
    }
    # 이전 팝업에서 고른 수량이 남지 않게 지운다. (새 팝업은 1부터 시작)
    state.pop("rebuy_qty", None)
    close_dialogs()
    st.rerun()


def after_use(item, result):
    """'사용' 결과: 남은 양이 0이 되어 소진됐으면 장보기에 추가할지 묻고, 아니면 메시지만 보여 준다."""
    if result[0] and item["status"] == store.STATUS_USED:
        ask_rebuy(item, result, shop.SOURCE_USED)
    else:
        finish(result)


def render_use_panel(item):
    """'사용' 버튼을 누르면 나오는 창: 쓴 양을 입력한다."""
    total = store.total_quantity(item)
    with st.form(f"use_form_{item['id']}"):
        amount = st.number_input(
            f"사용한 양 ({item['unit']}, 남은 양 {store.format_quantity(total, item['unit'])})",
            min_value=0.1,
            max_value=float(total),
            value=float(min(1.0, total)),
            step=1.0,
            format="%g",
        )
        col_ok, col_cancel = st.columns(2)
        ok = col_ok.form_submit_button("확인")
        col_cancel.form_submit_button("취소", on_click=close_action)
    if ok:
        after_use(item, store.use_quantity(items, item["id"], amount))


def render_batches(item):
    """유통기한별 묶음 목록. 기한이 지났거나 3일 이내인 묶음에만 [폐기] 버튼이 있다."""
    st.markdown(f"**유통기한별 ({len(item['batches'])}묶음)**")
    for batch in store.sorted_batches(item):
        col_date, col_qty, col_btn = st.columns([2.2, 1.3, 1], vertical_alignment="center")
        col_date.markdown(f"{store.format_expiry(batch['expiry'])} {expiry_badge(batch['expiry'])}")
        col_qty.write(store.format_quantity(batch["quantity"], item["unit"]))
        if store.can_discard(batch["expiry"]) and col_btn.button("폐기", key=f"discard_batch_{batch['id']}"):
            ask_rebuy(item, store.discard_batches(items, item["id"], [batch["id"]]), shop.SOURCE_DISCARDED)


@st.dialog("재료 정보", on_dismiss=close_dialogs)
def item_dialog(item_id):
    """재료 상세 팝업: 요약, [사용] [소진] [폐기], 유통기한별 묶음"""
    item = next((i for i in items if i["id"] == item_id and i["status"] == store.STATUS_IN_FRIDGE), None)
    if item is None:
        st.info("이미 소진했거나 폐기한 재료예요.")
        return
    first = store.earliest_batch(item)
    unit = item["unit"]
    zone = store.ZONES.get(item.get("zone"), "칸 미정")

    st.markdown(f"### {item['name']} {expiry_badge(first['expiry'])}")
    st.caption(
        f"총 {store.format_quantity(store.total_quantity(item), unit)} · "
        f"{item['category']} · {item['storage']} · {zone}"
    )
    if item.get("tip"):
        st.caption(f"💡 {item['tip']}")

    # 폐기 버튼은 기한이 지났거나 3일 이내인 묶음이 있을 때만 보여 준다.
    discardable = store.can_discard(first["expiry"])
    columns = st.columns(3)
    columns[0].button(
        "사용", key=f"use_{item['id']}", on_click=open_action, args=("use", item["id"]), width="stretch"
    )
    if columns[1].button("소진", key=f"used_{item['id']}", width="stretch"):
        ask_rebuy(item, store.mark_used(items, item["id"]), shop.SOURCE_USED)
    if discardable and columns[2].button("폐기", key=f"discard_{item['id']}", width="stretch"):
        ask_rebuy(item, store.discard_item(items, item["id"]), shop.SOURCE_DISCARDED)

    if is_open("use", item["id"]):
        render_use_panel(item)

    st.divider()
    render_batches(item)


# ---------------------------------------------------------------
# 3) "장보기 리스트에 추가할까요?" 팝업 (소진·폐기 뒤)
# ---------------------------------------------------------------
def close_rebuy():
    """✕로 닫으면 묻지 않은 것으로 둔다. (장보기의 '다시 살까요?'에 그대로 남는다)"""
    state.rebuy = None


def answer_rebuy(buy, quantity=1.0):
    """[추가]면 고른 수량으로 장보기 리스트에 담는다. (단위는 냉장고에 있던 단위)
    어느 쪽이든 장보기의 '다시 살까요?'에는 다시 나오지 않게 한다."""
    info = state.rebuy
    data = shop.load()
    result = (True, f"{info['message']} 장보기에는 추가하지 않았어요.")
    if buy:
        ok, message = shop.add_item(data, info["name"], quantity, info["unit"], info["source"])
        result = (ok, f"{info['message']} {message}")
    if info["gone"]:
        shop.mark_handled(data, [f"used:{info['item_id']}"])
    state.rebuy = None
    state.flash = result


@st.dialog("🛒 장보기", on_dismiss=close_rebuy)
def rebuy_dialog():
    info = state.rebuy
    st.write(info["message"])
    st.markdown(f"**'{info['name']}'을(를) 장보기 리스트에 추가할까요?**")
    # 담을 수량 (단위는 냉장고에 있던 단위 그대로)
    quantity = st.number_input(
        f"수량 ({info['unit']})", min_value=0.1, value=1.0, step=1.0, format="%g", key="rebuy_qty"
    )
    col_yes, col_no = st.columns(2)
    if col_yes.button("추가", type="primary", width="stretch"):
        answer_rebuy(True, quantity)
        st.rerun()
    if col_no.button("추가 안 함", width="stretch"):
        answer_rebuy(False)
        st.rerun()


# ---------------------------------------------------------------
# 4) 맨 위: 상태별 개수 + [+ 재료 추가]
# ---------------------------------------------------------------
col_summary, col_add = st.columns([4, 1.3], vertical_alignment="center")
col_summary.markdown(summary_badges())
def open_add_dialog():
    close_dialogs()
    state.pop("add_msg", None)
    state.add_open = True


col_add.button("＋ 재료 추가", type="primary", width="stretch", on_click=open_add_dialog)

# 직전 작업의 결과 메시지 표시 (한 번 보여 주고 지운다)
if "flash" in state:
    ok, message = state.pop("flash")
    (st.success if ok else st.warning)(message)


# ---------------------------------------------------------------
# 5) 냉장고 칸 그림
# 재료를 끌어서 놓으면 on_move, 누르면 on_select가 페이지를 다시 그리기 전에 실행된다.
# ---------------------------------------------------------------
BOARD_KEY = "fridge_board"


def on_move():
    """재료를 다른 칸에 놓으면 저장한다. (저장한 뒤에 그려야 원래 칸으로 되돌아가 보이지 않는다)"""
    move = (state.get(BOARD_KEY) or {}).get("move")
    if move:
        store.set_zone(store.load_items(), move.get("item_id"), move.get("zone"))


def on_select():
    """재료를 누르면 그 재료의 상세 팝업을 열도록 기억해 둔다."""
    selected = (state.get(BOARD_KEY) or {}).get("select")
    if selected:
        close_dialogs()  # 다른 재료에서 열어 둔 입력창은 닫는다.
        state.dialog_item = selected


if not store.fridge_items_sorted(items):
    st.info("냉장고가 비어 있어요. '＋ 재료 추가'로 재료를 넣어 보세요.")
else:
    st.caption("재료를 누르면 사용·소진·폐기, 끌면 칸을 옮길 수 있어요.")
    fridge_board(items, key=BOARD_KEY, on_move=on_move, on_select=on_select)

# 열려 있어야 하는 팝업을 연다. (한 번에 하나만)
if state.rebuy:
    rebuy_dialog()
elif state.add_open:
    add_dialog()
elif state.dialog_item:
    item_dialog(state.dialog_item)

"""스마트 냉장고 & 장보기 리스트 - Streamlit 앱 진입 파일.

실행: streamlit run app.py
"""

from datetime import date

import streamlit as st

import fridge_store as store

st.set_page_config(page_title="스마트 냉장고", page_icon="🧊")
st.title("🧊 스마트 냉장고")

# 화면이 다시 그려질 때마다 파일에서 최신 목록을 읽어 온다.
items = store.load_items()

# ---------------------------------------------------------------
# 화면 상태 관리
# Streamlit은 버튼을 누를 때마다 코드 전체를 처음부터 다시 실행한다.
# 그래서 "지금 어떤 재료의 사용/수정/삭제 창이 열려 있는지"를
# st.session_state(새로 실행돼도 유지되는 저장 공간)에 기억해 둔다.
# ---------------------------------------------------------------
if "action" not in st.session_state:
    st.session_state.action = None  # 예: {"kind": "use", "item_id": "...", "batch_id": None}


def open_action(kind, item_id, batch_id=None):
    """버튼을 눌렀을 때 해당 재료(또는 묶음)의 입력창을 연다."""
    st.session_state.action = {"kind": kind, "item_id": item_id, "batch_id": batch_id}


def close_action():
    """열려 있는 입력창을 닫는다."""
    st.session_state.action = None


def is_open(kind, item_id, batch_id=None):
    """지금 이 입력창이 열려 있어야 하는지 확인한다."""
    return st.session_state.action == {"kind": kind, "item_id": item_id, "batch_id": batch_id}


def finish(result):
    """작업 결과 메시지를 기억해 두고, 입력창을 닫고, 화면을 새로 그린다.

    st.rerun()을 하면 그 전에 띄운 메시지가 사라지므로,
    메시지를 session_state에 넣어 두었다가 다음 화면 맨 위에서 보여 준다.
    """
    ok, message = result
    st.session_state.flash = (ok, message)
    if ok:
        close_action()
    st.rerun()


# 직전 작업의 결과 메시지 표시 (한 번 보여 주고 지운다)
if "flash" in st.session_state:
    ok, message = st.session_state.pop("flash")
    (st.success if ok else st.warning)(message)


# ---------------------------------------------------------------
# 1) 재료 추가 폼
# st.form을 쓰면 "추가" 버튼을 누를 때 한 번에 제출된다.
# (입력칸을 하나 바꿀 때마다 화면이 새로 그려지는 것을 막아 준다)
# ---------------------------------------------------------------
with st.form("add_item_form", clear_on_submit=True):
    st.subheader("재료 추가")
    name = st.text_input("이름", placeholder="예: 우유")

    col_date, col_none = st.columns([2, 1])
    with col_date:
        expiry = st.date_input("유통기한", value=date.today())
    with col_none:
        st.write("")  # 체크박스를 날짜 칸 높이에 맞추기 위한 빈 줄
        no_expiry = st.checkbox("기한 없음", help="소금·간장처럼 기한이 없거나 모를 때 체크하세요.")

    # 수량과 단위를 한 줄에 나란히 배치
    col_qty, col_unit = st.columns([2, 1])
    with col_qty:
        quantity = st.number_input("수량", min_value=0.1, value=1.0, step=1.0, format="%g")
    with col_unit:
        unit = st.selectbox("단위", store.UNITS)

    submitted = st.form_submit_button("추가")

if submitted:
    name = name.strip()  # 앞뒤 공백 제거
    if not name:
        st.warning("재료 이름을 입력해 주세요.")
    else:
        finish(store.add_item(items, name, None if no_expiry else expiry, quantity, unit))


# ---------------------------------------------------------------
# 2) 재료 한 줄에 딸린 입력창들 (사용 / 수정 / 삭제 확인)
# ---------------------------------------------------------------
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
        cancel = col_cancel.form_submit_button("취소")
    if ok:
        finish(store.use_quantity(items, item["id"], amount))
    if cancel:
        close_action()
        st.rerun()


def render_edit_item_panel(item):
    """'수정' 버튼을 누르면 나오는 창: 이름과 단위를 고친다."""
    with st.form(f"edit_item_form_{item['id']}"):
        new_name = st.text_input("이름", value=item["name"])
        new_unit = st.selectbox("단위", store.UNITS, index=store.UNITS.index(item["unit"]))
        col_ok, col_cancel = st.columns(2)
        ok = col_ok.form_submit_button("저장")
        cancel = col_cancel.form_submit_button("취소")
    if ok:
        new_name = new_name.strip()
        if not new_name:
            st.warning("재료 이름을 입력해 주세요.")
        else:
            finish(store.update_item(items, item["id"], new_name, new_unit))
    if cancel:
        close_action()
        st.rerun()


def render_confirm_delete(message, on_delete, key):
    """삭제 전에 한 번 더 확인하는 창"""
    st.warning(message)
    col_ok, col_cancel = st.columns(2)
    if col_ok.button("삭제", key=f"confirm_{key}", type="primary"):
        finish(on_delete())
    if col_cancel.button("취소", key=f"cancel_{key}"):
        close_action()
        st.rerun()


# ---------------------------------------------------------------
# 3) 유통기한별 묶음 (펼쳐보기 안쪽)
# ---------------------------------------------------------------
def render_edit_batch_panel(item, batch):
    """묶음의 '수정' 버튼을 누르면 나오는 창: 유통기한과 수량을 고친다."""
    current = date.fromisoformat(batch["expiry"]) if batch["expiry"] else date.today()
    with st.form(f"edit_batch_form_{batch['id']}"):
        col_date, col_none = st.columns([2, 1])
        new_expiry = col_date.date_input("유통기한", value=current)
        col_none.write("")
        new_no_expiry = col_none.checkbox("기한 없음", value=batch["expiry"] is None)
        new_quantity = st.number_input(
            f"수량 ({item['unit']})",
            min_value=0.1,
            value=float(batch["quantity"]),
            step=1.0,
            format="%g",
        )
        col_ok, col_cancel = st.columns(2)
        ok = col_ok.form_submit_button("저장")
        cancel = col_cancel.form_submit_button("취소")
    if ok:
        finish(
            store.update_batch(
                items, item["id"], batch["id"], None if new_no_expiry else new_expiry, new_quantity
            )
        )
    if cancel:
        close_action()
        st.rerun()


def render_batches(item):
    """재료 한 줄 아래에 유통기한별 묶음 목록을 펼쳐 볼 수 있게 보여 준다."""
    # 묶음 수정·삭제 창이 열려 있으면 펼친 상태를 유지한다.
    action = st.session_state.action
    keep_open = bool(action and action["item_id"] == item["id"] and action["batch_id"])

    with st.expander(f"유통기한별 보기 ({len(item['batches'])}묶음)", expanded=keep_open):
        for batch in store.sorted_batches(item):
            col_date, col_qty, col_edit, col_del = st.columns([2, 2, 1, 1])
            col_date.write(store.format_expiry(batch["expiry"]))
            col_qty.write(store.format_quantity(batch["quantity"], item["unit"]))
            col_edit.button(
                "수정", key=f"edit_batch_{batch['id']}",
                on_click=open_action, args=("edit_batch", item["id"], batch["id"]),
            )
            col_del.button(
                "삭제", key=f"del_batch_{batch['id']}",
                on_click=open_action, args=("delete_batch", item["id"], batch["id"]),
            )

            if is_open("edit_batch", item["id"], batch["id"]):
                render_edit_batch_panel(item, batch)
            if is_open("delete_batch", item["id"], batch["id"]):
                render_confirm_delete(
                    f"{store.format_expiry(batch['expiry'])} 묶음"
                    f"({store.format_quantity(batch['quantity'], item['unit'])})을 삭제할까요?",
                    lambda: store.delete_batch(items, item["id"], batch["id"]),
                    key=batch["id"],
                )


# ---------------------------------------------------------------
# 4) 냉장고 목록 (가장 빠른 유통기한 순)
# ---------------------------------------------------------------
st.subheader("냉장고 목록")
fridge = store.fridge_items_sorted(items)

if not fridge:
    st.info("냉장고가 비어 있어요. 위에서 재료를 추가해 보세요.")

for item in fridge:
    with st.container(border=True):
        first = store.earliest_batch(item)
        unit = item["unit"]

        # 요약 줄: 이름 | 총 수량 · 가장 빠른 기한(그 기한의 수량) | 버튼 4개
        col_name, col_summary, col_use, col_used, col_edit, col_del = st.columns(
            [2, 3, 1, 1.1, 1, 1]
        )
        col_name.markdown(f"**{item['name']}**")
        col_summary.write(
            f"총 {store.format_quantity(store.total_quantity(item), unit)} · "
            f"{store.format_expiry(first['expiry'])} "
            f"({store.format_quantity(first['quantity'], unit)})"
        )
        # on_click: 버튼을 누르면 해당 입력창을 연다. ("다 씀"은 바로 실행)
        # 버튼마다 key가 달라야 Streamlit이 어떤 재료의 버튼인지 구분할 수 있다.
        col_use.button("사용", key=f"use_{item['id']}", on_click=open_action, args=("use", item["id"]))
        if col_used.button("다 씀", key=f"used_{item['id']}"):
            finish(store.mark_used(items, item["id"]))
        col_edit.button("수정", key=f"edit_{item['id']}", on_click=open_action, args=("edit_item", item["id"]))
        col_del.button("삭제", key=f"del_{item['id']}", on_click=open_action, args=("delete_item", item["id"]))

        # 열려 있는 입력창 표시
        if is_open("use", item["id"]):
            render_use_panel(item)
        if is_open("edit_item", item["id"]):
            render_edit_item_panel(item)
        if is_open("delete_item", item["id"]):
            render_confirm_delete(
                f"'{item['name']}'을(를) 모든 묶음까지 삭제할까요? (다 씀 기록도 남지 않아요)",
                lambda: store.delete_item(items, item["id"]),
                key=item["id"],
            )

        render_batches(item)

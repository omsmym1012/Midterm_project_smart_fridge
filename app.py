"""스마트 냉장고 & 장보기 리스트 - Streamlit 앱 진입 파일.

실행: streamlit run app.py
"""

from datetime import date

import streamlit as st

import classifier
import fridge_store as store

st.set_page_config(page_title="스마트 냉장고", page_icon="🧊")
st.title("🧊 스마트 냉장고")

# 화면이 다시 그려질 때마다 파일에서 최신 목록을 읽어 온다.
items = store.load_items()

# 분류 기능이 생기기 전에 넣은 재료가 있으면 한 번만 분류해 둔다.
for old_item in store.unclassified_items(items):
    with st.spinner(f"'{old_item['name']}' 분류 중..."):
        store.set_classification(items, old_item["id"], classifier.classify(old_item["name"]))

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


def render_expiry_summary():
    """화면 맨 위의 유통기한 요약: 상태별 재료 개수와 이름"""
    groups = store.expiry_summary(items)
    columns = st.columns(3)
    for col, status in zip(columns, [store.STATUS_EXPIRED, store.STATUS_SOON, store.STATUS_OK]):
        _, icon, title = STATUS_STYLE[status]
        group = groups[status]
        with col.container(border=True):
            st.metric(f"{icon} {title}", f"{len(group)}개")
            # 이름이 많으면 길어지므로 앞의 5개만 보여 주고 나머지는 "외 N개"로 줄인다.
            names = [item["name"] for item in group]
            shown = ", ".join(names[:5]) + (f" 외 {len(names) - 5}개" if len(names) > 5 else "")
            st.caption(shown or "없음")
    if groups[store.STATUS_NO_EXPIRY]:
        st.caption(f"⚪ 기한 없음 {len(groups[store.STATUS_NO_EXPIRY])}개는 요약에서 뺐어요.")


render_expiry_summary()

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
        classification = None
        note = ""
        # 이미 있는 재료에 합칠 때는 분류가 필요 없다. 새 재료일 때만 분류한다.
        if not store.find_in_fridge_by_name(items, name):
            with st.spinner(f"'{name}' 분류 중..."):
                classification = classifier.classify(name)
            if classification["source"] == "default":
                note = " (자동 분류에 실패해서 '기타'로 넣었어요. '수정'에서 바꿀 수 있어요.)"
        ok, message = store.add_item(
            items, name, None if no_expiry else expiry, quantity, unit, classification
        )
        finish((ok, message + note if ok else message))


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
    """'수정' 버튼을 누르면 나오는 창: 이름·단위·종류·보관 방법·팁을 고친다."""
    with st.form(f"edit_item_form_{item['id']}"):
        col_name, col_unit = st.columns([2, 1])
        new_name = col_name.text_input("이름", value=item["name"])
        new_unit = col_unit.selectbox("단위", store.UNITS, index=store.UNITS.index(item["unit"]))
        col_cat, col_storage = st.columns(2)
        new_category = col_cat.selectbox(
            "종류", classifier.CATEGORIES, index=classifier.CATEGORIES.index(item["category"])
        )
        new_storage = col_storage.selectbox(
            "보관 방법", classifier.STORAGES, index=classifier.STORAGES.index(item["storage"])
        )
        new_tip = st.text_input("보관 팁", value=item.get("tip", ""))
        col_ok, col_cancel = st.columns(2)
        ok = col_ok.form_submit_button("저장")
        cancel = col_cancel.form_submit_button("취소")
    if ok:
        new_name = new_name.strip()
        if not new_name:
            st.warning("재료 이름을 입력해 주세요.")
        else:
            new_tip = new_tip.strip()
            changed = (new_category, new_storage, new_tip) != (
                item["category"], item["storage"], item.get("tip", "")
            )
            result = store.update_item(
                items, item["id"], new_name, new_unit, new_category, new_storage, new_tip
            )
            # 분류를 직접 고쳤으면 기억해 두고, 다음에 같은 이름을 넣을 때 그대로 쓴다.
            if result[0] and changed:
                classifier.remember(new_name, new_category, new_storage, new_tip)
            finish(result)
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
        if item.get("tip"):
            st.caption(f"💡 {item['tip']}")
        for batch in store.sorted_batches(item):
            col_date, col_qty, col_edit, col_del = st.columns([2, 2, 1, 1])
            col_date.markdown(f"{store.format_expiry(batch['expiry'])} {expiry_badge(batch['expiry'])}")
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

# 종류·보관 방법 필터 ("전체"면 거르지 않음)
col_filter_cat, col_filter_storage = st.columns(2)
filter_category = col_filter_cat.selectbox("종류", ["전체"] + classifier.CATEGORIES)
filter_storage = col_filter_storage.selectbox("보관", ["전체"] + classifier.STORAGES)
filtered = [
    item for item in fridge
    if filter_category in ("전체", item["category"])
    and filter_storage in ("전체", item["storage"])
]

if not fridge:
    st.info("냉장고가 비어 있어요. 위에서 재료를 추가해 보세요.")
elif not filtered:
    st.info("조건에 맞는 재료가 없어요.")

for item in filtered:
    with st.container(border=True):
        first = store.earliest_batch(item)
        unit = item["unit"]

        # 요약 줄: 이름 | 총 수량 · 가장 빠른 기한(그 기한의 수량) | 버튼 4개
        col_name, col_summary, col_use, col_used, col_edit, col_del = st.columns(
            [2, 3, 1, 1.1, 1, 1]
        )
        col_name.markdown(f"**{item['name']}**")
        col_name.caption(f"{item['category']} · {item['storage']}")
        col_summary.markdown(
            f"{expiry_badge(first['expiry'])}  \n"  # 배지 다음 줄에 수량·기한 표시
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

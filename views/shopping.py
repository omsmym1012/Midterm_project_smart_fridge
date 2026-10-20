"""🛒 장보기 페이지

1) 다시 살까요?  : 다 쓴 재료·기한 지난/임박 재료 추천 → [담기] / [안 살래요]
2) 직접 추가     : 이름·수량·단위를 입력해서 담기
3) 장보기 리스트 : 이름 오른쪽 체크박스로 구매 체크, 삭제
4) 산 재료 정리  : 체크한 항목을 표에서 확인하고 한 번에 냉장고에 넣기
"""

import hashlib

import pandas as pd
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
# 1) 다시 살까요? (추천 목록)
# ---------------------------------------------------------------
st.subheader("🔁 다시 살까요?")
candidates = shop.candidates(fridge_items, data)

# 기한 지난 재료의 [담기]를 누르면 "버릴까요?" 확인 창을 연다. 어떤 후보인지 기억해 둔다.
st.session_state.setdefault("shop_discard_ask", None)

if not candidates:
    st.caption("추천할 재료가 없어요.")

for candidate in candidates:
    with st.container(border=True):
        col_name, col_add, col_skip = st.columns([4, 1, 1.3])
        col_name.markdown(f"**{candidate['name']}**")
        col_name.caption(candidate["detail"])
        key = candidate["keys"][0]  # 버튼 key를 구분하기 위한 값

        if col_add.button("담기", key=f"cand_add_{key}"):
            if candidate["kind"] == shop.SOURCE_EXPIRED:
                st.session_state.shop_discard_ask = key  # 버릴지 먼저 묻는다
                st.rerun()
            ok, message = shop.add_item(data, candidate["name"], 1.0, candidate["unit"], candidate["kind"])
            shop.mark_handled(data, candidate["keys"])
            finish(ok, message)

        if col_skip.button("안 살래요", key=f"cand_skip_{key}"):
            shop.mark_handled(data, candidate["keys"])
            finish(True, f"'{candidate['name']}'은(는) 추천에서 뺐어요.")

        # 기한 지난 재료: 냉장고의 지난 묶음도 버릴지 확인
        if st.session_state.shop_discard_ask == key:
            st.warning(f"냉장고에 있는 기한 지난 '{candidate['name']}'도 버릴까요?")
            st.caption(candidate["detail"])
            col_yes, col_no, col_cancel = st.columns(3)
            discard = col_yes.button("버리고 담기", key=f"discard_yes_{key}", type="primary")
            keep = col_no.button("남겨두고 담기", key=f"discard_no_{key}")
            if col_cancel.button("취소", key=f"discard_cancel_{key}"):
                st.session_state.shop_discard_ask = None
                st.rerun()
            if discard or keep:
                st.session_state.shop_discard_ask = None
                handled_keys = list(candidate["keys"])
                if discard:
                    fridge_store.discard_batches(fridge_items, candidate["item_id"], candidate["batch_ids"])
                    # 묶음을 다 버려서 "다 씀"이 됐다면, 그 기록이 다시 추천되지 않게 같이 처리한다.
                    handled_keys.append(f"used:{candidate['item_id']}")
                ok, message = shop.add_item(data, candidate["name"], 1.0, candidate["unit"], candidate["kind"])
                shop.mark_handled(data, handled_keys)
                finish(ok, message + (" 기한 지난 묶음은 버렸어요." if discard else ""))


# ---------------------------------------------------------------
# 2) 직접 추가
# 이름을 입력하고 Enter를 누르면 추천 단위를 채워 준다. (냉장고 추가와 같은 방식)
# ---------------------------------------------------------------
st.subheader("✏️ 직접 추가")

SHOP_ADD_DEFAULTS = {"shop_name": "", "shop_quantity": 1.0, "shop_unit": classifier.DEFAULT_UNIT}
for k, v in SHOP_ADD_DEFAULTS.items():
    st.session_state.setdefault(k, v)


def on_shop_name_change():
    """이름이 바뀌면 추천 단위를 채운다."""
    name = st.session_state.shop_name.strip()
    if name:
        with st.spinner(f"'{name}' 단위 추천 중..."):
            st.session_state.shop_unit = known_info(name)["unit"]


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
    col_unit.selectbox("단위", fridge_store.UNITS, key="shop_unit")
    col_btn.write("")  # 버튼을 입력칸 높이에 맞추기 위한 빈 줄
    col_btn.button("담기", key="shop_add", type="primary", on_click=on_shop_add_click)


# ---------------------------------------------------------------
# 3) 장보기 리스트
# ---------------------------------------------------------------
st.subheader("📝 장보기 리스트")

SOURCE_LABEL = {
    shop.SOURCE_USED: "다 쓴 재료",
    shop.SOURCE_EXPIRED: "기한 지난 재료",
    shop.SOURCE_SOON: "기한 임박 재료",
    shop.SOURCE_MANUAL: "직접 추가",
    shop.SOURCE_RECIPE: "요리 추천",
}


def on_check_change(item_id):
    """체크박스를 누르면 바로 저장한다."""
    shop.set_checked(data, item_id, st.session_state[f"shop_chk_{item_id}"])


if not data["items"]:
    st.info("장보기 리스트가 비어 있어요.")

for item in data["items"]:
    # 한 줄: 이름·수량 | 체크박스(산 재료면 v) | 출처 | 삭제
    col_name, col_chk, col_src, col_del = st.columns([3, 0.7, 2, 1], vertical_alignment="center")
    col_name.markdown(f"**{item['name']}** {fridge_store.format_quantity(item['quantity'], item['unit'])}")
    # 체크박스 글자는 숨기고 네모 칸만 보여 준다. (label_visibility="collapsed")
    col_chk.checkbox(
        f"{item['name']} 샀어요",
        value=item["checked"],
        key=f"shop_chk_{item['id']}",
        on_change=on_check_change,
        args=(item["id"],),
        label_visibility="collapsed",
    )
    col_src.caption(SOURCE_LABEL.get(item["source"], ""))
    if col_del.button("삭제", key=f"shop_del_{item['id']}"):
        shop.remove_items(data, [item["id"]])
        finish(True, f"'{item['name']}'을(를) 장보기 리스트에서 뺐어요.")


# ---------------------------------------------------------------
# 4) 산 재료 정리: 체크한 항목을 표에서 확인하고 한 번에 냉장고에 넣기
# ---------------------------------------------------------------
bought = shop.checked_items(data)
if bought:
    st.subheader("🧾 산 재료 냉장고에 넣기")
    st.caption(
        "수량·단위·유통기한을 확인해 주세요. 유통기한을 비워 두면 '기한 없음'으로 들어가요. "
        "냉장고에 넣지 않을 재료는 '넣기' 체크를 풀어 주세요."
    )

    # st.data_editor: 엑셀처럼 칸을 직접 고칠 수 있는 표
    table = pd.DataFrame(
        {
            "넣기": [True] * len(bought),
            "이름": [item["name"] for item in bought],
            "수량": [float(item["quantity"]) for item in bought],
            "단위": [item["unit"] for item in bought],
            # 날짜 칸은 처음에 비워 둔다. (NaT = 날짜 없음)
            "유통기한": pd.to_datetime(pd.Series([None] * len(bought))),
        }
    )
    # 체크한 항목이 바뀌면 표를 새로 만들도록 key에 항목 id들을 반영한다.
    editor_key = "shop_editor_" + hashlib.md5("".join(i["id"] for i in bought).encode()).hexdigest()[:8]
    edited = st.data_editor(
        table,
        key=editor_key,
        hide_index=True,
        width="stretch",
        column_config={
            "넣기": st.column_config.CheckboxColumn("넣기", width="small"),
            "이름": st.column_config.TextColumn("이름", disabled=True),
            "수량": st.column_config.NumberColumn("수량", min_value=0.1, step=1.0, format="%g"),
            "단위": st.column_config.SelectboxColumn("단위", options=fridge_store.UNITS, required=True),
            "유통기한": st.column_config.DateColumn("유통기한", format="YYYY-MM-DD"),
        },
    )

    if st.button("완료", type="primary", key="shop_done"):
        added, separate, skipped = [], [], []
        with st.spinner("냉장고에 넣는 중..."):
            for item, (_, row) in zip(bought, edited.iterrows()):
                if not row["넣기"]:
                    skipped.append(item["name"])
                    continue
                name, unit = item["name"], row["단위"]
                expiry = None if pd.isna(row["유통기한"]) else row["유통기한"].date()
                # 같은 이름이 다른 단위로만 있으면 따로 줄이 생긴다는 걸 알려 주기 위해 미리 확인
                if fridge_store.find_all_by_name(fridge_items, name) and not fridge_store.find_in_fridge_by_name(
                    fridge_items, name, unit=unit
                ):
                    separate.append(name)
                fridge_store.add_item(
                    fridge_items, name, expiry, float(row["수량"]), unit,
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

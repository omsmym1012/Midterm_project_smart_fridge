"""🗄️ 냉장고 칸 페이지: 재료를 끌어다 냉장고 칸에 놓아 보관 위치를 정리한다."""

import streamlit as st

import fridge_store as store
from fridge_board import fridge_board

st.title("🗄️ 냉장고 칸")
st.caption("재료를 끌어다 칸에 놓으세요. 재료를 짚으면 추천 칸이 초록색으로 바뀌어요.")

BOARD_KEY = "fridge_board"


def on_move():
    """재료를 다른 칸에 놓으면 화면을 다시 그리기 전에 저장한다.

    (저장한 뒤에 화면을 그려야 재료가 원래 칸으로 되돌아가 보이지 않는다.)
    """
    move = (st.session_state.get(BOARD_KEY) or {}).get("move")
    if move:
        store.set_zone(store.load_items(), move.get("item_id"), move.get("zone"))


items = store.load_items()
if not store.fridge_items_sorted(items):
    st.info("냉장고가 비어 있어요.")
else:
    fridge_board(items, key=BOARD_KEY, on_move=on_move)

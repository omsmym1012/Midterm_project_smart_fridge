"""🍳 요리 추천 페이지

[추천 받기]를 누르면 냉장고 재료로 만들 수 있는 요리 3개를 보여 준다.
- 식품안전나라 레시피에서 먼저 고르고, 모자라면 AI로 채운다. (recipe_store.recommend)
- 부족한 재료는 골라서 장보기 리스트에 담을 수 있다.
"""

import streamlit as st

import classifier
import fridge_store
import recipe_store
import shopping_store as shop

st.title("🍳 요리 추천")

items = fridge_store.load_items()
fridge = recipe_store.usable_items(items)

if "flash" in st.session_state:
    ok, message = st.session_state.pop("flash")
    (st.success if ok else st.warning)(message)

if not fridge:
    st.info("요리에 쓸 재료가 없어요. 냉장고에 재료를 먼저 추가해 주세요.")
    st.stop()

soon = [f["name"] for f in fridge if f["soon"]]
if soon:
    st.caption(f"🟠 먼저 쓸 재료: {', '.join(soon)}")

# 추천 결과는 화면이 다시 그려져도 유지되도록 session_state에 둔다.
state = st.session_state
state.setdefault("recipe_picks", None)
state.setdefault("recipe_notice", None)
state.setdefault("recipe_seen_ids", [])     # 이미 보여 준 레시피 (다른 요리 보기에서 제외)
state.setdefault("recipe_seen_names", [])


def run_recommend(more=False):
    """추천을 받아 session_state에 넣는다. more=True면 이미 본 요리는 빼고 새로 고른다."""
    if not more:
        state.recipe_seen_ids, state.recipe_seen_names = [], []
    with st.spinner("요리를 찾는 중... (처음에는 레시피를 받느라 조금 걸려요)"):
        picks, notice = recipe_store.recommend(items, state.recipe_seen_ids, state.recipe_seen_names)
    state.recipe_picks, state.recipe_notice = picks, notice
    state.recipe_seen_ids += [p["recipe"]["id"] for p in picks if p["recipe"]["id"]]
    state.recipe_seen_names += [p["recipe"]["name"] for p in picks]


col_new, col_more, _ = st.columns([1, 1.3, 2])
if col_new.button("추천 받기", type="primary"):
    run_recommend()
if state.recipe_picks and col_more.button("다른 요리 보기"):
    run_recommend(more=True)

if state.recipe_notice:
    st.warning(f"{state.recipe_notice} AI 추천만 보여 줘요.")

if state.recipe_picks is not None and not state.recipe_picks:
    st.warning("추천할 요리를 찾지 못했어요. 잠시 후 다시 시도해 주세요.")


def add_missing(names):
    """고른 부족한 재료를 장보기 리스트에 담는다."""
    data = shop.load()
    added, skipped = [], []
    with st.spinner("장보기에 담는 중..."):
        for name in names:
            unit = classifier.classify(name)["unit"]  # 재료에 맞는 단위 (목록·캐시·AI)
            ok, _ = shop.add_item(data, name, 1.0, unit, shop.SOURCE_RECIPE)
            (added if ok else skipped).append(name)
    message = f"🛒 장보기에 담았어요: {', '.join(added)}" if added else ""
    if skipped:
        message += f" (이미 있음: {', '.join(skipped)})"
    state.flash = (bool(added), message.strip())
    st.rerun()


def render_card(index, pick):
    recipe = pick["recipe"]
    with st.container(border=True):
        col_img, col_info = st.columns([1, 2])
        if recipe["image"]:
            col_img.image(recipe["image"], width="stretch")
        else:
            col_img.markdown("### 🍳")

        with col_info:
            badge = " :violet-badge[AI 추천]" if pick["source"] == "ai" else ""
            st.markdown(f"#### {recipe['name']}{badge}")
            info = " · ".join(x for x in [recipe["kind"], recipe["way"], f"{recipe['kcal']}kcal" if recipe["kcal"] else ""] if x)
            if info:
                st.caption(info)
            if pick["source"] == "ai" and recipe["tip"]:
                st.caption(recipe["tip"])

            # 쓰는 냉장고 재료 (임박 재료는 주황색 배지)
            uses = [f":orange-badge[{n}]" if n in pick["soon"] else n for n in pick["uses"]]
            st.markdown(f"**냉장고 재료:** {', '.join(uses) or '없음'}")

            listed = [m for m in pick["missing"] if shop.find_by_name(shop.load(), m)]
            to_buy = [m for m in pick["missing"] if m not in listed]
            if not pick["missing"]:
                st.markdown("**부족한 재료:** 없음")
            else:
                st.markdown(f"**부족한 재료:** {', '.join(pick['missing'])}")
                if to_buy:
                    chosen = st.multiselect(
                        "장보기에 담을 재료", to_buy, default=to_buy,
                        key=f"recipe_missing_{index}_{recipe['name']}", label_visibility="collapsed",
                    )
                    if st.button("장보기에 담기", key=f"recipe_add_{index}_{recipe['name']}", disabled=not chosen):
                        add_missing(chosen)
                else:
                    st.caption("🛒 모두 장보기 리스트에 있어요.")

        with st.expander("조리 순서"):
            for step in recipe["steps"]:
                st.markdown(step if step[:1].isdigit() else f"- {step}")
            if pick["basic"]:
                st.caption(f"기본 양념: {', '.join(pick['basic'])}")
            if pick["source"] == "api":
                if recipe["parts"]:
                    st.caption(f"재료 전체: {recipe['parts']}")
                if recipe["tip"]:
                    st.caption(f"💡 {recipe['tip']}")
                st.caption("출처: 식품안전나라 조리식품 레시피 DB")


for i, pick in enumerate(state.recipe_picks or []):
    render_card(i, pick)

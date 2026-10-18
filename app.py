"""스마트 냉장고 & 장보기 리스트 - Streamlit 앱 진입 파일.

실행: streamlit run app.py

이 파일은 사이드바 메뉴만 만들고, 실제 화면은 views/ 폴더의 페이지 파일이 그린다.
    views/fridge.py   🧊 냉장고 > 목록
    views/zones.py    🗄️ 냉장고 > 칸
    views/shopping.py 🛒 장보기
    views/recipe.py   🍳 요리 추천
"""

import streamlit as st

import shopping_store

st.set_page_config(page_title="스마트 냉장고", page_icon="🧊")

# 메뉴의 "장보기" 옆에 아직 안 산 항목 개수를 보여 준다. 예: "장보기 (3)"
count = shopping_store.unchecked_count(shopping_store.load())

# st.Page: 페이지 하나. url_path를 정해 두면 제목(개수)이 바뀌어도 같은 페이지로 인식된다.
# st.navigation에 딕셔너리를 넘기면 "제목: [페이지들]" 묶음으로 사이드바에 보여 준다.
pages = {
    "냉장고": [
        st.Page("views/fridge.py", title="목록", icon="🧊", url_path="fridge", default=True),
        st.Page("views/zones.py", title="칸", icon="🗄️", url_path="zones"),
    ],
    "장보기": [
        st.Page("views/shopping.py", title=f"장보기 ({count})" if count else "장보기", icon="🛒", url_path="shopping"),
    ],
    "요리": [
        st.Page("views/recipe.py", title="요리 추천", icon="🍳", url_path="recipe"),
    ],
}

# st.navigation: 왼쪽 사이드바에 메뉴를 만들고, 고른 페이지를 실행한다.
st.navigation(pages).run()

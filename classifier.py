"""재료 이름을 보고 종류와 보관 방법을 분류하는 모듈.

분류 순서
1) 사용자가 직접 고친 결과나 예전 AI 결과(캐시 파일)에 있으면 그대로 사용
2) 미리 만든 목록(BUILTIN)에 있으면 사용 — 빠르고 무료
3) 둘 다 없으면 OpenRouter AI에게 물어보고, 결과를 캐시에 저장
4) AI도 실패하면 "기타 / 냉장"으로 두고 사용자가 고칠 수 있게 한다
"""

import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

# .env 파일의 OPENROUTER_API_KEY를 환경 변수로 읽어 온다. (내 컴퓨터에서 실행할 때)
load_dotenv()

CATEGORIES = [
    "채소", "과일", "육류", "해산물", "유제품·계란",
    "곡류·면", "양념·소스", "가공·냉동식품", "음료", "기타",
]
STORAGES = ["냉장", "냉동", "실온"]

DEFAULT_CATEGORY = "기타"
DEFAULT_STORAGE = "냉장"

# AI 설정
# 무료 모델은 사용자가 몰리면 잠깐씩 막힌다(429 오류).
# 그래서 첫 번째 모델이 막히면 다음 모델로 다시 시도하도록 여러 개를 적어 둔다.
AI_MODELS = ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"]
AI_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_TIMEOUT = 20  # 초. 이 시간 안에 답이 없으면 실패로 처리

# 사용자 수정·AI 결과를 기억해 두는 파일 (.gitignore의 data/*.json에 포함되어 커밋되지 않음)
CACHE_FILE = Path(__file__).parent / "data" / "classify_cache.json"

# ---------------------------------------------------------------
# 미리 만든 분류 목록: 이름 → (종류, 보관, 팁)
# 자취생이 자주 사는 재료 위주로 정리했다.
# ---------------------------------------------------------------
BUILTIN = {
    # 채소
    "대파": ("채소", "냉장", "손질해서 키친타월로 감싸 밀폐용기에 보관하세요."),
    "쪽파": ("채소", "냉장", "씻지 말고 키친타월에 싸서 보관하세요."),
    "양파": ("채소", "실온", "통풍이 잘 되는 서늘한 곳에 두세요. 자른 건 랩으로 싸서 냉장."),
    "마늘": ("채소", "냉장", "다진 마늘은 소분해서 냉동하면 오래 써요."),
    "감자": ("채소", "실온", "빛을 피해 서늘한 곳에. 사과와 같이 두면 싹이 덜 나요."),
    "고구마": ("채소", "실온", "냉장하면 쉽게 상해요. 신문지에 싸서 서늘한 곳에 두세요."),
    "당근": ("채소", "냉장", "물기를 닦고 키친타월에 싸서 보관하세요."),
    "양배추": ("채소", "냉장", "심지를 도려내고 젖은 키친타월을 채워 두면 오래가요."),
    "배추": ("채소", "냉장", "신문지에 싸서 세워 보관하세요."),
    "상추": ("채소", "냉장", "씻지 말고 키친타월을 깔아 밀폐용기에 보관하세요."),
    "깻잎": ("채소", "냉장", "꼭지에 물을 적신 키친타월을 감싸 보관하세요."),
    "시금치": ("채소", "냉장", "데쳐서 소분 냉동하면 오래 써요."),
    "콩나물": ("채소", "냉장", "물에 담가 냉장하고 물을 자주 갈아 주세요."),
    "숙주": ("채소", "냉장", "금방 상하니 1~2일 안에 드세요."),
    "애호박": ("채소", "냉장", "랩으로 싸서 보관하세요."),
    "오이": ("채소", "냉장", "물기를 닦고 키친타월에 싸서 세워 두세요."),
    "가지": ("채소", "냉장", "랩으로 하나씩 싸서 보관하세요."),
    "버섯": ("채소", "냉장", "씻지 말고 키친타월에 싸서 보관하세요."),
    "팽이버섯": ("채소", "냉장", "봉지째 냉장하고 뜯은 뒤에는 빨리 드세요."),
    "고추": ("채소", "냉장", "꼭지를 떼고 밀폐용기에. 오래 둘 땐 냉동하세요."),
    "파프리카": ("채소", "냉장", "물기를 닦고 하나씩 랩으로 싸 두세요."),
    "브로콜리": ("채소", "냉장", "데쳐서 소분 냉동하면 오래 써요."),
    "토마토": ("채소", "실온", "덜 익었으면 실온, 익으면 냉장하세요."),
    "방울토마토": ("채소", "냉장", "씻지 말고 보관하고 먹기 직전에 씻으세요."),
    "무": ("채소", "냉장", "자른 단면을 랩으로 싸서 보관하세요."),
    # 과일
    "사과": ("과일", "냉장", "다른 과일과 따로 봉지에 넣어 보관하세요."),
    "바나나": ("과일", "실온", "걸어 두면 덜 물러요. 익으면 껍질째 냉동해도 돼요."),
    "귤": ("과일", "실온", "서늘한 곳에 두고 상한 게 있으면 바로 골라내세요."),
    "딸기": ("과일", "냉장", "씻지 말고 보관하고 2~3일 안에 드세요."),
    "포도": ("과일", "냉장", "씻지 말고 봉지째 냉장하세요."),
    "레몬": ("과일", "냉장", "밀폐 봉지에 넣어 냉장하세요."),
    "아보카도": ("과일", "실온", "익을 때까지 실온, 익으면 냉장하세요."),
    "블루베리": ("과일", "냉장", "씻지 말고 보관하고, 오래 둘 땐 냉동하세요."),
    # 육류
    "돼지고기": ("육류", "냉장", "2~3일 안에 못 먹으면 1회분씩 랩에 싸 냉동하세요."),
    "삼겹살": ("육류", "냉장", "1회분씩 랩에 싸 냉동하면 편해요."),
    "소고기": ("육류", "냉장", "2~3일 안에 못 먹으면 소분해서 냉동하세요."),
    "닭고기": ("육류", "냉장", "1~2일 안에 조리하거나 바로 냉동하세요."),
    "닭가슴살": ("육류", "냉동", "1개씩 소분 냉동하고 전날 냉장 해동하세요."),
    "다짐육": ("육류", "냉장", "상하기 쉬워요. 바로 소분해서 냉동하세요."),
    "베이컨": ("육류", "냉장", "개봉 후에는 랩으로 싸서 빨리 드세요."),
    # 해산물
    "고등어": ("해산물", "냉동", "손질해서 1회분씩 냉동하세요."),
    "새우": ("해산물", "냉동", "해동한 건 다시 얼리지 마세요."),
    "오징어": ("해산물", "냉동", "손질해서 소분 냉동하세요."),
    "연어": ("해산물", "냉장", "1~2일 안에 드세요."),
    "어묵": ("해산물", "냉장", "개봉 후 밀폐해서 빨리 드세요. 오래 둘 땐 냉동."),
    "참치캔": ("해산물", "실온", "개봉 후엔 다른 용기에 옮겨 냉장하세요."),
    # 유제품·계란
    "계란": ("유제품·계란", "냉장", "뾰족한 쪽이 아래로 가게 두고, 문 쪽보다 안쪽에 보관하세요."),
    "달걀": ("유제품·계란", "냉장", "뾰족한 쪽이 아래로 가게 두고, 문 쪽보다 안쪽에 보관하세요."),
    "우유": ("유제품·계란", "냉장", "개봉 후에는 기한과 상관없이 2~3일 안에 드세요."),
    "치즈": ("유제품·계란", "냉장", "개봉 후 랩으로 단단히 싸서 보관하세요."),
    "요거트": ("유제품·계란", "냉장", "개봉 후엔 빨리 드세요."),
    "버터": ("유제품·계란", "냉장", "많으면 소분해서 냉동하세요."),
    "두부": ("유제품·계란", "냉장", "남은 두부는 물에 잠기게 담가 냉장하고 물을 매일 갈아 주세요."),
    # 곡류·면
    "쌀": ("곡류·면", "실온", "밀폐용기에 담아 서늘한 곳에 두세요. 여름엔 냉장."),
    "밥": ("곡류·면", "냉동", "따뜻할 때 1공기씩 랩에 싸 냉동하세요."),
    "라면": ("곡류·면", "실온", "직사광선을 피해 보관하세요."),
    "파스타": ("곡류·면", "실온", "밀폐해서 습기를 피하세요."),
    "식빵": ("곡류·면", "냉동", "바로 못 먹으면 한 장씩 냉동하세요. 냉장은 빨리 굳어요."),
    "빵": ("곡류·면", "실온", "2일 넘게 둘 거면 냉동하세요."),
    "떡": ("곡류·면", "냉동", "1회분씩 냉동하세요."),
    "우동": ("곡류·면", "냉장", "개봉 전엔 냉장, 오래 둘 땐 냉동하세요."),
    # 양념·소스
    "간장": ("양념·소스", "실온", "개봉 후엔 냉장하면 맛이 오래가요."),
    "고추장": ("양념·소스", "냉장", "깨끗한 숟가락으로 덜어 쓰세요."),
    "된장": ("양념·소스", "냉장", "표면을 랩으로 덮어 두세요."),
    "소금": ("양념·소스", "실온", "습기 없는 곳에 밀폐해서 두세요."),
    "설탕": ("양념·소스", "실온", "습기 없는 곳에 밀폐해서 두세요."),
    "식용유": ("양념·소스", "실온", "빛을 피해 서늘한 곳에 두세요."),
    "참기름": ("양념·소스", "실온", "빛을 피해 서늘한 곳에 두세요."),
    "케첩": ("양념·소스", "냉장", "개봉 후 냉장하세요."),
    "마요네즈": ("양념·소스", "냉장", "개봉 후 냉장하세요. 얼리면 분리돼요."),
    "김치": ("양념·소스", "냉장", "공기가 닿지 않게 꾹 눌러 담으세요."),
    # 가공·냉동식품
    "만두": ("가공·냉동식품", "냉동", "녹았다 다시 얼리면 맛이 떨어져요."),
    "햄": ("가공·냉동식품", "냉장", "개봉 후 랩으로 싸서 빨리 드세요."),
    "스팸": ("가공·냉동식품", "실온", "개봉 후엔 랩으로 싸서 냉장하세요."),
    "소시지": ("가공·냉동식품", "냉장", "개봉 후 빨리 드세요."),
    "냉동피자": ("가공·냉동식품", "냉동", "녹았다 다시 얼리지 마세요."),
    "아이스크림": ("가공·냉동식품", "냉동", "냉동실 안쪽에 두세요."),
    "김": ("가공·냉동식품", "실온", "개봉 후 밀폐해서 습기를 피하세요."),
    # 음료
    "주스": ("음료", "냉장", "개봉 후 빨리 드세요."),
    "생수": ("음료", "실온", "직사광선을 피하세요."),
    "맥주": ("음료", "냉장", "세워서 보관하세요."),
    "콜라": ("음료", "실온", "개봉 후엔 냉장하세요."),
}


def _normalize(name):
    """비교용 이름: 띄어쓰기를 지우고 영문은 소문자로 (fridge_store와 같은 규칙)"""
    return "".join(name.split()).lower()


# ---------------------------------------------------------------
# 캐시 파일 (사용자 수정 + AI 결과)
# ---------------------------------------------------------------
def _load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = CACHE_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, CACHE_FILE)


def remember(name, category, storage, tip):
    """사용자가 고친 분류를 기억한다. 다음에 같은 이름을 추가하면 이 값을 쓴다."""
    cache = _load_cache()
    cache[_normalize(name)] = {"category": category, "storage": storage, "tip": tip}
    _save_cache(cache)


# ---------------------------------------------------------------
# 미리 만든 목록에서 찾기
# ---------------------------------------------------------------
def _from_builtin(name):
    """목록에서 찾는다. 정확히 같은 이름이 없으면 이름 안에 포함된 단어로 찾는다.

    예: "서울우유" → "우유", "냉동만두" → "만두"
    여러 개가 포함되면 가장 긴 단어를 쓴다. ("방울토마토"는 "토마토"보다 "방울토마토")
    """
    key = _normalize(name)
    if key in BUILTIN:
        return BUILTIN[key]
    matches = [word for word in BUILTIN if word in key]
    if matches:
        # 한 글자 단어("무", "김", "밥")는 엉뚱하게 걸리기 쉬워서, 이름 전체가 같을 때만 쓴다.
        matches = [word for word in matches if len(word) >= 2]
    if matches:
        return BUILTIN[max(matches, key=len)]
    return None


# ---------------------------------------------------------------
# AI에게 물어보기
# ---------------------------------------------------------------
def _get_api_key():
    """API 키를 찾는다. 내 컴퓨터에서는 .env, Streamlit Cloud에서는 Secrets 설정에서 읽는다."""
    key = os.getenv("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        import streamlit as st

        return st.secrets.get("OPENROUTER_API_KEY")
    except Exception:
        # Secrets 설정이 아예 없으면 오류가 나므로 조용히 None을 돌려준다.
        return None


def _ask_ai(name):
    """AI에게 분류를 요청한다. 성공하면 (종류, 보관, 팁), 실패하면 None."""
    api_key = _get_api_key()
    if not api_key:
        return None

    prompt = (
        f"식재료 '{name}'을(를) 분류해 주세요.\n"
        f"종류는 다음 중 하나: {', '.join(CATEGORIES)}\n"
        f"보관 방법은 다음 중 하나: {', '.join(STORAGES)}\n"
        "tip은 자취생을 위한 보관 팁 한 문장(40자 이내)입니다.\n"
        "다른 설명 없이 JSON 한 개만 답하세요. 예:\n"
        '{"category": "채소", "storage": "냉장", "tip": "키친타월에 싸서 보관하세요."}'
    )
    # 모델을 앞에서부터 차례로 시도하고, 처음으로 제대로 답한 결과를 쓴다.
    for model in AI_MODELS:
        result = _ask_one_model(api_key, model, prompt)
        if result:
            return result
    return None


def _ask_one_model(api_key, model, prompt):
    """모델 하나에 요청한다. 성공하면 (종류, 보관, 팁), 실패하면 None."""
    try:
        response = requests.post(
            AI_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=AI_TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError):
        # 인터넷 문제, 무료 모델 호출 한도 초과(429), 이상한 응답 등은 모두 실패로 처리
        return None

    # AI가 ```json ... ``` 처럼 감싸서 답해도 { } 부분만 꺼내서 읽는다.
    found = re.search(r"\{.*\}", text, re.DOTALL)
    if not found:
        return None
    try:
        data = json.loads(found.group())
    except json.JSONDecodeError:
        return None

    category, storage = data.get("category"), data.get("storage")
    # 정해진 선택지 밖의 답을 하면 믿지 않는다.
    if category not in CATEGORIES or storage not in STORAGES:
        return None
    return category, storage, str(data.get("tip", "")).strip()


# ---------------------------------------------------------------
# 외부에서 쓰는 함수
# ---------------------------------------------------------------
def classify(name):
    """재료 이름을 분류해서 dict로 돌려준다.

    반환 예: {"category": "채소", "storage": "냉장", "tip": "...", "source": "builtin"}
    source: "cache"(사용자 수정·이전 AI) / "builtin"(목록) / "ai" / "default"(분류 실패)
    """
    cache = _load_cache()
    key = _normalize(name)
    if key in cache:
        return {**cache[key], "source": "cache"}

    found = _from_builtin(name)
    if found:
        category, storage, tip = found
        return {"category": category, "storage": storage, "tip": tip, "source": "builtin"}

    found = _ask_ai(name)
    if found:
        category, storage, tip = found
        # AI 결과는 저장해 두고 다음에는 다시 묻지 않는다.
        cache[key] = {"category": category, "storage": storage, "tip": tip}
        _save_cache(cache)
        return {"category": category, "storage": storage, "tip": tip, "source": "ai"}

    return {"category": DEFAULT_CATEGORY, "storage": DEFAULT_STORAGE, "tip": "", "source": "default"}

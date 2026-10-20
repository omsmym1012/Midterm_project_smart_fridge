"""요리 추천 모듈

1) 식품안전나라 "조리식품의 레시피 DB"(COOKRCP01)를 한 번에 받아 data/recipes.json에 저장한다.
   (일주일이 지나면 새로 받는다. 받기에 실패하면 예전에 받은 것을 그대로 쓴다.)
2) 냉장고 재료와 레시피 재료를 비교해서 점수를 매긴다.
   - 사용자가 고른 "쓰고 싶은 재료"(처음에는 유통기한 3일 이내 재료)를 1개 이상 쓰는 레시피만,
     많이 쓸수록 앞으로
   - 냉장고 재료를 많이 쓰고, 부족한 재료가 적을수록 앞으로
   - 기한 지난 재료는 없는 것으로 본다.
3) 냉장고 재료를 2가지 이상 쓰는 레시피가 3개가 안 되면, 모자란 만큼 AI에게 요리를 추천받는다.

인증키는 .env(또는 Streamlit Cloud Secrets)의 FOODSAFETY_API_KEY에서 읽는다.
"""

import json
import os
import re
import time
from pathlib import Path

import requests

import ai_client
import fridge_store

DATA_FILE = Path(__file__).parent / "data" / "recipes.json"  # .gitignore의 data/*.json에 포함
API_URL = "https://openapi.foodsafetykorea.go.kr/api/{key}/COOKRCP01/json/{start}/{end}"
PAGE_SIZE = 1000          # API가 한 번에 주는 최대 개수
REFRESH_DAYS = 7          # 이 기간이 지나면 레시피를 새로 받는다
RECOMMEND_COUNT = 3       # 보여 줄 요리 개수
MIN_FRIDGE_MATCH = 2      # "알맞은 레시피" 기준: 냉장고 재료를 이만큼 이상 쓰는 레시피

# 거의 모든 집에 있다고 보고, 부족한 재료로 치지 않는 기본 양념
BASIC_SEASONINGS = [
    "물", "소금", "설탕", "후추", "후춧가루", "간장", "식용유", "참기름", "들기름", "깨", "참깨",
    "통깨", "식초", "올리고당", "물엿", "요리당", "고춧가루", "다진마늘", "맛술", "미림", "청주",
]

# 같은 재료로 보는 이름 묶음. 한 묶음 안의 이름은 서로 같은 재료로 비교한다.
# 예: 냉장고에 "삼겹살"이 있으면 레시피의 "돼지고기"도 있는 것으로 본다. (반대도 마찬가지)
SAME_GROUPS = [
    ["계란", "달걀"],
    ["소고기", "쇠고기"],
    ["돼지고기", "삼겹살"],
]


class RecipeError(Exception):
    """레시피를 받을 수 없을 때 (인증키 없음·잘못된 키·인터넷 문제)"""


# ---------------------------------------------------------------
# 레시피 받기 / 저장
# ---------------------------------------------------------------
def load_recipes():
    """저장된 레시피를 돌려준다. 없거나 오래됐으면 API에서 새로 받는다.

    새로 받기에 실패했는데 예전 레시피가 있으면 그것을 쓰고, 아예 없으면 RecipeError를 낸다.
    """
    saved = _read_file()
    fresh = saved and time.time() - saved.get("fetched_at", 0) < REFRESH_DAYS * 86400
    if fresh:
        return saved["recipes"]
    try:
        recipes = fetch_all()
    except RecipeError:
        if saved:
            return saved["recipes"]
        raise
    _write_file({"fetched_at": time.time(), "recipes": recipes})
    return recipes


def _read_file():
    if not DATA_FILE.exists():
        return None
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if data.get("recipes") else None
    except (json.JSONDecodeError, OSError, AttributeError):
        return None


def _write_file(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_file, DATA_FILE)


def fetch_all():
    """API에서 레시피 전체를 받아 정리된 목록으로 돌려준다."""
    key = ai_client.get_secret("FOODSAFETY_API_KEY")
    if not key:
        raise RecipeError("식품안전나라 인증키(FOODSAFETY_API_KEY)가 설정되지 않았어요.")
    recipes, start = [], 1
    while True:
        rows, total = _fetch_page(key, start, start + PAGE_SIZE - 1)
        recipes += [_parse_row(row) for row in rows]
        start += PAGE_SIZE
        if not rows or start > total:
            break
    # 이름이나 재료가 비어 있는 레시피는 빼고, 같은 레시피 번호가 두 번 오면 하나만 남긴다.
    unique = {}
    for recipe in recipes:
        if recipe["name"] and recipe["ingredients"]:
            unique.setdefault(recipe["id"] or recipe["name"], recipe)
    return list(unique.values())


def _fetch_page(key, start, end):
    """레시피 start~end번을 받는다. 반환: (레시피 줄들, 전체 개수)"""
    try:
        response = requests.get(API_URL.format(key=key, start=start, end=end), timeout=30)
        response.raise_for_status()
        body = response.json()["COOKRCP01"]
    except (requests.RequestException, ValueError, KeyError) as error:
        raise RecipeError("레시피를 받아 오지 못했어요. 잠시 후 다시 시도해 주세요.") from error
    result = body.get("RESULT", {})
    if result.get("CODE") not in (None, "INFO-000"):
        # 예: INFO-100 인증키가 유효하지 않음, INFO-200 데이터 없음
        raise RecipeError(f"식품안전나라: {result.get('MSG', '알 수 없는 오류')}")
    return body.get("row", []), int(body.get("total_count") or 0)


def _https(url):
    """사진 주소를 https로 바꾼다. (배포 사이트는 https라 http 사진은 막힐 수 있다)"""
    return url.replace("http://", "https://", 1) if url else ""


def _parse_row(row):
    """API 레시피 한 줄을 앱에서 쓰기 좋은 모양으로 정리한다."""
    steps = []
    for i in range(1, 21):  # 조리 순서는 MANUAL01 ~ MANUAL20 칸에 나뉘어 있다
        text = (row.get(f"MANUAL{i:02d}") or "").strip()
        if text:
            # 끝에 붙은 사진 표시 글자(예: "...섞는다.a")를 지운다.
            steps.append(re.sub(r"(?<=[.!])[a-zA-Z]$", "", text))
    return {
        "id": row.get("RCP_SEQ", ""),
        "name": (row.get("RCP_NM") or "").strip(),
        "kind": row.get("RCP_PAT2", ""),         # 반찬, 국&찌개, 일품 등
        "way": row.get("RCP_WAY2", ""),          # 끓이기, 볶기 등
        "kcal": row.get("INFO_ENG", ""),
        "image": _https(row.get("ATT_FILE_NO_MAIN", "")),
        "parts": (row.get("RCP_PARTS_DTLS") or "").strip(),
        "ingredients": parse_ingredients(row.get("RCP_PARTS_DTLS") or ""),
        "steps": steps,
        "tip": (row.get("RCP_NA_TIP") or "").strip(),
    }


def parse_ingredients(text):
    """재료 글자에서 재료 이름만 골라낸다.

    예: "[1인분]두부 20g(2×2×2cm), 다진 대파 5g(1작은술)\\n·양념장 : 간장 3g"
        → ["두부", "다진 대파", "간장"]
    """
    names = []
    for line in text.splitlines():
        line = re.sub(r"\[[^\]]*\]", "", line)          # [1인분] 같은 표시
        if ":" in line:
            line = line.split(":", 1)[1]                # "·양념장 : ..." 의 머리말
        # 쉼표가 없고 숫자도 없는 줄은 요리 이름이나 "고명" 같은 머리말로 본다.
        if "," not in line and not re.search(r"\d", line):
            continue
        # 재료는 쉼표로 나뉘고, 가끔 "+", ">", "/"로 이어 적기도 한다.
        for part in re.split(r"[,+>/]", line):
            part = part.split(":")[-1]                  # "육수: 쇠고기" 처럼 안쪽에 남은 머리말
            part = re.sub(r"\([^)]*\)?", "", part)      # 괄호 안 설명 (닫는 괄호가 빠진 것도)
            part = re.split(r"\d|약간|적당량|조금|소량|적량|½|⅓|¼|⅔", part)[0]  # 양 표시 앞까지만
            part = re.sub(r"<[^>]*>?|[()]", " ", part)     # 남은 HTML 태그(<br>)·괄호
            part = part.strip(" ·•-●○▶*\t")
            # 앞의 머리말 지우기. 예: "재료 표고버섯", "양념 다진 마늘", "고기 삶는 재료 양파", "발사믹드레싱 발사믹식초"
            part = re.sub(r"^.*?(재료|양념장|양념|육수|고명|반죽|드레싱|토핑|곁들임|소스)\s+(?=\S)", "", part).strip()
            if 1 <= len(part) <= 15 and part not in names:
                names.append(part)
    return names


# ---------------------------------------------------------------
# 냉장고 재료와 비교
# ---------------------------------------------------------------
def _norm(name):
    return fridge_store.normalize_name(name)


def _aliases(name):
    """이름과, 같은 재료 묶음(SAME_GROUPS)의 다른 이름들. 예: "한돈삼겹살" → {"한돈삼겹살", "돼지고기", "삼겹살"}"""
    names = {name}
    for group in SAME_GROUPS:
        if any(word in name for word in group):
            names.update(group)
    return names


def _matches(fridge_name, ingredient):
    """냉장고 재료가 레시피 재료와 같은 것인지 (띄어쓰기 무시, 포함 관계도 인정)

    예: "대파" ↔ "다진 대파", "서울우유" ↔ "우유", "삼겹살" ↔ "돼지고기". 한 글자 이름("무")은 완전히 같을 때만.
    """
    a, b = _norm(fridge_name), _norm(ingredient)
    for x in _aliases(a):
        if x == b:
            return True
        short, long_ = sorted((x, b), key=len)
        if len(short) >= 2 and short in long_:
            return True
    return False


def _is_basic(ingredient):
    key = _norm(ingredient)
    return any(key == s or (len(s) >= 2 and key.endswith(s)) for s in BASIC_SEASONINGS)


def usable_items(items):
    """추천에 쓸 냉장고 재료: 냉장고에 있고 기한이 지나지 않은 묶음이 있는 것"""
    result = []
    for item in fridge_store.fridge_items_sorted(items):
        alive = [b for b in item["batches"] if fridge_store.expiry_status(b["expiry"]) != fridge_store.STATUS_EXPIRED]
        if alive:
            soon = any(fridge_store.expiry_status(b["expiry"]) == fridge_store.STATUS_SOON for b in alive)
            label = fridge_store.d_day_label(fridge_store.earliest_batch({"batches": alive})["expiry"])
            # pick: 이번 추천에서 꼭 쓰고 싶은 재료인지 (recommend에서 사용자 선택으로 채운다)
            result.append({"name": item["name"], "soon": soon, "dday": label, "pick": soon})
    return result


def score_recipe(recipe, fridge):
    """레시피 하나를 냉장고 재료와 비교한다.

    반환: {"recipe", "uses": [냉장고 재료], "picked": [그중 쓰고 싶은 재료], "soon": [그중 임박 재료],
           "missing": [부족한 재료], "basic": [기본 양념]}
    """
    uses, picked, soon, missing, basic = [], [], [], [], []
    for ingredient in recipe["ingredients"]:
        # 기본 양념은 먼저 걸러 낸다. (냉장고에 간장·소금이 있다고 "알맞은 레시피"가 되지 않게)
        if _is_basic(ingredient):
            basic.append(ingredient)
            continue
        found = next((f for f in fridge if _matches(f["name"], ingredient)), None)
        if found:
            if found["name"] not in uses:
                uses.append(found["name"])
                if found["soon"]:
                    soon.append(found["name"])
                if found["pick"]:
                    picked.append(found["name"])
        else:
            missing.append(ingredient)
    return {
        "recipe": recipe, "uses": uses, "picked": picked, "soon": soon,
        "missing": missing, "basic": basic, "source": "api",
    }


def recommend_from_recipes(recipes, fridge, exclude_ids=()):
    """알맞은 레시피를 점수 순으로 골라 최대 3개 돌려준다.

    알맞은 레시피: 냉장고 재료를 2가지 이상 쓰고, 쓰고 싶은 재료를 골랐다면 그중 1개 이상을 쓰는 것
    exclude_ids: 이미 보여 준 레시피 id ("다른 요리 보기"에서 겹치지 않게)
    """
    need_pick = any(f["pick"] for f in fridge)
    scored = [score_recipe(r, fridge) for r in recipes if r["id"] not in exclude_ids]
    good = [s for s in scored if len(s["uses"]) >= MIN_FRIDGE_MATCH and (s["picked"] or not need_pick)]
    # 정렬 순서: 쓰고 싶은 재료를 많이 쓸수록 → 임박 재료를 많이 쓸수록 → 냉장고 재료를 많이 쓸수록 → 부족한 재료가 적을수록
    good.sort(key=lambda s: (-len(s["picked"]), -len(s["soon"]), -len(s["uses"]), len(s["missing"])))
    return good[:RECOMMEND_COUNT]


# ---------------------------------------------------------------
# AI로 보완
# ---------------------------------------------------------------
def recommend_from_ai(fridge, count, avoid_names=()):
    """레시피가 모자랄 때 AI에게 요리 count개를 추천받는다. 실패하면 빈 목록."""
    if count <= 0 or not fridge:
        return []
    soon = [f["name"] for f in fridge if f["soon"]]
    picks = [f["name"] for f in fridge if f["pick"]]
    fridge_names = [f["name"] for f in fridge]
    prompt = (
        "자취생 1인분 집밥 요리를 추천해 주세요.\n"
        f"냉장고 재료: {', '.join(fridge_names)}\n"
        f"꼭 쓰고 싶은 재료: {', '.join(picks) or '없음'}\n"
        f"이미 추천한 요리(제외): {', '.join(avoid_names) or '없음'}\n"
        f"꼭 쓰고 싶은 재료를 1개 이상(많을수록 좋음) 쓰고, 냉장고 재료를 최대한 활용하는 요리 {count}개를 골라 주세요.\n"
        "uses는 위 냉장고 재료 이름 중 실제로 쓰는 것만 그대로 적고, "
        "missing은 더 사야 하는 재료(소금·간장 같은 기본 양념 제외)입니다. "
        "steps는 짧은 조리 순서 3~6단계입니다.\n"
        "다른 설명 없이 JSON 배열만 답하세요. 예:\n"
        '[{"name": "대파 계란볶음밥", "description": "10분 만에 만드는 볶음밥", '
        '"uses": ["대파", "계란"], "missing": ["밥"], "steps": ["대파를 송송 썬다.", "..."]}]'
    )

    def check(data):
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return None
        results = []
        for dish in data[:count]:
            if not isinstance(dish, dict) or not str(dish.get("name", "")).strip():
                continue
            uses = [n for n in dish.get("uses", []) if n in fridge_names]  # 없는 재료를 지어내면 뺀다
            results.append(
                {
                    "recipe": {
                        "id": "", "name": str(dish["name"]).strip(), "kind": "", "way": "", "kcal": "",
                        "image": "", "parts": "", "ingredients": [],
                        "steps": [str(s) for s in dish.get("steps", []) if str(s).strip()],
                        "tip": str(dish.get("description", "")).strip(),
                    },
                    "uses": uses,
                    "picked": [n for n in uses if n in picks],
                    "soon": [n for n in uses if n in soon],
                    "missing": [str(n) for n in dish.get("missing", []) if str(n).strip()],
                    "basic": [],
                    "source": "ai",
                }
            )
        return results or None

    return ai_client.ask_json(prompt, validate=check, total_timeout=60) or []


def recommend(items, chosen=None, exclude_ids=(), avoid_names=()):
    """요리 추천 전체 흐름. 반환: (추천 목록, 안내 메시지 또는 None)

    chosen: 사용자가 고른 "쓰고 싶은 재료" 이름들. None이면 유통기한 3일 이내 재료를 쓴다.

    레시피 DB에서 먼저 고르고, 3개가 안 되면 AI로 채운다.
    레시피 DB를 못 쓰면(인증키 없음 등) AI만으로 추천하고 그 이유를 알려 준다.
    """
    fridge = usable_items(items)
    if chosen is not None:
        for f in fridge:
            f["pick"] = f["name"] in chosen
    notice = None
    try:
        picks = recommend_from_recipes(load_recipes(), fridge, exclude_ids)
    except RecipeError as error:
        picks, notice = [], str(error)
    if len(picks) < RECOMMEND_COUNT:
        avoid = list(avoid_names) + [p["recipe"]["name"] for p in picks]
        picks += recommend_from_ai(fridge, RECOMMEND_COUNT - len(picks), avoid)
    return picks, notice

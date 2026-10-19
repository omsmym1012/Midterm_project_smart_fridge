"""냉장고 데이터를 JSON 파일에 저장하고 불러오는 모듈.

화면(app.py)과 데이터 처리를 나눠 두면, 나중에 장보기 리스트나 AI 추천에서도
같은 함수를 그대로 가져다 쓸 수 있다.

[데이터 구조]
재료 하나(item)는 이름·단위가 같은 것끼리 한 줄로 합쳐지고,
그 안에 유통기한별 "묶음(batch)"을 여러 개 가진다.

    {
      "id": "...", "name": "우유", "unit": "팩", "status": "in_fridge",
      "category": "유제품·계란", "storage": "냉장", "tip": "개봉 후에는 ...",
      "batches": [
        {"id": "...", "expiry": "2026-10-18", "quantity": 1},
        {"id": "...", "expiry": "2026-10-25", "quantity": 2},
        {"id": "...", "expiry": null, "quantity": 1}      <- 기한 없음
      ]
    }
"""

import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path

# 데이터 파일 위치: 프로젝트 폴더 안의 data/fridge.json
# (.gitignore에 data/*.json이 있어서 개인 기록이 커밋되지 않는다)
DATA_FILE = Path(__file__).parent / "data" / "fridge.json"

# 수량 단위 선택지
UNITS = ["개", "g", "kg", "ml", "L", "팩", "봉지", "병", "캔", "단", "통", "모", "송이", "장"]

# 재료 상태: 냉장고에 있음 / 다 씀
# "다 씀" 재료는 지우지 않고 남겨 두었다가, 나중에 장보기 리스트에 추가할 때 쓴다.
STATUS_IN_FRIDGE = "in_fridge"
STATUS_USED = "used"

# 기한 없는 묶음을 정렬할 때 맨 뒤로 보내기 위한 아주 먼 날짜
_FAR_FUTURE = "9999-12-31"


# ---------------------------------------------------------------
# 파일 저장 / 불러오기
# ---------------------------------------------------------------
def load_items():
    """JSON 파일에서 재료 목록을 읽어 온다. 파일이 없으면 빈 목록을 돌려준다."""
    if not DATA_FILE.exists():
        return []
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except (json.JSONDecodeError, OSError):
        # 파일이 깨졌거나 읽을 수 없으면 앱이 멈추지 않도록 빈 목록으로 시작한다.
        return []
    return [_upgrade_old_item(item) for item in items]


def _upgrade_old_item(item):
    """예전 형식(묶음 없이 expiry/quantity를 바로 가진 재료)을 새 형식으로 바꾼다."""
    if "batches" not in item:
        item["batches"] = [
            {"id": _new_id(), "expiry": item.pop("expiry", None), "quantity": item.pop("quantity", 0)}
        ]
    return item


def save_items(items):
    """재료 목록을 JSON 파일에 저장한다.

    임시 파일에 먼저 쓴 뒤 바꿔치기해서, 저장 도중 앱이 꺼져도
    기존 파일이 반쯤 쓰인 채로 망가지지 않게 한다.
    """
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        # ensure_ascii=False: 한글을 \uXXXX가 아닌 그대로 저장해서 파일을 열어 봐도 읽을 수 있게 한다.
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, DATA_FILE)


# ---------------------------------------------------------------
# 작은 도우미 함수들
# ---------------------------------------------------------------
def _new_id():
    """재료·묶음마다 붙이는 고유 번호 (같은 이름이어도 구분하기 위해)"""
    return uuid.uuid4().hex


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _round(quantity):
    """0.1 + 0.2 = 0.30000000000000004 같은 소수점 오차를 없앤다."""
    return round(quantity, 3)


def normalize_name(name):
    """이름 비교용: 띄어쓰기를 모두 지우고 영문은 소문자로 바꾼다. 예: "대 파" → "대파" """
    return "".join(name.split()).lower()


def _expiry_key(batch):
    """정렬용 키: 기한 없는 묶음은 맨 뒤로 간다."""
    return batch["expiry"] or _FAR_FUTURE


def _find(items, item_id):
    """id로 재료를 찾는다. 없으면 None."""
    return next((item for item in items if item["id"] == item_id), None)


def find_all_by_name(items, name, exclude_id=None):
    """냉장고에 있는 재료 중 이름이 같은(띄어쓰기·대소문자 무시) 재료를 모두 찾는다.

    단위가 다르면 따로 줄을 만들 수 있으므로 여러 개일 수 있다. (예: 우유 팩, 우유 ml)
    """
    key = normalize_name(name)
    return [
        item for item in items
        if item["status"] == STATUS_IN_FRIDGE
        and item["id"] != exclude_id
        and normalize_name(item["name"]) == key
    ]


def find_in_fridge_by_name(items, name, unit=None, exclude_id=None):
    """이름이 같은 재료 하나를 찾는다. unit을 주면 단위까지 같은 재료만 찾는다. 없으면 None."""
    for item in find_all_by_name(items, name, exclude_id):
        if unit is None or item["unit"] == unit:
            return item
    return None


def _add_to_batches(item, expiry_str, quantity):
    """같은 기한의 묶음이 있으면 수량을 더하고, 없으면 새 묶음을 만든다."""
    for batch in item["batches"]:
        if batch["expiry"] == expiry_str:
            batch["quantity"] = _round(batch["quantity"] + quantity)
            return
    item["batches"].append({"id": _new_id(), "expiry": expiry_str, "quantity": quantity})
    item["batches"].sort(key=_expiry_key)


# ---------------------------------------------------------------
# 화면에 보여 줄 값 계산
# ---------------------------------------------------------------
def total_quantity(item):
    """모든 묶음의 수량 합계"""
    return _round(sum(batch["quantity"] for batch in item["batches"]))


def earliest_batch(item):
    """유통기한이 가장 빠른 묶음 (기한 없는 묶음은 가장 마지막)"""
    return min(item["batches"], key=_expiry_key)


def sorted_batches(item):
    """묶음을 유통기한이 빠른 순서로 정렬한다. (기한 없는 묶음은 맨 뒤)"""
    return sorted(item["batches"], key=_expiry_key)


def unclassified_items(items):
    """분류 정보가 없는 재료 (분류 기능이 생기기 전에 넣은 재료)"""
    return [item for item in items if item["status"] == STATUS_IN_FRIDGE and not item.get("category")]


def set_classification(items, item_id, classification):
    """재료에 분류 결과를 넣고 저장한다."""
    item = _find(items, item_id)
    item["category"] = classification["category"]
    item["storage"] = classification["storage"]
    item["tip"] = classification.get("tip", "")
    save_items(items)


def fridge_items_sorted(items):
    """냉장고에 남아 있는 재료만 골라 가장 빠른 유통기한 순서로 정렬한다."""
    in_fridge = [item for item in items if item["status"] == STATUS_IN_FRIDGE]
    return sorted(in_fridge, key=lambda item: _expiry_key(earliest_batch(item)))


def format_quantity(quantity, unit):
    """수량을 보기 좋게 표시한다. 예: 3.0 → "3개", 0.5 → "0.5kg" """
    if float(quantity).is_integer():
        quantity = int(quantity)
    return f"{quantity}{unit}"


def format_expiry(expiry_str):
    """날짜 표시. 올해면 "10/18", 다른 해면 "2027/01/05", 기한 없음이면 "기한 없음"."""
    if expiry_str is None:
        return "기한 없음"
    d = date.fromisoformat(expiry_str)
    if d.year == date.today().year:
        return f"{d.month}/{d.day}"
    return d.strftime("%Y/%m/%d")


# ---------------------------------------------------------------
# 재료 추가 / 사용 / 다 씀
# 각 함수는 (성공 여부, 안내 메시지)를 돌려준다. 화면은 이 메시지를 그대로 보여 준다.
# ---------------------------------------------------------------
def add_item(items, name, expiry, quantity, unit, classification=None, allow_new_unit=False):
    """재료를 추가한다. 이름과 단위가 같은 재료가 있으면 그 줄에 합친다.

    expiry: date 객체, 기한 없음이면 None
    classification: 분류 결과 {"category", "storage", "tip"}
                    (기존 줄에 합칠 때 주면 기존 줄의 분류도 이 값으로 바뀐다)
    allow_new_unit: 같은 이름이 다른 단위로만 있을 때, 사용자가 확인했으면 True → 새 줄로 추가
    """
    expiry_str = expiry.isoformat() if expiry else None
    same_unit = find_in_fridge_by_name(items, name, unit=unit)

    if same_unit:
        # 이름·단위가 같으면 기존 줄에 합친다.
        _add_to_batches(same_unit, expiry_str, quantity)
        if classification:
            same_unit["category"] = classification["category"]
            same_unit["storage"] = classification["storage"]
            same_unit["tip"] = classification.get("tip", "")
        save_items(items)
        return True, f"'{same_unit['name']}'에 {format_quantity(quantity, unit)}을(를) 더했어요."

    other_units = [item["unit"] for item in find_all_by_name(items, name)]
    if other_units and not allow_new_unit:
        # 같은 이름이 다른 단위로만 있으면 합칠 수 없다. 사용자 확인 없이는 추가하지 않는다.
        return False, (
            f"'{name}'은(는) 이미 '{', '.join(other_units)}' 단위로 있어요. "
            "단위가 달라서 따로 추가돼요."
        )

    items.append(
        {
            "id": _new_id(),
            "name": name,
            "unit": unit,
            "status": STATUS_IN_FRIDGE,
            "category": (classification or {}).get("category"),
            "storage": (classification or {}).get("storage"),
            "tip": (classification or {}).get("tip", ""),
            "added_at": _now(),
            "batches": [{"id": _new_id(), "expiry": expiry_str, "quantity": quantity}],
        }
    )
    save_items(items)
    return True, f"'{name}'을(를) 냉장고에 넣었어요."


def use_quantity(items, item_id, amount):
    """재료를 일부 사용한다. 유통기한이 빠른 묶음부터 차감하고, 다 쓰면 "다 씀" 처리한다."""
    item = _find(items, item_id)
    total = total_quantity(item)
    if amount > total:
        return False, f"남은 양({format_quantity(total, item['unit'])})보다 많이 쓸 수 없어요."

    remaining = amount
    for batch in sorted(item["batches"], key=_expiry_key):
        take = min(batch["quantity"], remaining)
        batch["quantity"] = _round(batch["quantity"] - take)
        remaining = _round(remaining - take)
        if remaining <= 0:
            break
    # 수량이 0이 된 묶음은 정리한다.
    item["batches"] = [batch for batch in item["batches"] if batch["quantity"] > 0]

    if not item["batches"]:
        # 전부 썼으면 "다 씀"과 똑같이 처리한다.
        return mark_used(items, item_id)

    save_items(items)
    return True, (
        f"'{item['name']}' {format_quantity(amount, item['unit'])} 사용했어요. "
        f"남은 양: {format_quantity(total_quantity(item), item['unit'])}"
    )


def mark_used(items, item_id):
    """재료 전체를 "다 씀" 상태로 바꾼다. (나중에 장보기 리스트에서 사용)"""
    item = _find(items, item_id)
    item["status"] = STATUS_USED
    item["used_at"] = _now()
    item["batches"] = []  # 남은 양이 없으므로 묶음을 비운다.
    save_items(items)
    return True, f"'{item['name']}'을(를) 다 썼어요."


# ---------------------------------------------------------------
# 수정 / 삭제 (재료 줄 전체)
# ---------------------------------------------------------------
def update_item(items, item_id, new_name, new_unit, category, storage, tip):
    """재료의 이름·단위·분류(종류, 보관 방법, 팁)를 수정한다."""
    item = _find(items, item_id)
    # 이름·단위가 둘 다 같은 줄이 생기면 어느 줄에 합쳐야 할지 모호해지므로 막는다.
    if find_in_fridge_by_name(items, new_name, unit=new_unit, exclude_id=item_id):
        return False, f"'{new_name}'은(는) 이미 '{new_unit}' 단위로 냉장고에 있어요. 이름이나 단위를 바꿔 주세요."
    item["name"] = new_name
    item["unit"] = new_unit
    item["category"] = category
    item["storage"] = storage
    item["tip"] = tip
    save_items(items)
    return True, f"'{new_name}' 정보를 수정했어요."


def delete_item(items, item_id):
    """재료를 기록까지 완전히 지운다. (잘못 입력한 재료를 지울 때 사용)"""
    item = _find(items, item_id)
    items[:] = [i for i in items if i["id"] != item_id]
    save_items(items)
    return True, f"'{item['name']}'을(를) 삭제했어요."


# ---------------------------------------------------------------
# 수정 / 삭제 (유통기한별 묶음 하나)
# ---------------------------------------------------------------
def update_batch(items, item_id, batch_id, new_expiry, new_quantity):
    """묶음 하나의 유통기한과 수량을 수정한다.

    바꾼 기한이 다른 묶음과 같아지면 두 묶음을 하나로 합친다.
    """
    item = _find(items, item_id)
    expiry_str = new_expiry.isoformat() if new_expiry else None
    # 수정할 묶음을 빼낸 뒤, 바뀐 값으로 다시 넣는다. (같은 기한이 있으면 자동으로 합쳐짐)
    item["batches"] = [batch for batch in item["batches"] if batch["id"] != batch_id]
    _add_to_batches(item, expiry_str, new_quantity)
    save_items(items)
    return True, "묶음 정보를 수정했어요."


def discard_batches(items, item_id, batch_ids):
    """기한 지난 묶음들을 버린다. (장보기에 담으면서 "버리기"를 골랐을 때)

    남은 묶음이 없으면 재료 전체를 "다 씀" 상태로 바꾼다.
    """
    item = _find(items, item_id)
    item["batches"] = [batch for batch in item["batches"] if batch["id"] not in batch_ids]
    if not item["batches"]:
        mark_used(items, item_id)
    else:
        save_items(items)


def expired_batches(item, today=None):
    """재료의 묶음 중 기한이 지난 것들"""
    return [b for b in item["batches"] if expiry_status(b["expiry"], today) == STATUS_EXPIRED]


def soon_batches(item, today=None):
    """재료의 묶음 중 기한이 3일 이내로 남은 것들 (오늘 포함)"""
    return [b for b in item["batches"] if expiry_status(b["expiry"], today) == STATUS_SOON]


def used_items(items):
    """"다 씀" 상태인 재료 기록들"""
    return [item for item in items if item["status"] == STATUS_USED]


def delete_batch(items, item_id, batch_id):
    """묶음 하나를 지운다. 마지막 묶음이었다면 재료 줄도 함께 지운다."""
    item = _find(items, item_id)
    item["batches"] = [batch for batch in item["batches"] if batch["id"] != batch_id]
    if not item["batches"]:
        return delete_item(items, item_id)
    save_items(items)
    return True, "묶음을 삭제했어요."


# ---------------------------------------------------------------
# 유통기한 알림 (기한 지남 / 3일 이내 / 여유 / 기한 없음)
# ---------------------------------------------------------------
SOON_DAYS = 3  # 오늘부터 며칠 뒤까지를 "임박"으로 볼지

STATUS_EXPIRED = "expired"  # 기한 지남
STATUS_SOON = "soon"        # 오늘 ~ 3일 뒤
STATUS_OK = "ok"            # 여유
STATUS_NO_EXPIRY = "none"   # 기한 없음


def days_left(expiry_str, today=None):
    """기한까지 남은 날 수. 오늘이 기한이면 0, 어제였으면 -1. 기한 없음이면 None."""
    if expiry_str is None:
        return None
    today = today or date.today()
    return (date.fromisoformat(expiry_str) - today).days


def expiry_status(expiry_str, today=None):
    """유통기한 상태를 4가지 중 하나로 알려 준다."""
    days = days_left(expiry_str, today)
    if days is None:
        return STATUS_NO_EXPIRY
    if days < 0:
        return STATUS_EXPIRED
    if days <= SOON_DAYS:
        return STATUS_SOON
    return STATUS_OK


def d_day_label(expiry_str, today=None):
    """D-day 글자. 예: "D-3", "D-day", "D+2 지남", "기한 없음" """
    days = days_left(expiry_str, today)
    if days is None:
        return "기한 없음"
    if days < 0:
        return f"D+{-days} 지남"
    if days == 0:
        return "D-day"
    return f"D-{days}"


def expiry_summary(items, today=None):
    """냉장고 재료를 상태별로 나눈다. 재료마다 가장 빠른 기한을 기준으로 한다.

    반환 예: {"expired": [재료, ...], "soon": [...], "ok": [...], "none": [...]}
    """
    groups = {STATUS_EXPIRED: [], STATUS_SOON: [], STATUS_OK: [], STATUS_NO_EXPIRY: []}
    for item in fridge_items_sorted(items):
        status = expiry_status(earliest_batch(item)["expiry"], today)
        groups[status].append(item)
    return groups


# ---------------------------------------------------------------
# 냉장고 칸 (보관 위치)
# 재료의 "zone" 값에 칸 id를 저장한다. 값이 없으면(None) 아직 칸에 넣지 않은 새 재료다.
# ---------------------------------------------------------------
ZONES = {
    "top": "냉장 위칸",
    "middle": "냉장 가운데칸",
    "bottom": "냉장 아래칸",
    "crisper": "신선칸",
    "door": "냉장 문칸",
    "freezer": "냉동 칸",
    "freezer_door": "냉동 문칸",
    "outside": "냉장고 밖",
}

# 냉장 보관 재료의 종류별 추천 칸
# - 채소·과일: 습도가 유지되는 신선칸
# - 육류·해산물: 가장 차가운 아래칸 (핏물이 다른 재료에 떨어지지 않게)
# - 양념·소스·음료: 자주 꺼내고 온도 변화에 강해서 문칸
ZONE_BY_CATEGORY = {
    "채소": "crisper",
    "과일": "crisper",
    "육류": "bottom",
    "해산물": "bottom",
    "유제품·계란": "middle",
    "양념·소스": "door",
    "음료": "door",
    "곡류·면": "top",
    "가공·냉동식품": "top",
    "밀키트·간편식": "middle",
}


# 칸마다 맞는 보관 방법 (적혀 있지 않은 칸은 냉장)
ZONE_STORAGE = {"freezer": "냉동", "freezer_door": "냉동", "outside": "실온"}


def zone_fits_storage(zone, storage):
    """칸이 재료의 보관 방법과 맞는지. (예: 냉동 보관 재료를 신선칸에 추천하지 않기 위해)"""
    return ZONE_STORAGE.get(zone, "냉장") == (storage or "냉장")


def recommend_zone(item):
    """보관 방법과 종류를 보고 추천 칸 id를 정한다. (이름으로 못 찾았을 때 쓰는 규칙)"""
    if item.get("storage") == "냉동":
        return "freezer"
    if item.get("storage") == "실온":
        return "outside"
    return ZONE_BY_CATEGORY.get(item.get("category"), "middle")


def set_zone(items, item_id, zone):
    """재료를 다른 칸으로 옮긴다. zone이 None이면 "새 재료"로 되돌린다. 바뀌었으면 True."""
    item = _find(items, item_id)
    if item is None or (zone is not None and zone not in ZONES) or item.get("zone") == zone:
        return False
    item["zone"] = zone
    save_items(items)
    return True

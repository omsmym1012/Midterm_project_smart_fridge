"""장보기 리스트 데이터를 JSON 파일에 저장하고 불러오는 모듈.

[데이터 구조] data/shopping.json
    {
      "items": [
        {"id": "...", "name": "우유", "quantity": 1, "unit": "팩",
         "source": "used", "checked": false, "added_at": "..."}
      ],
      "handled": ["used:<재료 id>", "expired:<묶음 id>", "soon:<묶음 id>", ...]
    }

- source: 어디서 왔는지 ("used" 다 쓴 재료 / "expired" 기한 지난 재료 / "soon" 기한 임박 재료 / "manual" 직접 추가)
- checked: "샀어요" 체크 여부
- handled: 추천 목록에서 이미 [담기]나 [안 살래요]를 누른 항목.
           다시 추천하지 않도록 기억해 둔다.
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import fridge_store

# 데이터 파일 위치 (.gitignore의 data/*.json에 포함되어 커밋되지 않음)
DATA_FILE = Path(__file__).parent / "data" / "shopping.json"

SOURCE_USED = "used"
SOURCE_EXPIRED = "expired"
SOURCE_SOON = "soon"
SOURCE_MANUAL = "manual"


# ---------------------------------------------------------------
# 파일 저장 / 불러오기
# ---------------------------------------------------------------
def load():
    """장보기 데이터를 읽어 온다. 파일이 없거나 깨졌으면 빈 데이터로 시작한다."""
    empty = {"items": [], "handled": []}
    if not DATA_FILE.exists():
        return empty
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return empty
    return {"items": data.get("items", []), "handled": data.get("handled", [])}


def save(data):
    """임시 파일에 먼저 쓴 뒤 바꿔치기해서, 저장 도중 꺼져도 파일이 망가지지 않게 한다."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, DATA_FILE)


# ---------------------------------------------------------------
# 장보기 항목 추가 / 체크 / 삭제
# ---------------------------------------------------------------
def find_by_name(data, name):
    """장보기 리스트에서 이름이 같은(띄어쓰기·대소문자 무시) 항목을 찾는다."""
    key = fridge_store.normalize_name(name)
    for item in data["items"]:
        if fridge_store.normalize_name(item["name"]) == key:
            return item
    return None


def add_item(data, name, quantity, unit, source=SOURCE_MANUAL):
    """장보기 항목을 추가한다. 같은 이름이 이미 있으면 추가하지 않고 알려 준다."""
    if find_by_name(data, name):
        return False, f"'{name}'은(는) 이미 장보기 리스트에 있어요."
    data["items"].append(
        {
            "id": uuid.uuid4().hex,
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "source": source,
            "checked": False,
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    save(data)
    return True, f"'{name}'을(를) 장보기 리스트에 담았어요."


def set_checked(data, item_id, checked):
    """"샀어요" 체크 상태를 바꾼다."""
    for item in data["items"]:
        if item["id"] == item_id:
            item["checked"] = checked
    save(data)


def remove_items(data, item_ids):
    """장보기 항목들을 지운다."""
    data["items"] = [item for item in data["items"] if item["id"] not in item_ids]
    save(data)


def checked_items(data):
    return [item for item in data["items"] if item["checked"]]


def unchecked_count(data):
    """아직 안 산 항목 개수 (사이드바 메뉴에 표시)"""
    return sum(1 for item in data["items"] if not item["checked"])


# ---------------------------------------------------------------
# "다시 살까요?" 추천 목록
# ---------------------------------------------------------------
def mark_handled(data, keys):
    """추천 항목에 [담기]/[안 살래요]를 눌렀다고 기억한다. 다시 추천하지 않는다."""
    for key in keys:
        if key not in data["handled"]:
            data["handled"].append(key)
    save(data)


def candidates(fridge_items, data):
    """장보기에 담을 만한 재료 후보를 만든다.

    1) 기한 지난 재료: 냉장고에 있는 재료 중 기한 지난 묶음이 있는 것
    2) 기한 임박 재료: 기한이 3일 이내로 남은 묶음이 있는 것
    3) 다 쓴 재료: "다 씀" 기록 (같은 이름이 여러 번 있으면 하나로)

    이미 장보기 리스트에 있거나, 이미 처리한(handled) 것은 빼고,
    지금 냉장고에 같은 이름이 남아 있는 "다 쓴 재료"도 뺀다. (또 살 필요가 적으니까)

    반환 예: [{"kind": "expired", "name": "우유", "unit": "팩", "keys": [...],
               "item_id": "...", "batch_ids": [...], "detail": "10/14 1팩"}, ...]
    """
    handled = set(data["handled"])
    result = []
    seen_names = set()

    def already_listed(name):
        return find_by_name(data, name) or fridge_store.normalize_name(name) in seen_names

    def batch_text(batches, unit):
        return ", ".join(
            f"{fridge_store.format_expiry(b['expiry'])} {fridge_store.format_quantity(b['quantity'], unit)}"
            for b in batches
        )

    # 1) 기한 지난 재료 → 2) 기한 임박(3일 이내) 재료
    # 한 재료에 지난 묶음과 임박 묶음이 같이 있으면 "기한 지남" 후보 하나로 보여 준다.
    for item in fridge_store.fridge_items_sorted(fridge_items):
        expired = [b for b in fridge_store.expired_batches(item) if f"expired:{b['id']}" not in handled]
        soon = [b for b in fridge_store.soon_batches(item) if f"soon:{b['id']}" not in handled]
        if not (expired or soon) or already_listed(item["name"]):
            continue
        seen_names.add(fridge_store.normalize_name(item["name"]))
        # 임박 묶음 키도 함께 처리해서, 나중에 같은 묶음이 또 추천되지 않게 한다.
        keys = [f"expired:{b['id']}" for b in expired] + [f"soon:{b['id']}" for b in soon]
        if expired:
            kind, detail = SOURCE_EXPIRED, f"기한 지남 · {batch_text(expired, item['unit'])}"
        else:
            kind, detail = SOURCE_SOON, f"{fridge_store.SOON_DAYS}일 이내 · {batch_text(soon, item['unit'])}"
        result.append(
            {
                "kind": kind,
                "name": item["name"],
                "unit": item["unit"],
                "keys": keys,
                "item_id": item["id"],
                "batch_ids": [b["id"] for b in expired],  # 버릴 수 있는 건 지난 묶음뿐
                "detail": detail,
            }
        )

    # 3) 다 쓴 재료 (최근에 다 쓴 것부터)
    used = sorted(fridge_store.used_items(fridge_items), key=lambda i: i.get("used_at", ""), reverse=True)
    for item in used:
        key = f"used:{item['id']}"
        if key in handled:
            continue
        if fridge_store.find_in_fridge_by_name(fridge_items, item["name"]):
            continue  # 냉장고에 같은 재료가 아직 있음
        norm = fridge_store.normalize_name(item["name"])
        if norm in seen_names:
            # 같은 이름의 "다 씀" 기록이 또 있으면 앞의 후보에 키만 합친다.
            for candidate in result:
                if fridge_store.normalize_name(candidate["name"]) == norm:
                    candidate["keys"].append(key)
            continue
        if find_by_name(data, item["name"]):
            continue
        seen_names.add(norm)
        used_date = item.get("used_at", "")[:10]
        result.append(
            {
                "kind": SOURCE_USED,
                "name": item["name"],
                "unit": item["unit"],
                "keys": [key],
                "item_id": item["id"],
                "batch_ids": [],
                "detail": f"다 씀 · {fridge_store.format_expiry(used_date) if used_date else ''}",
            }
        )
    return result

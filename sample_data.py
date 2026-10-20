"""테스트용 데이터 (사이드바 '🧪 테스트 데이터 넣기' 버튼)

배포 사이트는 다시 배포할 때마다 data/ 폴더가 비워지므로,
버튼 한 번으로 냉장고·다 쓴 기록·장보기를 같은 상태로 채워서 빠르게 테스트한다.

유통기한은 "오늘부터 며칠 뒤"로 적어 두어서, 언제 넣어도
기한 지남 / 3일 이내 / 여유 / 기한 없음이 골고루 섞인다.
분류(종류·보관·팁)는 classifier의 미리 만든 목록에서 가져온다. (AI를 부르지 않음)
"""

from datetime import date, datetime, timedelta

import classifier
import fridge_store
import shopping_store

# 냉장고 재료: (이름, 단위, [(오늘부터 며칠 뒤 또는 None=기한 없음, 수량), ...], 칸 또는 None=새 재료)
FRIDGE = [
    ("우유", "팩", [(-2, 1), (5, 1)], "door"),       # 기한 지난 묶음 + 여유 묶음
    ("시금치", "단", [(-1, 1)], None),               # 기한 지남
    ("버섯", "팩", [(0, 1)], None),                  # D-day
    ("두부", "모", [(1, 1)], "middle"),              # 3일 이내
    ("대파", "단", [(2, 1)], None),
    ("돼지고기", "g", [(3, 300)], "bottom"),
    ("사과", "개", [(6, 3)], None),                  # 여유
    ("당근", "개", [(7, 2)], None),
    ("계란", "개", [(10, 10)], "middle"),
    ("치즈", "장", [(12, 5)], None),
    ("햄", "개", [(15, 1)], None),
    ("김치", "통", [(20, 1)], "bottom"),
    ("양파", "개", [(None, 3)], "outside"),          # 기한 없음
    ("고추장", "통", [(None, 1)], "door"),
    ("만두", "봉지", [(None, 1)], "freezer"),
]

# 다 쓴 기록: (이름, 단위, 며칠 전에 다 썼는지) → 장보기 '다시 살까요?' 후보로 나온다.
USED = [
    ("콩나물", "봉지", 1),
    ("요거트", "개", 3),
]

# 장보기 리스트: (이름, 수량, 단위, 샀어요 체크 여부)
SHOPPING = [
    ("라면", 5, "개", False),
    ("바나나", 1, "송이", False),
    ("식빵", 1, "봉지", True),    # 체크해 두어서 '산 재료 냉장고에 넣기'를 바로 테스트할 수 있다
]


def _item(name, unit, batches, zone=None, status=fridge_store.STATUS_IN_FRIDGE):
    """냉장고 재료 한 줄을 fridge_store와 같은 모양으로 만든다."""
    info = classifier.classify(name)
    today = date.today()
    return {
        "id": fridge_store._new_id(),
        "name": name,
        "unit": unit,
        "status": status,
        "category": info["category"],
        "storage": info["storage"],
        "tip": info.get("tip", ""),
        "added_at": fridge_store._now(),
        "zone": zone,
        "batches": [
            {
                "id": fridge_store._new_id(),
                "expiry": None if days is None else (today + timedelta(days=days)).isoformat(),
                "quantity": quantity,
            }
            for days, quantity in batches
        ],
    }


def load_sample():
    """지금 데이터를 지우고 테스트 데이터로 바꾼다. (냉장고·다 쓴 기록·장보기 전부)"""
    items = [_item(name, unit, batches, zone) for name, unit, batches, zone in FRIDGE]
    for name, unit, days_ago in USED:
        item = _item(name, unit, [], status=fridge_store.STATUS_USED)
        item["used_at"] = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        items.append(item)
    fridge_store.save_items(items)

    shopping = {"items": [], "handled": []}
    for name, quantity, unit, checked in SHOPPING:
        shopping_store.add_item(shopping, name, quantity, unit, shopping_store.SOURCE_MANUAL)
        shopping["items"][-1]["checked"] = checked
    shopping_store.save(shopping)

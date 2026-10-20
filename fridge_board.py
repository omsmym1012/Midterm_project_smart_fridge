"""냉장고 칸 모양 화면 (드래그 앤 드롭 컴포넌트)

Streamlit 기본 위젯에는 드래그 앤 드롭이 없어서, st.components.v2로
HTML·CSS·JavaScript를 직접 넣은 작은 컴포넌트를 만든다.

- 왼쪽: 냉장고 그림 (위에서부터 냉동실 칸 + 문칸, 냉장실 위/가운데/아래/신선칸 + 문칸, 냉장고 밖)
- 오른쪽: 아직 칸에 넣지 않은 "새 재료"
- 재료를 마우스(또는 손가락)로 잡으면 추천 칸 색이 연하게 바뀌고,
  다른 칸에 놓으면 Python으로 {"item_id", "zone"}을 보낸다. ("move" 이벤트)
- 끌지 않고 누르기만 하면 재료 id를 보낸다. ("select" 이벤트 → 상세 팝업)
"""

import streamlit as st

import classifier
import fridge_store as store

# 컴포넌트 모양
CSS = """
.fb-root {
    --fb-line: var(--st-border-color, rgba(128, 128, 128, 0.4));
    position: relative;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    color: var(--st-text-color, inherit);
    font-family: var(--st-font, inherit);
    user-select: none;
    -webkit-user-select: none;
}
.fb-fridge { flex: 3 1 320px; display: flex; flex-direction: column; gap: 8px; }
.fb-section {
    border: 3px solid var(--fb-line);
    border-radius: 14px;
    padding: 8px;
    display: grid;
    grid-template-columns: 1fr 34%;
    gap: 6px;
}
.fb-section-title { grid-column: 1 / -1; font-weight: 700; font-size: 0.85rem; }
.fb-shelves { display: flex; flex-direction: column; gap: 6px; }
.fb-zone {
    border: 1.5px dashed var(--fb-line);
    border-radius: 10px;
    padding: 6px;
    min-height: 56px;
    transition: background-color 0.15s, border-color 0.15s;
}
.fb-door { height: 100%; box-sizing: border-box; }
.fb-tray { flex: 1 1 160px; align-self: flex-start; }
.fb-zone-title { font-size: 0.75rem; opacity: 0.7; margin-bottom: 4px; }
.fb-list { display: flex; flex-wrap: wrap; gap: 4px; min-height: 28px; }
.fb-list:empty::after { content: attr(data-empty); font-size: 0.75rem; opacity: 0.5; }

/* 재료 카드: 왼쪽 굵은 선 색 = 유통기한 상태 */
.fb-chip {
    display: inline-flex;
    flex-direction: column;
    padding: 3px 8px;
    border-radius: 8px;
    background: var(--st-background-color, #fff);
    border: 1px solid var(--fb-line);
    border-left: 5px solid var(--fb-status);
    cursor: pointer;
    touch-action: none;
    font-size: 0.8rem;
    line-height: 1.25;
}
.fb-meta { font-size: 0.7rem; opacity: 0.7; }
.fb-expired { --fb-status: #e5484d; }
.fb-soon { --fb-status: #f5a524; }
.fb-ok { --fb-status: #30a46c; }
.fb-none { --fb-status: #9ba1a6; }

/* 추천 칸 (재료를 짚었을 때) / 지금 놓으려는 칸 */
.fb-zone.fb-recommend { background: rgba(48, 164, 108, 0.12); border-color: #30a46c; }
.fb-zone.fb-over { background: rgba(59, 130, 246, 0.15); border-style: solid; border-color: #3b82f6; }

/* 끌고 다니는 카드와, 원래 자리에 남는 흐린 카드 */
.fb-ghost {
    position: absolute;
    z-index: 10;
    pointer-events: none;
    opacity: 0.9;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    cursor: grabbing;
}
.fb-placeholder { opacity: 0.35; }
"""

# 컴포넌트 동작
# 재료 이름은 사용자가 입력한 글자이므로 innerHTML이 아니라 textContent로만 넣는다. (스크립트 실행 방지)
JS = """
export default function (component) {
    const { data, parentElement, setTriggerValue } = component;

    // 화면이 다시 그려질 때마다 이전 내용을 지우고 새로 만든다.
    const old = parentElement.querySelector(".fb-root");
    if (old) old.remove();
    const root = document.createElement("div");
    root.className = "fb-root";
    parentElement.appendChild(root);

    const titles = data.zones;      // 칸 id → 칸 이름
    const lists = {};               // 칸 id → 재료 카드가 들어가는 영역
    const zoneBoxes = [];           // 재료를 놓을 수 있는 칸들 ("새 재료" 포함)
    let dragging = null;            // 지금 끌고 있는 재료 정보

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function makeZone(id, title, extraClass) {
        const box = el("div", "fb-zone " + (extraClass || ""));
        box.dataset.zone = id;
        const list = el("div", "fb-list");
        box.append(el("div", "fb-zone-title", title), list);
        lists[id] = list;
        zoneBoxes.push(box);
        return box;
    }

    // 냉장실 / 냉동실: 왼쪽은 선반들, 오른쪽은 문칸
    function makeSection(title, shelfIds, doorId) {
        const section = el("div", "fb-section");
        const shelves = el("div", "fb-shelves");
        shelfIds.forEach((id) => shelves.appendChild(makeZone(id, titles[id])));
        section.append(el("div", "fb-section-title", title), shelves, makeZone(doorId, titles[doorId], "fb-door"));
        return section;
    }

    const fridge = el("div", "fb-fridge");
    // 위에서부터 냉동실 → 냉장실 → 냉장고 밖 (일반 가정용 냉장고처럼 냉동실이 위)
    fridge.append(
        makeSection("❄️ 냉동실", ["freezer"], "freezer_door"),
        makeSection("🧊 냉장실", ["top", "middle", "bottom", "crisper"], "door"),
        makeZone("outside", titles.outside + " (실온)")
    );
    const tray = makeZone("tray", "🆕 새 재료", "fb-tray");
    lists.tray.dataset.empty = "새 재료가 없어요";
    root.append(fridge, tray);

    function setRecommend(zoneId, on) {
        zoneBoxes.forEach((box) => box.classList.toggle("fb-recommend", on && box.dataset.zone === zoneId));
    }

    // 손가락/마우스 위치에 있는 칸 찾기
    function zoneAt(x, y) {
        return zoneBoxes.find((box) => {
            const r = box.getBoundingClientRect();
            return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
        });
    }

    function makeChip(item) {
        const chip = el("div", "fb-chip fb-" + item.status);
        chip.append(el("span", "fb-name", item.name), el("span", "fb-meta", item.meta));
        chip.title = "추천 칸: " + titles[item.recommend];

        chip.addEventListener("pointerenter", () => { if (!dragging) setRecommend(item.recommend, true); });
        chip.addEventListener("pointerleave", () => { if (!dragging) setRecommend(item.recommend, false); });
        chip.addEventListener("pointerdown", (event) => startDrag(event, chip, item));
        return chip;
    }

    // 끌기: 포인터 이벤트를 써서 마우스와 터치에서 똑같이 동작하게 한다.
    function startDrag(event, chip, item) {
        if (event.button !== 0) return;
        event.preventDefault();
        chip.setPointerCapture(event.pointerId);
        const rect = chip.getBoundingClientRect();
        const offsetX = event.clientX - rect.left;
        const offsetY = event.clientY - rect.top;
        const startX = event.clientX;
        const startY = event.clientY;
        let ghost = null;
        let over = null;
        dragging = item;
        setRecommend(item.recommend, true);

        function onMove(e) {
            // 조금이라도 움직였을 때부터 끌기로 본다. (그냥 누른 건 무시)
            if (!ghost) {
                if (Math.abs(e.clientX - startX) + Math.abs(e.clientY - startY) < 5) return;
                ghost = chip.cloneNode(true);
                ghost.classList.add("fb-ghost");
                ghost.style.width = rect.width + "px";
                root.appendChild(ghost);
                chip.classList.add("fb-placeholder");
            }
            const base = root.getBoundingClientRect();
            ghost.style.left = e.clientX - base.left - offsetX + "px";
            ghost.style.top = e.clientY - base.top - offsetY + "px";
            const target = zoneAt(e.clientX, e.clientY) || null;
            if (target !== over) {
                if (over) over.classList.remove("fb-over");
                if (target) target.classList.add("fb-over");
                over = target;
            }
        }

        function onEnd(e) {
            chip.removeEventListener("pointermove", onMove);
            chip.removeEventListener("pointerup", onEnd);
            chip.removeEventListener("pointercancel", onEnd);
            if (chip.hasPointerCapture(e.pointerId)) chip.releasePointerCapture(e.pointerId);
            if (over) over.classList.remove("fb-over");
            chip.classList.remove("fb-placeholder");
            setRecommend(item.recommend, false);
            dragging = null;
            if (!ghost) {
                // 움직이지 않고 손을 뗐으면 "누르기"로 보고 상세 팝업을 연다.
                if (e.type === "pointerup") setTriggerValue("select", item.id);
                return;
            }
            ghost.remove();

            const target = e.type === "pointerup" ? zoneAt(e.clientX, e.clientY) : null;
            if (!target || chip.parentElement === lists[target.dataset.zone]) return;
            // 화면에서 먼저 옮겨 두고, Python에 알려서 저장한다.
            lists[target.dataset.zone].appendChild(chip);
            const zone = target.dataset.zone === "tray" ? null : target.dataset.zone;
            setTriggerValue("move", { item_id: item.id, zone: zone });
        }

        chip.addEventListener("pointermove", onMove);
        chip.addEventListener("pointerup", onEnd);
        chip.addEventListener("pointercancel", onEnd);
    }

    data.items.forEach((item) => {
        const zone = item.zone && lists[item.zone] ? item.zone : "tray";
        lists[zone].appendChild(makeChip(item));
    });
}
"""

# 컴포넌트 등록 (이 파일이 처음 import될 때 한 번만 실행된다)
_board = st.components.v2.component("fridge_board", css=CSS, js=JS)


def recommend(item, cache):
    """추천 칸: 이름으로 찾은 칸(목록·AI)을 먼저 쓰고, 없거나 보관 방법과 안 맞으면 종류 규칙을 쓴다."""
    zone = classifier.name_zone(item["name"], cache)
    if zone and store.zone_fits_storage(zone, item.get("storage")):
        return zone
    return store.recommend_zone(item)


def _board_data(items):
    """컴포넌트에 넘길 데이터: 칸 이름과 냉장고 재료 목록"""
    cache = classifier.load_cache()  # 재료마다 파일을 읽지 않도록 한 번만 읽는다.
    data_items = []
    for item in store.fridge_items_sorted(items):
        first = store.earliest_batch(item)
        data_items.append(
            {
                "id": item["id"],
                "name": item["name"],
                "meta": f"{store.format_quantity(store.total_quantity(item), item['unit'])} · "
                f"{store.d_day_label(first['expiry'])}",
                "status": store.expiry_status(first["expiry"]),
                "zone": item.get("zone"),
                "recommend": recommend(item, cache),
            }
        )
    return {"zones": store.ZONES, "items": data_items}


def fridge_board(items, key, on_move, on_select):
    """냉장고 칸 화면을 그린다.

    재료를 다른 칸에 놓으면 on_move, 누르면 on_select가 화면을 다시 그리기 전에 먼저 실행된다.
    그 안에서 st.session_state[key]["move"]로 {"item_id", "zone"}을,
    st.session_state[key]["select"]로 누른 재료 id를 읽을 수 있다.
    """
    _board(data=_board_data(items), key=key, on_move_change=on_move, on_select_change=on_select)

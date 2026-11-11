"""공통 언어 v0 (티켓 #31) — 엔진이 **지금 실제로 쓰는** 개념(부품)과 관계의 목록.

- 이 목록은 설계 문서가 아니라 코드의 거울이다. 코어 데이터 클래스·상태·행동·사건이 바뀌면
  `tests/test_vocabulary.py` 가 이 목록과 생성 문서(docs/11-COMMON-LANGUAGE.md)의 불일치를 잡는다.
- 관계(LINKS)는 id 문자열로 이어지는 의미상 연결이라 타입 표기만으로는 보이지 않는다. 그래서 손으로 적되,
  각 관계의 출발 필드가 코드에 실제로 있는지 테스트가 확인한다.
- 다른 산업(환경 B·C)을 보고 미리 넣은 개념은 없다 (이식성 실험 오염 방지, #31).

    uv run python -m asel.vocabulary   # 문서 재생성
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from asel.core import model
from asel.core.actions import ActionKind
from asel.core.events import EventType

# ------------------------------------------------------------------ 개념(부품)

CONCEPTS: dict[str, str] = {
    "Entity": "셀·설비·작업장 같은 '일을 하는 곳'. 산업별 의미는 type 과 capabilities 로만 표현한다",
    "Resource": "용량이 있는 자원. 동시에 처리할 수 있는 작업 수(capacity), 예약(holders), 고장 단위(out_of_service)",
    "Task": "처리해야 할 일 한 단위. 필요한 역할(capability), 선행 작업(predecessors), 생명주기(status)",
    "Relation": "개체 사이의 연결 (예: 물자 흐름). v0 에서는 기록만 하고 흐름 제약으로 쓰지 않는다",
    "WorldState": "세계의 현재 상태. version(모든 변경), structure_version(구조 변경), 시각",
    "TaskStatus": "작업 생명주기: CREATED → WAITING → READY → RUNNING → COMPLETED (예외: BLOCKED/FAILED/CANCELLED)",
    "EntityMode": "개체의 재구성 상태: normal / draining(새 작업 중단) / changeover(역할 전환 중)",
}

# 개념에 속하지 않는 '값' 개념: capability 는 문자열 라벨이다 (산업별 의미는 시나리오가 준다)
VALUE_CONCEPTS: dict[str, str] = {
    "capability": "어떤 일을 할 수 있는지 나타내는 라벨 (예: pick, pack). Task 가 요구하고 Entity 가 제공한다",
}

# ------------------------------------------------------------------ 관계 (출발 개념.필드 → 도착 개념)

LINKS: list[tuple[str, str, str, str]] = [
    # (출발 개념, 출발 필드, 도착, 의미)
    ("Task", "predecessors", "Task", "먼저 끝나야 하는 작업 (여러 개 가능 = 갈라짐·합침 흐름)"),
    ("Task", "assigned_entity", "Entity", "작업이 실행되는 곳"),
    ("Task", "capability", "capability", "작업이 요구하는 역할"),
    ("Task", "status", "TaskStatus", "작업 상태"),
    ("Entity", "capabilities", "capability", "개체가 제공하는 역할"),
    ("Entity", "target_capabilities", "capability", "재구성 후 제공할 역할"),
    ("Entity", "mode", "EntityMode", "재구성 상태"),
    ("Resource", "id", "Entity", "자원은 같은 id 의 개체에 속한다 (v0: 개체당 자원 1개)"),
    ("Resource", "holders", "Task", "자원을 예약 중인(실행 중인) 작업"),
    ("Relation", "source", "Entity", "연결의 출발"),
    ("Relation", "target", "Entity", "연결의 도착"),
    ("WorldState", "entities", "Entity", "세계에 있는 개체"),
    ("WorldState", "resources", "Resource", "세계에 있는 자원"),
    ("WorldState", "tasks", "Task", "세계에 있는 작업"),
    ("WorldState", "relations", "Relation", "세계에 있는 연결"),
]

# ------------------------------------------------------------------ 행동·사건 (부품을 움직이는 동사)

ACTIONS: dict[str, str] = {
    ActionKind.CREATE_TASK: "작업 생성 (환경). 실제 처리 시간은 비공개",
    ActionKind.START_TASK: "작업 시작 = 자원 예약 + RUNNING (배정 주체)",
    ActionKind.COMPLETE_TASK: "작업 완료 = 자원 해제 + 후속 작업 READY (환경)",
    ActionKind.BEGIN_OUTAGE: "고장 시작: 자원 용량 일부 사용 불가 (환경). 원인은 비공개",
    ActionKind.END_OUTAGE: "고장 종료 (환경)",
    ActionKind.REQUEST_RECONFIGURATION: "역할 전환 요청 (구조 제어 주체)",
    ActionKind.COMPLETE_RECONFIGURATION: "역할 전환 완료 (환경)",
    ActionKind.CANCEL_TASKS: "아직 시작하지 않은 작업 포기 (환경, 예: 요청 시간 초과). 진행 중 작업은 끝까지",
}

EVENTS: dict[str, str] = {
    EventType.WORLD_INITIALIZED: "세계 초기화 (개체·연결·자원)",
    EventType.ACTION_PROPOSED: "행동 제안 기록",
    EventType.ACTION_REJECTED: "행동 거절과 사유 (사유는 공개되므로 숨겨진 값을 넣지 않는다)",
    EventType.TASK_CREATED: "작업 생성",
    EventType.TASK_STATE_CHANGED: "작업 상태 전이",
    EventType.RESOURCE_RESERVED: "자원 예약",
    EventType.RESOURCE_RELEASED: "자원 해제",
    EventType.RESOURCE_OUTAGE_STARTED: "고장 시작 (공개: 단위 수)",
    EventType.RESOURCE_OUTAGE_ENDED: "고장 종료",
    EventType.RECONFIGURATION_REQUESTED: "재구성 요청 (작업 비우기 시작)",
    EventType.RECONFIGURATION_STARTED: "역할 전환 시작",
    EventType.RECONFIGURATION_COMPLETED: "새 역할 적용",
    EventType.RUN_ENDED: "실행 종료",
}


def code_concepts() -> dict[str, list[str]]:
    """코어 모델에서 개념과 필드를 직접 읽는다 (문서와 비교하는 기준)."""
    out: dict[str, list[str]] = {}
    for name in ("Entity", "Resource", "Task", "Relation", "WorldState"):
        out[name] = [f.name for f in dataclasses.fields(getattr(model, name))]
    out["TaskStatus"] = [s.value for s in model.TaskStatus]
    out["EntityMode"] = [v for k, v in vars(model.EntityMode).items() if k.isupper()]
    return out


def code_actions() -> list[str]:
    return sorted(v for k, v in vars(ActionKind).items() if k.isupper())


def code_events() -> list[str]:
    return sorted(v for k, v in vars(EventType).items() if k.isupper())


def render_markdown() -> str:
    cc = code_concepts()
    lines = [
        "# 11. 공통 언어 v0 — 엔진의 개념(부품)과 관계",
        "",
        "> **생성 문서 — 직접 고치지 않는다.** `uv run python -m asel.vocabulary` 로 `src/asel/vocabulary.py` 에서 만든다.",
        "> 코드와 어긋나면 `tests/test_vocabulary.py` 가 실패한다. 상태: v0 (환경 A 물류에서 실제로 쓰는 개념만, 2026-11-11).",
        "> 범용 온톨로지는 장기 후보(R-15). 새 개념은 새 산업 환경에 **실제로 필요할 때만** 추가하고 변경 이력을 남긴다.",
        "",
        "## 개념 관계도",
        "",
        "```mermaid",
        "graph LR",
    ]
    for src, fld, dst, _ in LINKS:
        lines.append(f"  {src} -->|{fld}| {dst}")
    lines += ["```", "", "## 부품 목록", ""]
    for name, desc in CONCEPTS.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append(desc)
        lines.append("")
        lines.append("- 필드/값: " + ", ".join(f"`{f}`" for f in cc[name]))
        lines.append("")
    for name, desc in VALUE_CONCEPTS.items():
        lines += [f"### {name} (값)", "", desc, ""]
    lines += ["## 관계", "", "| 출발 | 필드 | 도착 | 의미 |", "|---|---|---|---|"]
    lines += [f"| {s} | `{f}` | {d} | {m} |" for s, f, d, m in LINKS]
    lines += ["", "## 행동 (부품을 움직이는 동사)", "", "| 행동 | 의미 |", "|---|---|"]
    lines += [f"| `{k}` | {v} |" for k, v in sorted(ACTIONS.items())]
    lines += ["", "## 사건 (기록되는 사실)", "", "| 사건 | 의미 |", "|---|---|"]
    lines += [f"| `{k}` | {v} |" for k, v in sorted(EVENTS.items())]
    lines += [
        "",
        "## 산업 단어는 어디에 있나",
        "",
        "코어에는 산업 단어가 없다. `pick`, `pack`, `order` 같은 말은 시나리오 파일과 도메인 어댑터에만 있다.",
        "새 산업은 (1) 시나리오에서 개체 type·capability 라벨을 정하고 (2) 작업 흐름을 정의해서 이식한다.",
        "",
    ]
    return "\n".join(lines)


DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "11-COMMON-LANGUAGE.md"


def main() -> None:
    DOC_PATH.write_text(render_markdown(), encoding="utf-8", newline="\n")
    print(DOC_PATH)


if __name__ == "__main__":
    main()

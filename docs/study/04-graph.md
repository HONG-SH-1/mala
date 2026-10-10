# LangGraph 그래프와 상태 — state / graph / route·validate 노드

> 학습용 읽기 전용 노트 (2026-10-09 작성). 코드 수정 없음.
> 관련 노트: [`02-ollama-calls.md`](02-ollama-calls.md) · [`03-queue.md`](03-queue.md) · [`fix-later.md`](fix-later.md)
> 검증 환경: `langgraph 0.6.11` (`.venv`)

```
        ┌──────────────────────────────┐
        ▼                              │ (valid=False & error_count < max_retries)
START → route ──needs_context──> retrieve ──> answer ──> validate ──> END
          └─────simple / 청크 보유─────────────▲
```

---

## 1. `src/agents/state.py` (전체 25줄)

```python
"""LangGraph shared state — Phase 2."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    task_input: str
    route_decision: str
    intent: str
    analysis_result: str
    retrieved_chunks: list[dict]
    context_refs: list[str]
    generated_code: str
    answer: str
    valid: bool
    error_count: int
    max_retries: int
    history: Annotated[list[str], operator.add]
    last_error: str
    tool_step_count: int
    router_note: str
```

**한 줄 설명:** 그래프 전역에서 주고받는 키를 `total=False` TypedDict로 선언하고, `history`만 `operator.add` reducer를 붙여 노드마다 **누적**되게 한다.

| 그룹 | 키 | 비고 |
|---|---|---|
| 식별 | `task_id`, `task_input` | `new_task_state`에서 1회 설정 |
| 라우팅 | `route_decision`, `intent` | `route`/`hermes_route`가 기록 |
| 검색 | `retrieved_chunks`, `context_refs`, `analysis_result` | `retrieve` 또는 `plan_route`가 채움 |
| 생성 | `generated_code`, `answer` | `generated_code`는 **선언만 되고 쓰는 코드 없음** |
| 제어 | `valid`, `error_count`, `max_retries`, `last_error` | `validate` 루프의 연료 |
| 관측 | `history`(누적), `router_note`, `tool_step_count` | `history`만 reducer 보유 |

> **`history`만 누적, 나머지는 전부 덮어쓰기(LastValue)** 입니다. 그래서 재시도 라운드에서 `retrieved_chunks`는 새 값으로 교체되지만 `history`는 1·2차 기록이 함께 남습니다.
>
> 선언에 **`force_vault_rag`가 없습니다** — 이게 아래 4절의 핵심입니다.

---

## 2. `src/agents/graph.py` (전체 133줄)

```python
"""LangGraph orchestrator — Phase 2 minimal loop."""

from __future__ import annotations

import logging
from functools import partial
from typing import Literal

from langgraph.graph import END, StateGraph

from src.agents.nodes import (
    answer_inline,
    answer_via_queue,
    hermes_route_node,
    new_task_state,
    retrieve_node,
    route_node,
    validate_node,
)
from src.agents.state import AgentState
from src.broker import RedisBroker
from src.broker.task_status import TaskStatusStore
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _route_branch(state: AgentState) -> Literal["retrieve", "answer"]:
    if state.get("route_decision") == "needs_context":
        if state.get("retrieved_chunks"):
            return "answer"
        return "retrieve"
    return "answer"


def _validate_branch(state: AgentState) -> Literal["route", "__end__"]:
    if state.get("valid"):
        return "__end__"
    if state.get("error_count", 0) >= state.get("max_retries", 2):
        return "__end__"
    return "route"


def build_graph(
    settings: Settings | None = None,
    *,
    use_queue: bool = True,
):
    settings = settings or get_settings()
    store = TaskStatusStore(settings)
    broker = RedisBroker(settings)

    if use_queue:
        answer_fn = partial(
            answer_via_queue,
            settings=settings,
            broker=broker,
            store=store,
        )
    else:
        answer_fn = partial(answer_inline, settings=settings, store=store)

    graph = StateGraph(AgentState)
    if settings.use_hermes_router:
        graph.add_node(
            "route",
            partial(hermes_route_node, store=store, settings=settings),
        )
    else:
        graph.add_node("route", partial(route_node, store=store))
    graph.add_node(
        "retrieve",
        partial(retrieve_node, store=store, settings=settings),
    )
    graph.add_node("answer", answer_fn)
    graph.add_node("validate", partial(validate_node, store=store))

    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route",
        _route_branch,
        {"retrieve": "retrieve", "answer": "answer"},
    )
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "validate")
    graph.add_conditional_edges(
        "validate",
        _validate_branch,
        {"route": "route", "__end__": END},
    )

    return graph.compile()


def run_task(
    task_input: str,
    *,
    use_queue: bool = True,
    settings: Settings | None = None,
    use_hermes_router: bool | None = None,
    force_vault_rag: bool = False,
) -> AgentState:
    settings = settings or get_settings()
    if use_hermes_router is not None:
        from dataclasses import replace

        settings = replace(settings, use_hermes_router=use_hermes_router)
    store = TaskStatusStore(settings)
    initial = new_task_state(
        task_input,
        max_retries=settings.graph_max_retries,
    )
    if force_vault_rag:
        initial["force_vault_rag"] = True
    store.update(
        initial["task_id"],
        {
            "status": "started",
            "task_input": task_input[:200],
            "node": "init",
        },
    )
    app = build_graph(settings, use_queue=use_queue)
    final = app.invoke(initial)
    store.update(
        final["task_id"],
        {
            "status": "completed" if final.get("valid") else "failed",
            "node": "done",
            "answer_preview": (final.get("answer") or "")[:120],
        },
    )
    return final
```

**함수별 한 줄 설명**

| 함수 | 설명 |
|---|---|
| `_route_branch` | `needs_context`인데 청크가 아직 없으면 `retrieve`로, 이미 있거나 `simple`이면 곧바로 `answer`로 보낸다. |
| `_validate_branch` | 답이 유효하거나 재시도 한도(`max_retries`)를 다 썼으면 종료하고, 아니면 `route`로 되돌려 한 바퀴 더 돌린다. |
| `build_graph` | 설정에 따라 라우터 노드(키워드 vs Hermes)와 answer 노드(큐 vs 인라인)를 골라 `partial()`로 의존성을 주입한 뒤 4노드 그래프를 컴파일한다. |
| `run_task` | 초기 상태를 만들고 `task_status`에 시작/종료를 기록하며 그래프를 1회 `invoke`하는 외부 진입점. |

읽을 때 눈여겨볼 지점:

- **의존성 주입이 `partial()`로 통일** — 노드 함수는 `store`/`broker`/`settings`를 인자로만 받아 테스트에서 가짜 store를 끼우기 쉽다 (`tests/test_graph_route.py`의 `_NoOpStore`).
- **라우터 선택은 컴파일 시점에 고정** (`:64-70`) — 런타임 전환은 불가하고, `run_task`가 `dataclasses.replace`로 `Settings`를 바꿔 다시 빌드한다 (`:104-107`).
- **`_route_branch`의 "청크 보유 시 answer"** 분기 (`:30-32`)가 Hermes 경로의 중복 검색을 막는다 — `plan_route`가 이미 검색을 끝냈기 때문.
- **재시도해도 `task_id`가 그대로** (`:109-111`에서 1회 발급) → [`03-queue.md`](03-queue.md) 5절의 늦은 결과 채택 문제로 연결.

---

## 3. `src/agents/nodes.py` — `new_task_state` · `route_node` · `validate_node`

### 3-1. `new_task_state` (`:282-297`)

```python
def new_task_state(
    task_input: str,
    *,
    task_id: str | None = None,
    max_retries: int = 2,
) -> dict:
    tid = task_id or f"TASK-{uuid.uuid4().hex[:8]}"
    return {
        "task_id": tid,
        "task_input": task_input,
        "error_count": 0,
        "tool_step_count": 0,
        "max_retries": max_retries,
        "valid": False,
        "history": [],
    }
```

**한 줄 설명:** `TASK-` + UUID 앞 8자로 작업 ID를 발급하고 카운터·플래그를 0/False로 초기화한 초기 상태 딕셔너리를 만든다.

### 3-2. `route_node` (`:74-111`)

```python
def route_node(state: dict, *, store: TaskStatusStore) -> dict:
    if state.get("force_vault_rag"):
        route_decision = "needs_context"
        intent = Intent.ANALYZE.value
        _status(
            state,
            store,
            "route",
            {"route_decision": route_decision, "intent": intent, "mode": "study"},
        )
        return {
            "route_decision": route_decision,
            "intent": intent,
            "history": ["route:needs_context:study"],
        }

    text = state["task_input"].lower()
    if any(k in text for k in _RETRIEVAL_KEYWORDS):
        route_decision = "needs_context"
        intent = Intent.ANALYZE.value
    elif "code" in text or "코드" in text or "```" in state["task_input"]:
        route_decision = "simple"
        intent = Intent.CODE.value
    else:
        route_decision = "simple"
        intent = Intent.ANALYZE.value

    _status(
        state,
        store,
        "route",
        {"route_decision": route_decision, "intent": intent},
    )
    return {
        "route_decision": route_decision,
        "intent": intent,
        "history": [f"route:{route_decision}"],
    }
```

**한 줄 설명:** `force_vault_rag`가 켜져 있으면 무조건 RAG 경로로 보내고, 그렇지 않으면 질문 텍스트의 키워드만 보고 `needs_context`/`simple`과 `intent`를 정하는 LLM 없는 규칙 기반 라우터.

| 조건 | 결과 |
|---|---|
| `force_vault_rag` truthy (`:75`) | `needs_context` + `analyze` + `history=["route:needs_context:study"]` |
| `_RETRIEVAL_KEYWORDS` 포함 (`:91`) — 옵시디언·노트·rag·검색·wiki·`[[`·vault | `needs_context` + `analyze` |
| `code` / `코드` / 코드펜스 포함 (`:94`) | `simple` + `code` |
| 그 외 (`:98`) | `simple` + `analyze` |

> `text = state["task_input"].lower()`로 소문자화하지만 한글 키워드는 영향이 없고, 코드펜스 체크만 원문(`state["task_input"]`)을 본다.

### 3-3. `validate_node` (`:258-279`)

```python
def validate_node(state: dict, *, store: TaskStatusStore) -> dict:
    answer = (state.get("answer") or "").strip()
    min_len = 8
    valid = len(answer) >= min_len and not answer.lower().startswith("error")
    error_count = state.get("error_count", 0)
    if not valid:
        error_count += 1

    _status(
        state,
        store,
        "validate",
        {"valid": str(valid), "answer_len": len(answer)},
    )
    out: dict = {
        "valid": valid,
        "error_count": error_count,
        "history": [f"validate:{'ok' if valid else 'fail'}"],
    }
    if not valid:
        out["last_error"] = state.get("last_error") or "validation_failed"
    return out
```

**한 줄 설명:** 답변이 8자 이상이고 `"error"`로 시작하지 않는지만 보는 길이 기반 검증기로, 실패 시 `error_count`를 1 올려 `_validate_branch`의 재시도 루프에 연료를 공급한다.

> 품질 검증이 아니라 **빈 답 / 명백한 에러 문자열 탐지** 수준입니다. 환각이나 출처 불일치는 잡지 못합니다.
> `min_len = 8`은 지역 변수로 하드코딩돼 있어 `.env`로 조절할 수 없습니다.

---

## 4. `force_vault_rag`는 다음 노드까지 전달되는가? → **아니오, 조용히 버려집니다**

### 결론

`run_task(force_vault_rag=True)`로 넣은 값은 **START 노드에서 폐기되어 `route_node`에 도달하지 않습니다.** `AgentState`에 선언되지 않은 키이기 때문입니다. 경고 로그조차 남지 않습니다.

### 코드 경로 — 값이 어디서 사라지는가

**① 값을 넣는 쪽** — `src/agents/graph.py:113-114`

```python
    if force_vault_rag:
        initial["force_vault_rag"] = True
```

`src/scripts/study_once.py:84-90`이 `force_vault_rag=True`로 호출합니다.

**② 채널 생성** — `langgraph/graph/state.py:1318-1328` `_get_channels()`

```python
    type_hints = get_type_hints(schema, include_extras=True)
    all_keys = {
        name: _get_channel(name, typ)
        for name, typ in type_hints.items()
        if name != "__slots__"
```

채널은 **TypedDict의 `__annotations__`에서만** 만들어집니다. `force_vault_rag`는 `state.py`에 없으므로 채널 자체가 존재하지 않습니다.

**③ START 노드의 출력 키 화이트리스트** — `langgraph/graph/state.py:944-950`

```python
    def attach_node(self, key: str, node: StateNodeSpec[Any, ContextT] | None) -> None:
        if key == START:
            output_keys = [
                k
                for k, v in self.builder.schemas[self.builder.input_schema].items()
                if not is_managed_value(v)
            ]
```

**④ 실제로 걸러내는 한 줄** — `langgraph/graph/state.py:956-962` `_get_updates()`

```python
        def _get_updates(
            input: None | dict | Any,
        ) -> Sequence[tuple[str, Any]] | None:
            if input is None:
                return None
            elif isinstance(input, dict):
                return [(k, v) for k, v in input.items() if k in output_keys]
```

`invoke`에 넘긴 딕셔너리는 START 채널(`EphemeralValue`)에 통째로 들어가지만, START 노드가 상태 채널로 **기록**할 때 이 리스트 컴프리헨션이 선언되지 않은 키를 떨어뜨립니다. `_get_updates`에는 로깅이 없어 **경고 없이 사라집니다**.

> 참고: `langgraph/pregel/_io.py:93-97`의 `map_input`에는 선언 안 된 입력 키에 대한 `logger.warning`이 있지만, `StateGraph.compile()`은 `input_channels=START`(단일 문자열, `state.py:875`)로 설정하므로 `_io.py:88-89`의 문자열 분기를 타고 그 경고에 도달하지 않습니다. 그래서 디버깅 단서가 전혀 남지 않습니다.

### 실측 검증 (langgraph 0.6.11 · 레포 코드 수정 없음)

프로젝트의 실제 `AgentState`를 import해 1노드 그래프로 확인:

```
langgraph: 0.6.11
declared in AgentState: False
node saw force_vault_rag = None
node saw keys = ['history', 'task_id', 'task_input']
final has force_vault_rag = False
```

같은 코드에서 `force_vault_rag: bool` **한 줄만 추가한** TypedDict로 바꾸면:

```
node saw force_vault_rag = True
final has force_vault_rag = True
```

→ 원인이 LangGraph 버전이나 호출 방식이 아니라 **스키마 미선언 단 하나**임이 확정됩니다.

### 실제 영향 — study 모드가 조용히 반쪽만 동작

`route_node:75`의 `if state.get("force_vault_rag"):`는 항상 `None`을 받아 **키워드 분기로 흘러내립니다.** 따라서 study 모드의 동작이 질문 문장에 좌우됩니다.

| study 모드 질문 | `force_vault_rag` | 키워드 매칭 | 실제 경로 |
|---|---|---|---|
| `"이 노트에서 핵심 개념을 요약해줘"` (study_once 기본값) | 무시됨 | `"노트"` 적중 | ✅ `needs_context` — **우연히** 동작 |
| `"이 폴더 노트에서 MALA 아키텍처 요약해줘"` (README 예시) | 무시됨 | `"노트"` 적중 | ✅ `needs_context` — 우연히 동작 |
| `"인증 흐름이 뭐야?"` | 무시됨 | 없음 | ❌ `simple` — **RAG 없이 모델 지식으로 답** |

즉 *"키워드 없이 항상 vault RAG"* 라는 study 모드의 존재 이유가 **키워드 없는 질문에서 정확히 깨집니다.** 에러가 아니라 "노트에 있는 내용을 모른다고 답함" 또는 환각으로만 드러나고, `history`에 `route:needs_context:study`가 아니라 `route:simple`이 찍히는 것으로 구분할 수 있습니다.

### 유닛 테스트가 못 잡는 이유

`tests/test_study_route.py`는 `route_node`를 **직접** 호출합니다.

```python
    state = {
        "task_id": "T-study",
        "task_input": "인증 흐름이 뭐야?",
        "error_count": 0,
        "force_vault_rag": True,
    }
    out = route_node(state, store=_NoOpStore())
    assert out["route_decision"] == "needs_context"
    assert "study" in out["history"][0]
```

평범한 딕셔너리를 넘기므로 LangGraph의 채널 필터를 **우회**합니다. 노드 로직 자체는 올바르기 때문에 테스트는 통과하고, 그래프를 통과시켰을 때만 깨집니다 — 녹색 테스트가 오히려 잘못된 확신을 줍니다.

### 같은 뿌리의 두 번째 지점

`hermes_route_node`(`nodes.py:58`)도 `bool(state.get("force_vault_rag"))`를 `plan_route`에 넘기므로 동일하게 항상 `False`가 됩니다. `plan_route:106-117`의 `force_vault_rag` 분기(LLM 라우팅을 건너뛰고 즉시 검색)는 **그래프를 통해서는 도달 불가능한 코드**입니다. 단 `study_once.py`는 `use_hermes_router=False`로 호출하므로 현재 실행 경로에서 두 문제가 겹치지는 않습니다.

### 고칠 방향

`src/agents/state.py`의 `AgentState`에 `force_vault_rag: bool` 한 줄 추가로 끝납니다(위 실측 2번으로 확인). 재발 방지로는 `route_node` 단위 테스트가 아니라 **컴파일된 그래프에 `invoke`해서** `history[0]`에 `study`가 들어오는지 확인하는 테스트가 필요합니다.

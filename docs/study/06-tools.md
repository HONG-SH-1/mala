# Hermes 라우터와 툴 호출 — 코드 전문 · ADR-003 요약 · 모델 선택 근거 추적

> 학습용 읽기 전용 노트 (2026-10-09 작성). 코드 수정 없음.
> 관련 노트: [`04-graph.md`](04-graph.md) · [`05-rag.md`](05-rag.md) · [`fix-later.md`](fix-later.md)
> 검증 환경: Ollama **0.35.1** (ADR 작성 당시는 0.24)

---

## 1. `src/agents/hermes_router.py` (전체 198줄)

```python
"""Hermes-style router via Ollama /api/chat tools (Phase 4)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from src.config import Settings
from src.retrieval.pipeline import VaultRetriever
from src.schemas.tools import SearchVaultArgs, search_vault_tool_spec

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are MALA's routing agent. You MUST use tools correctly.

Rules:
- MUST call search_vault when the user asks about Obsidian notes, vault text, welcome message in notes, or MALA project docs.
- MUST NOT call search_vault for general knowledge: sports, FIFA/World Cup, news, math trivia.
- When calling search_vault, pass a short focused query (Korean or English).

Examples — call search_vault:
- "옵시디언 노트에서 환영 메시지가 뭐라고 적혀 있어?" → query: "환영 메시지"

Examples — no tool:
- "2026년 FIFA 월드컵 우승팀은 어느 나라야?"
"""

# Hermes on Ollama often skips tool_calls; keyword fallback for vault-shaped questions.
_OOD_MARKERS = (
    "월드컵",
    "fifa",
    "우승팀",
    "스포츠",
    "축구",
    "world cup",
)
_VAULT_MARKERS = (
    "옵시디언",
    "obsidian",
    "vault",
    "볼트",
    "노트",
    "환영",
    "mala",
    "마라",
    "프로젝트 문서",
    "내 문서",
)


def fallback_vault_query(task_input: str) -> str | None:
    """Return a search query when the task clearly needs the vault (not OOD)."""
    text = task_input.strip()
    if not text:
        return None
    lower = text.lower()
    if any(m in text or m in lower for m in _OOD_MARKERS):
        return None
    if any(m in text or m in lower for m in _VAULT_MARKERS):
        return text[:200]
    return None


def _chat(
    messages: list[dict],
    settings: Settings,
) -> dict:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": settings.ollama_router_model,
        "messages": messages,
        "tools": [search_vault_tool_spec()],
        "stream": False,
        "options": {"temperature": 0},
    }
    with httpx.Client(timeout=settings.ollama_timeout_sec) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def _execute_search(query: str, settings: Settings) -> tuple[str, list[dict], list[str]]:
    retriever = VaultRetriever(settings)
    hits = retriever.search(query)
    return (
        retriever.format_context(hits),
        retriever.hits_to_chunks(hits),
        [c["id"] for c in retriever.hits_to_chunks(hits)],
    )


def plan_route(
    task_input: str,
    settings: Settings,
    *,
    tool_step_count: int = 0,
    force_vault_rag: bool = False,
) -> dict:
    """
    Returns partial state update: route_decision, optional retrieved_chunks, tool_step_count, history.
    """
    if force_vault_rag:
        query = task_input.strip()[:200] or "study"
        context, chunks, refs = _execute_search(query, settings)
        return {
            "route_decision": "needs_context",
            "intent": "analyze",
            "analysis_result": context,
            "retrieved_chunks": chunks,
            "context_refs": refs,
            "tool_step_count": tool_step_count + 1,
            "history": [f"hermes:study_force:{len(chunks)}_hits"],
        }

    if tool_step_count >= settings.max_tool_steps:
        return {
            "route_decision": "simple",
            "history": [f"hermes:circuit_breaker:{tool_step_count}"],
            "last_error": "tool_step_limit",
        }

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_input},
    ]
    try:
        data = _chat(messages, settings)
    except httpx.HTTPError as exc:
        logger.warning("Hermes router HTTP error: %s", exc)
        return {
            "route_decision": "simple",
            "history": ["hermes:http_fail"],
            "last_error": str(exc),
        }

    msg = data.get("message") or {}
    tool_calls = msg.get("tool_calls") or []

    if not tool_calls:
        fallback_q = fallback_vault_query(task_input)
        if fallback_q:
            context, chunks, refs = _execute_search(fallback_q, settings)
            return {
                "route_decision": "needs_context",
                "intent": "analyze",
                "analysis_result": context,
                "retrieved_chunks": chunks,
                "context_refs": refs,
                "tool_step_count": tool_step_count + 1,
                "history": [
                    "hermes:no_tool",
                    f"hermes:fallback_search:{len(chunks)}_hits",
                ],
            }
        content = (msg.get("content") or "").strip()
        return {
            "route_decision": "simple",
            "history": ["hermes:no_tool"],
            "router_note": content[:200],
        }

    for call in tool_calls[:1]:
        fn = call.get("function") or {}
        name = fn.get("name")
        if name != "search_vault":
            continue
        raw_args = fn.get("arguments") or "{}"
        if isinstance(raw_args, dict):
            args_dict = raw_args
        else:
            args_dict = json.loads(raw_args)
        try:
            args = SearchVaultArgs.model_validate(args_dict)
        except (ValidationError, json.JSONDecodeError) as exc:
            return {
                "route_decision": "simple",
                "history": ["hermes:bad_tool_args"],
                "last_error": str(exc),
            }
        context, chunks, refs = _execute_search(args.query, settings)
        return {
            "route_decision": "needs_context",
            "intent": "analyze",
            "analysis_result": context,
            "retrieved_chunks": chunks,
            "context_refs": refs,
            "tool_step_count": tool_step_count + 1,
            "history": [f"hermes:search_vault:{len(chunks)}_hits"],
        }

    return {
        "route_decision": "simple",
        "history": ["hermes:unknown_tool"],
    }
```

**함수별 한 줄 설명**

| 함수 | 설명 |
|---|---|
| `fallback_vault_query` | Hermes가 툴을 안 불렀을 때, 질문이 vault 관련 단어를 담고 있고 OOD(스포츠·월드컵)가 아니면 검색어로 쓸 문자열을 돌려준다. |
| `_chat` | 라우터 모델에 `search_vault` 툴 스펙을 붙여 Ollama `/api/chat`을 temperature 0으로 1회 호출한다. |
| `_execute_search` | `VaultRetriever`로 실제 Chroma 검색을 수행해 컨텍스트 문자열·청크 리스트·청크 ID 리스트를 돌려준다. |
| `plan_route` | 라우팅 전체를 담당 — study 강제·서킷 브레이커·HTTP 실패·툴 미호출·인자 오류를 모두 처리해 LangGraph 부분 상태를 반환한다. |

### `plan_route`의 6갈래

| # | 조건 | 코드 | 결과 | `history` |
|---|---|---|---|---|
| 1 | `force_vault_rag` | `:106-117` | LLM 생략, 즉시 검색 | `hermes:study_force:N_hits` |
| 2 | 툴 스텝 ≥ `MAX_TOOL_STEPS` | `:119-124` | 서킷 브레이커 → `simple` | `hermes:circuit_breaker:N` |
| 3 | HTTP 실패 | `:132-138` | `simple` (검색 없음) | `hermes:http_fail` |
| 4 | `tool_calls` 없음 + vault 키워드 | `:143-158` | **폴백 검색** | `hermes:no_tool`, `hermes:fallback_search:N_hits` |
| 5 | `tool_calls` 없음 + 키워드 없음 | `:159-164` | `simple` + `router_note` | `hermes:no_tool` |
| 6 | `search_vault` 호출됨 | `:166-193` | 인자 검증 후 검색 | `hermes:search_vault:N_hits` |

인자 검증 실패는 `hermes:bad_tool_args`(`:178-183`), 모르는 툴 이름은 `hermes:unknown_tool`(`:195-198`)로 빠집니다.

### 읽을 때 눈여겨볼 지점

- **OOD 차단이 먼저** — `fallback_vault_query:61-62`가 `_OOD_MARKERS`를 먼저 보고 `None`을 반환한다. 즉 월드컵·노트가 둘 다 걸린 질문은 **검색하지 않는다** (OOD 우선).
- **툴 호출은 1개만** — `for call in tool_calls[:1]`(`:166`)로 첫 호출만 처리한다. 멀티툴·멀티스텝 루프는 없다.
- **서킷 브레이커가 실질적으로 작동하지 않는다** — `tool_step_count`는 검색을 수행할 때만 +1 되는데(`:115`, `:151`, `:191`), 그 뒤 그래프는 `retrieve`를 건너뛰고 `answer`로 가므로 한 라운드에 최대 1회만 증가한다. `MAX_TOOL_STEPS=5`에 도달하려면 재시도가 5번 필요하지만 `GRAPH_MAX_RETRIES=2`가 먼저 걸린다.
- **`_execute_search`가 `hits_to_chunks`를 두 번 호출** (`:90`과 `:92`) — 같은 순수 변환이라 버그는 아니지만 중복 작업.
- **`except httpx.HTTPError`만 잡는다** (`:132`) — `_chat` 안의 `resp.json()`에서 JSON 파싱이 실패하면 그 예외는 처리되지 않고 노드 밖으로 전파된다.

---

## 2. `src/schemas/tools.py` (전체 29줄)

```python
"""Tool schemas — Phase 4 Hermes / function calling."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchVaultArgs(BaseModel):
    query: str = Field(min_length=1, description="Semantic search query for Obsidian vault")


def search_vault_tool_spec() -> dict:
    schema = SearchVaultArgs.model_json_schema()
    props = schema.get("properties", {})
    return {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": (
                "Search the user's local Obsidian markdown vault (Chroma RAG). "
                "Use when the question needs personal notes or project docs."
            ),
            "parameters": {
                "type": "object",
                "properties": props,
                "required": ["query"],
            },
        },
    }
```

**한 줄 설명**

| 대상 | 설명 |
|---|---|
| `SearchVaultArgs` | 툴 인자를 `query: str`(1자 이상) 하나로 정의해 LLM이 보낸 JSON을 Pydantic으로 검증한다. |
| `search_vault_tool_spec` | 위 모델의 JSON 스키마를 뽑아 OpenAI 호환 function 스펙 형태로 감싼다. |

> 스키마를 손으로 쓰지 않고 **Pydantic에서 파생**시키는 구조라, 인자를 추가하면 검증과 LLM에 보내는 스펙이 자동으로 함께 갱신됩니다.
> 툴은 `search_vault` **하나뿐**이며, description에 "개인 노트·프로젝트 문서가 필요할 때 쓸 것"이라고 용도를 못 박아 OOD를 억제하려 합니다.

---

## 3. `src/agents/nodes.py:47-71` — `hermes_route_node`

```python
def hermes_route_node(
    state: dict,
    *,
    store: TaskStatusStore,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    out = plan_route(
        state["task_input"],
        settings,
        tool_step_count=state.get("tool_step_count", 0),
        force_vault_rag=bool(state.get("force_vault_rag")),
    )
    if "intent" not in out:
        out["intent"] = Intent.ANALYZE.value
    _status(
        state,
        store,
        "hermes_route",
        {
            "route_decision": out.get("route_decision", ""),
            "tool_steps": out.get("tool_step_count", 0),
        },
    )
    return out
```

**한 줄 설명:** `plan_route`에 질문·툴 스텝 수·study 플래그를 넘겨 받은 부분 상태에 `intent` 기본값(`analyze`)을 채우고, 라우팅 결과를 `task_status`에 기록한 뒤 그대로 반환하는 얇은 어댑터.

- `plan_route`의 `simple` 분기들은 `intent`를 주지 않으므로 `:60-61`에서 기본값을 보강한다
- `task_status`에 `route_decision`과 `tool_steps`를 남겨 외부에서 관측 가능하게 한다 (`:62-70`)
- **`force_vault_rag`는 항상 `False`로 전달된다** — `AgentState`에 미선언이라 LangGraph가 버리기 때문 ([`04-graph.md`](04-graph.md) 4절, [`fix-later.md`](fix-later.md) 8번). 따라서 `plan_route`의 1번 갈래는 그래프 경유로 **도달 불가**.

---

## 4. `docs/decisions/003-phase4-hermes-router.md` 요약

| 항목 | 내용 |
|---|---|
| **상태** | Accepted — PoC verified (2026-05-26) |
| **맥락** | RTX 3080 10GB에서의 LLM 툴 라우팅, Phase 3의 Chroma + Obsidian 재사용 |

**결정 4가지**

1. **답변 모델은 그대로** `qwen3:8b` (ADR-001 유지)
2. **Phase 4 라우터는** `hermes3:8b` — Ollama `/api/chat` + `search_vault` 툴 스키마
3. **VRAM 정책:** 10GB에서 Hermes와 Qwen **동시 적재 금지**. 라우터 chat → (선택) embed → 워커 generate 순서로 돌리고 **스왑 지연을 OOM보다 낫다고 수용**
4. **라우팅 폴백:** Hermes가 `tool_calls`를 안 주더라도 vault 키워드에 걸리고 OOD가 아니면 Chroma 검색 수행. **OOD는 폴백을 타면 안 됨**

**PoC 결과표**

| 검증 | 결과 |
|---|---|
| `check_paths` | OK (`USE_HERMES_ROUTER=1`) |
| `run_hermes_once --ood` | OOD OK — vault 검색 없음 (`TASK-9a2e30e5`) |
| `run_hermes_once` (vault) | SUCCESS — 볼트 환영 메시지 노트 컨텍스트로 답변 일치 (`TASK-8f744eba`) |
| Hermes 단독 VRAM | peak **7418 MiB**, `ollama ps` **5.2 GB** |
| 네이티브 `tool_calls` | **Ollama 0.24에서 자주 비어 있음** — 폴백으로 완화 |

**결과(Consequences)**

- `USE_HERMES_ROUTER=1` → `route` 자리에 `hermes_route_node`. `needs_context` + 청크 보유 시 중복 `retrieve` 생략
- `hermes_router.py`에 `MAX_TOOL_STEPS` 서킷 브레이커
- 모델은 `D:\ollama\models`에 보관 (Windows 환경변수 + `db.sqlite` — 트러블슈팅 문서 참조)

**범위 밖(PoC)**

- CrewAI, GPU 상주 2번째 LLM, 35B MoE
- **폴백 없이 신뢰할 수 있는 네이티브 툴 호출** (후속 과제로 명시)
- Web UI, GraphRAG

---

## 5. qwen3:8b도 tools를 지원하는데 왜 hermes3:8b를 따로 썼나?

### 결론: **레포 문서에 비교·선택 근거가 없습니다.**

`docs/`, `archive/`, `handoff/`(로컬 전용 문서, 비공개), `README.md` 전체에서 `hermes` · `tools` · `function calling` · `FC` 를 검색했지만, **qwen3의 툴 지원과 hermes3를 비교한 서술은 한 줄도 없습니다.** ADR-003에는 "검토한 대안(Alternatives considered)" 항목 자체가 없고, 라우터로 hermes3를 쓴다는 **결정만** 적혀 있습니다.

### 실측: 두 모델 모두 tools를 지원합니다

2026-10-09, Ollama 0.35.1 `POST /api/show`:

```
=== hermes3:8b ===
 capabilities: completion, tools
 params: 8.0B | quant: Q4_0 | context_length: 131072

=== qwen3:8b ===
 capabilities: completion, tools, thinking
 params: 8.2B | quant: Q4_K_M | context_length: 40960
```

→ `qwen3:8b`도 `tools` capability를 가지며, 오히려 `thinking`까지 추가로 지원합니다. 컨텍스트 길이는 hermes3가 131072로 더 길지만, 레포에서는 두 모델 모두 ctx 4096으로 기록·운영됩니다(`model-comparison.md`).

### 근거에 가장 가까운 텍스트 (그래도 비교는 아님)

| 위치 | 텍스트 | 성격 |
|---|---|---|
| `docs/model-comparison.md:44` | Hermes 3 8B 행 — params 칸에 **"8B FC router"**, 역할 칸에 **"Tool 라우터 (Phase 4)"** | 역할 **배정**이지 비교 근거가 아님. qwen3 행에는 툴 관련 언급이 전혀 없음 |
| `docs/decisions/003-phase4-hermes-router.md:10` | "Phase 4 router: `hermes3:8b` via Ollama `/api/chat` + `search_vault` tool schema" | 결정 서술. 왜 qwen3가 아닌지는 없음 |
| `docs/model-comparison.md:44` 비고 | "Phase 4 PoC · tool은 폴백 검색 병행" | 한계 기록 |

즉 문서에서 읽을 수 있는 것은 **"Hermes 3는 function calling 특화 모델로 알려져 있다"는 통념을 전제로 역할을 배정했다**는 정도이며, 그 전제를 측정이나 인용으로 뒷받침한 기록은 없습니다. 이 레포가 MoE 기각(ADR-001)을 VRAM **실측**으로 못 박은 것과 대비됩니다.

### 오히려 역방향 증거가 남아 있습니다

| 위치 | 기록 |
|---|---|
| `docs/decisions/003-phase4-hermes-router.md:22` | 네이티브 `tool_calls`가 "**Ollama 0.24에서 자주 비어 있음**" |
| `docs/development-log.md:147` | "막힘 1 — Hermes가 **`search_vault` tool 미호출** → Qwen만 답 → 환각" |
| `handoff/2026-05-26-to-claude.md:18` *(로컬 전용)* | "Hermes는 Ollama 0.24에서 **native `tool_calls`가 거의 안 나와** vault 질문이 처음엔 Qwen 환각" |
| `src/agents/hermes_router.py:32` (주석) | "Hermes on Ollama often skips tool_calls; keyword fallback for vault-shaped questions." |

**FC 특화 모델로 데려온 hermes3가 정작 FC에 실패해, 키워드 폴백으로 RAG를 보장하는 구조가 되었습니다.** 개발 로그의 성공 사례(`TASK-8f744eba`, `TASK-a9198b0e`)도 `hermes:fallback_search:1_hits`로 기록돼 있어 **툴 호출이 아니라 폴백 경유**임을 보여줍니다.

### 질문이 열린 채로 남아 있었다는 기록

| 위치 | 기록 |
|---|---|
| `handoff/2026-05-26-to-claude.md:111` *(로컬 전용)* | "Hermes `tool_calls`를 Ollama 0.24에서 안정화하려면 — 프롬프트만 vs route 노드에서 retrieve 기본 분기 vs **다른 8B FC 모델?**" |
| `handoff/2026-05-27-to-claude.md:26` *(로컬 전용)* | "**하지 말 것:** … Hermes tool 대개편 (시간 대비 이득 작음)" |
| `docs/development-log.md:170` | "Hermes **네이티브 tool 호출**은 PoC 이후 개선 (현재 폴백으로 RAG 보장)" |
| `docs/decisions/003-phase4-hermes-router.md:33` | 범위 밖 — "폴백 없이 신뢰할 수 있는 네이티브 툴 호출 (follow-up)" |


> `handoff/`는 **로컬 전용 문서(비공개)** 로 `.gitignore`에 등재되어 레포에 포함되지 않습니다. 위 인용은 로컬 파일 기준이라 외부에서는 확인할 수 없습니다.

→ 모델 교체 가능성은 **인식하고 있었지만 V1 마감(05-27) 시간 제약으로 보류**한 것으로 읽힙니다. 다만 **"qwen3로 라우팅을 시도해 봤다"는 기록은 어디에도 없습니다.**

### 정리

| 질문 | 답 |
|---|---|
| 문서에 qwen3 vs hermes3 툴 성능 비교가 있나? | **없음** |
| ADR-003에 대안 검토 항목이 있나? | **없음** (Decision · PoC · Consequences · Not in scope 뿐) |
| hermes3 선택의 측정 근거가 있나? | **없음** — VRAM 실측(7418 MiB)만 있고 툴 호출 성공률 비교는 없음 |
| 근거에 가장 가까운 것은? | `model-comparison.md:44`의 "8B FC router" 역할 라벨 (통념 기반 배정) |
| 현재 실제로 라우팅을 수행하는 것은? | LLM 툴 호출이 아니라 **키워드 폴백** |

**지금 재검토한다면** 비교 조건이 당시보다 좋습니다 — Ollama가 0.24 → **0.35.1**로 올라왔고 `/api/show`가 두 모델 모두 `tools`를 보고합니다. `.env`의 `OLLAMA_ROUTER_MODEL=qwen3:8b` 한 줄만 바꿔 `run_hermes_once`와 `--ood`를 돌리면 **모델 교체만으로** 비교가 됩니다. 답변 모델과 라우터가 같은 모델이 되면 ADR-003의 VRAM 스왑 정책(동시 적재 금지)도 자연히 불필요해집니다 — 스왑 자체가 사라지기 때문입니다.

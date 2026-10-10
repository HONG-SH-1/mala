# fix-later — 나중에 고칠 것 (Ollama 호출 / 타임아웃 / 설정)

> 학습 중 발견한 개선 후보 기록 (2026-10-09). **코드는 수정하지 않음.**
> 관련 노트: [`02-ollama-calls.md`](02-ollama-calls.md) · 관련 ADR: [`../decisions/003-phase4-hermes-router.md`](../decisions/003-phase4-hermes-router.md)

| # | 항목 | 위치 | 영향 |
|---|---|---|---|
| 1 | `num_ctx` 미지정 | `src/worker.py:41-45` | 품질 (조용한 실패) |
| 2 | 답변 생성 `temperature` 미지정 | `src/worker.py:41-45` | 재현성 |
| 3 | 재시도가 4xx까지 포함 | `src/worker.py:30-35` | 불필요한 지연 |
| 4 | 워커 최악 대기 > 오케스트레이터 대기 | `src/worker.py:30-35` vs `src/agents/nodes.py:172` | 정합성 (결과 혼선) |
| 5 | `keep_alive` 미지정 | 모든 Ollama 호출 | VRAM 정책이 코드로 강제되지 않음 |
| 6 | 죽은 환경 변수 2개 | `.env.example:5-6` | 혼동 유발 |
| 7 | qwen3 thinking 모드 기본 켜짐 | `src/worker.py:41-45` | 지연 · 컨텍스트 소모 |
| 8 | **[우선순위 높음]** `force_vault_rag` 미선언 | `src/agents/state.py:9-25` | **기능 무효화** (study 모드 RAG 건너뜀) |
| 9 | rerank가 키워드 점수 우선 | `src/retrieval/rerank.py:38-50` | 의미 검색 무력화 |
| 10 | 청크 상한 없음 + 임베더 2048 토큰 | `src/retrieval/chunker.py` · `nomic-embed-text` | 검색/프롬프트 비대칭 |
| 11 | `delete_source`가 모든 예외를 삼킴 | `src/retrieval/chroma_store.py:46-50` | 구·신 청크 공존 (무로그) |
| 12 | `RAG_TOP_K` 문서 5 vs 실제 3 | `.env:30` vs `.env.example:31` | 문서 불일치 |
| 13 | `validate`가 답변 내부 모순을 못 잡음 | `src/agents/nodes.py:258-279` | 오정보 통과 |
| 14 | 서킷 브레이커 사실상 무동작 | `src/agents/hermes_router.py:119-124` | 죽은 안전장치 |
| 15 | `_chat`의 JSON 파싱 실패 미처리 | `src/agents/hermes_router.py:80-83` · `:130-138` | 예외 전파 |
| 16 | 라우터 모델 선택에 측정 근거 없음 | `docs/decisions/003-phase4-hermes-router.md` | 불필요한 모델 스왑 가능성 |

---

## 1. `num_ctx` 미지정 — 프롬프트가 조용히 잘릴 수 있음

`/api/generate` 페이로드에 `options`가 아예 없어 컨텍스트 길이가 Ollama 서버 측 모델 기본값에 맡겨짐.

- `src/worker.py:41-45` — `model`, `prompt`, `stream` 3개만 전송
- `build_prompt`(`src/worker.py:51-72`)는 청크 `RAG_TOP_K=5`개 × 최대 1200자(`src/retrieval/pipeline.py:296`)를 붙임
- 기본 `num_ctx`를 넘기면 **에러 없이** 앞쪽 컨텍스트가 잘림 → "노트에 있는데 모른다고 답함" 형태로만 드러남

## 2. 답변 생성 `temperature` 미지정 — 답이 매번 달라짐

- `src/worker.py:41-45` — `options` 없음 → 모델 기본값(비결정적)
- 반면 라우터는 `src/agents/hermes_router.py:78`에서 `"options": {"temperature": 0}` 지정
- 결과적으로 **라우팅은 결정적, 최종 답변은 비결정적** → 회귀 테스트·데모 재현이 어려움

## 3. 재시도가 4xx까지 포함 — 연결 실패와 5xx만 재시도해야 함

```python
retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
```

- `src/worker.py:33`
- `httpx.HTTPStatusError`는 **4xx와 5xx를 모두** 포함 → 모델명 오타(404), 잘못된 페이로드(400) 같은 영구 실패도 3회 재시도
- 고칠 방향: `RequestError`(연결 실패) + `HTTPStatusError` 중 `response.status_code >= 500`만 재시도하도록 조건부 predicate로 분리

## 4. 워커 최악 대기(3×120초)가 오케스트레이터 대기(120초)보다 김 — 늦은 결과가 다음 작업과 충돌

| 쪽 | 설정 | 최악 소요 |
|---|---|---|
| 워커 | `stop_after_attempt(3)` × `OLLAMA_TIMEOUT_SEC=120` + 백오프 2s·4s (`src/worker.py:30-35`) | **약 366초** |
| 오케스트레이터 | `timeout_sec: float = 120` (`src/agents/nodes.py:172`) | **120초** |

진행 순서:

1. 오케스트레이터가 120초에 포기 → `last_error="result_timeout"`, `valid=False` 반환 (`src/agents/nodes.py:211-217`)
2. `validate_node` → `_validate_branch`(`src/agents/graph.py:36-41`)가 `route`로 되돌림 (`GRAPH_MAX_RETRIES=2` — 실측 **총 2회 시도**, 14번 항목 참조)
3. 같은 `task_id`로 **새 Envelope를 또 push** — `task_id`는 `new_task_state`에서 한 번만 발급되고 루프 중 바뀌지 않음 (`src/agents/nodes.py:288`)
4. 그 사이 1차 작업이 늦게 끝나 `result_queue`에 결과를 넣음 → 재시도 라운드가 **1차의 늦은 결과를 자기 답으로 받아들임** (`task_id`가 같아 `src/agents/nodes.py:201` 필터를 통과)
5. 최종적으로 워커 2개 분량의 결과 중 하나는 큐에 남아 다음 실행이 주워 감. `task_id`가 다르면 `src/agents/nodes.py:201-203`에서 **로그만 남기고 폐기**

고칠 방향: 오케스트레이터 대기 ≥ 워커 최악 소요가 되게 맞추거나(또는 반대로 워커 재시도 축소), `task_id`에 시도 회차를 붙이고, `result_queue`를 `task_id`별 키로 분리해 유실·혼선을 막기.

## 5. `keep_alive` 미지정 — ADR-003이 코드가 아니라 Ollama 자동 교체에 의존

- `keep_alive`는 `src/` 전체에서 한 번도 전송되지 않음 → Ollama 기본값(마지막 호출 후 5분 적재 유지)
- ADR-003의 "10GB에서 Hermes + Qwen 동시 적재 금지" 정책이 **코드로 강제되어 있지 않고**, 호출 순서(라우터 → 임베딩 → 워커 생성)와 Ollama의 자동 스왑에 의존
- 세 모델(`hermes3:8b`, `nomic-embed-text`, `qwen3:8b`)이 5분 창 안에서 겹쳐 호출되면 OOM 위험
- 고칠 방향: 라우터·임베딩 호출에 `keep_alive: 0`을 명시해 사용 직후 언로드

## 6. `.env`의 `MAX_MODEL_LEN`, `GPU_MEMORY_UTILIZATION`은 읽히지 않음 (vLLM 시절 잔재)

- `.env.example:5-6`에 `GPU_MEMORY_UTILIZATION=0.85`, `MAX_MODEL_LEN=4096`이 있으나 `src/config.py`의 `Settings`에 해당 필드가 **없음** → 완전히 무시됨
- 같은 파일 주석도 "Phase 1+ reference; Ollama manages VRAM"이라고 인정
- `INFERENCE_ENGINE=ollama`도 동일하게 미사용
- 위험: `MAX_MODEL_LEN=4096`을 보고 컨텍스트가 4096으로 설정됐다고 **오해**하게 됨 (실제로는 1번 항목대로 미지정)
- 고칠 방향: 삭제하거나, `Settings`에 추가해 1번의 `num_ctx`로 실제 연결

---

## 7. qwen3 thinking 모드 기본 켜짐 — 숨은 추론 토큰으로 지연·컨텍스트 증가

`src/worker.py:41-45`가 `think` 파라미터를 보내지 않으므로 `qwen3:8b`의 thinking이 **기본값으로 켜진 채** 호출됩니다. `src/` 전체에 `think` 문자열이 한 번도 없습니다.

**실측 (2026-10-09, Ollama 0.35.1)** — `worker.py`와 동일한 페이로드(`model`/`prompt`/`stream` 3개만)로 호출:

```
POST /api/generate  {"model": "qwen3:8b", "prompt": "Reply with the single word: ok", "stream": false}

thinking field present: True | chars: 568
response chars: 2 | has <think> inline: False
prompt_eval_count: 17 | eval_count: 143
total_duration_s: 35.3
```

- `/api/show`의 `capabilities: ['completion', 'tools', 'thinking']` — thinking 지원 모델이고 템플릿에 think 마커 존재
- **2글자 답("ok")을 얻는 데 생성 토큰 143개** 중 약 141개가 추론 토큰 → 사실상 전량이 숨은 비용
- 추론 텍스트는 `response`가 아니라 **별도 `thinking` 필드**로 돌아오므로 답변 본문이 오염되지는 않음
- 그런데 `worker.py:96`은 `ollama_result.get("response", "")`만 읽음 → **추론 토큰 값을 다 치르고 결과는 버림**

영향:

| 축 | 영향 |
|---|---|
| 지연 | 짧은 답에도 추론 토큰 생성 시간이 그대로 붙음 (위 실측은 모델 로드 포함 35초) |
| 컨텍스트 | 추론 토큰이 생성 중 `num_ctx`를 프롬프트·답변과 함께 나눠 씀 → **1번 항목(`num_ctx` 미지정)과 곱해져 악화** |
| 누적 | 단발성 `/api/generate`라 턴 간 누적은 없음 (멀티턴 `/api/chat`으로 바꾸면 누적 시작) |

> 같은 `/api/show` 결과에서 모델 기본 `temperature 0.6`, `top_k 20`, `top_p 0.95`도 확인됨 — **2번 항목 보강**: 답변 생성은 중립값이 아니라 0.6으로 돌고 있습니다.

고칠 방향: `src/worker.py:call_ollama`의 페이로드에 `"think": False`를 추가(답변 품질을 보고 결정). 추론을 유지할 경우 `thinking` 필드를 로그나 `task_status`에 남겨 비용을 관측 가능하게 만들기.

---

## 8. [우선순위 높음] `force_vault_rag`가 `AgentState`에 미선언 — LangGraph가 조용히 버림

`src/agents/graph.py:113-114`가 넣은 `force_vault_rag`는 `src/agents/state.py:9-25`의 `AgentState`에 **선언되어 있지 않아** START 노드에서 폐기됩니다. `route_node:75`는 항상 `None`을 받습니다.

근거·실측 전문은 [`04-graph.md`](04-graph.md) 4절. 요약:

| 단계 | 위치 | 동작 |
|---|---|---|
| 채널 생성 | `langgraph/graph/state.py:1318-1322` | 채널은 TypedDict `__annotations__`에서만 생성 → 해당 채널 없음 |
| 화이트리스트 | `langgraph/graph/state.py:945-950` | START 노드 `output_keys`를 입력 스키마 키로 한정 |
| 폐기 | `langgraph/graph/state.py:961` | `[(k, v) for k, v in input.items() if k in output_keys]` — **로깅 없이** 탈락 |

실측 (`langgraph 0.6.11`, 프로젝트 실제 `AgentState` import): `node saw force_vault_rag = None`. 같은 코드에서 `force_vault_rag: bool` 한 줄만 추가하면 `True`로 전달 → 원인이 스키마 미선언 단 하나로 확정.

**study 모드가 키워드 없는 질문에서 RAG를 건너뜁니다:**

| 질문 | 실제 경로 |
|---|---|
| `"이 노트에서 핵심 개념을 요약해줘"` (기본값) | ✅ `"노트"` 키워드 적중 — **우연히** 동작 |
| `"인증 흐름이 뭐야?"` | ❌ `simple` — RAG 없이 모델 지식으로 답 |

즉 *"키워드 없이 항상 vault RAG"* 라는 기능의 존재 이유가 정확히 그 지점에서 깨지고, 에러 대신 환각 또는 "모른다"로만 드러납니다. 구분 단서는 `history`에 `route:needs_context:study`가 아니라 `route:simple`이 찍히는 것.

**실행 증거 — `TASK-42f5e6b6`** (study_once, 2026-10-09T04:18:45Z)

표준출력의 `history`가 `route:needs_context:study`가 아니라 **`route:needs_context`** 로 찍혔습니다. 즉 study 분기가 아니라 `"노트"` 키워드 분기를 탄 것입니다.

Redis `task_status:TASK-42f5e6b6`에 남은 기록이 이를 독립적으로 뒷받침합니다:

```
task_input: 이 노트에서 핵심 개념을 요약해줘
route_decision: needs_context
mode field present: False        <-- 결정적
hits: 3
intent: analyze
via: inline
valid: True
status: completed
```

`route_node`의 study 분기는 `task_status`에 **`mode: "study"` 를 함께 기록합니다**(`src/agents/nodes.py:82`). 그 필드가 아예 없다는 것은 `:75`의 `if state.get("force_vault_rag"):`가 거짓이었고 `:91`의 키워드 분기로 내려갔다는 직접 증거입니다. 질문에 `"노트"`가 들어 있어 **결과적으로는 RAG를 탔지만, 그건 study 플래그 때문이 아닙니다.**


**단위 테스트는 못 잡습니다.** `tests/test_study_route.py`는 `route_node`를 평범한 딕셔너리로 직접 호출해 LangGraph 채널 필터를 우회합니다. 노드 로직 자체는 올바르므로 테스트는 통과하고, 녹색 결과가 잘못된 확신을 줍니다.

**수정 순서:**

1. 컴파일된 그래프를 `invoke`하는 통합 테스트를 먼저 작성해 **실패를 확인** (키워드 없는 질문 → `history[0]`에 `study` 기대)
2. `src/agents/state.py`의 `AgentState`에 `force_vault_rag: bool` 한 줄 추가
3. 같은 테스트로 **통과 확인**

**함께 따라오는 것:** `hermes_route_node`(`src/agents/nodes.py:58`)도 `bool(state.get("force_vault_rag"))`를 넘기므로 항상 `False`가 되고, `plan_route:106-117`의 `force_vault_rag` 분기는 그래프 경유로 **도달 불가능**합니다. 2단계 수정으로 이 경로도 함께 살아나므로, 통합 테스트는 `USE_HERMES_ROUTER=1` 케이스도 같이 덮는 편이 좋습니다.

---

## 9. rerank가 키워드 점수 우선, 벡터 거리는 동점일 때만 — 의미 검색을 키워드가 덮어씀

`src/retrieval/rerank.py:38-50`의 점수 함수가 `(kw, -dist)` 튜플을 반환하고 `sorted(..., reverse=True)`로 정렬됩니다. 튜플 비교는 **앞 원소가 먼저**이므로 키워드 점수가 1차 기준, 벡터 거리는 **동점일 때만** 쓰이는 2차 기준입니다.

| 가중치 | 값 |
|---|---|
| 토큰이 헤딩에 포함 | +3 |
| 토큰이 본문·파일명에 포함 | +1 |
| `phase N` 파일명 일치 | +8 |
| 벡터 거리 | 동점 시에만 |

결과: 의미적으로 가장 가까운 청크라도 키워드 하나 덜 겹치면 **키워드가 겹치는 먼 청크에 밀립니다.** +8 보너스는 `vault_sample/Phase-2-Agent.md` 같은 데모 파일명을 겨냥한 하드코딩이라, 실제 vault(`<VAULT_PATH>`)에서는 쓰이지 않으면서 코드만 남아 있습니다. 주석도 "Phase 3 demo quality"로 한계를 밝혀 둔 상태(`:1`).

고칠 방향: 두 점수를 정규화해 가중 합(예: `w1*norm(kw) + w2*(1-dist)`)으로 바꾸거나, 임베딩 기반 크로스 인코더 재정렬로 교체. 최소한 `phase` 하드코딩은 제거.

---

## 10. 청크 크기 상한 없음 + 임베더 컨텍스트 2048 — 임베딩은 잘리고 프롬프트에는 전문이 들어감

- `chunk_markdown`(`src/retrieval/chunker.py:26-76`)은 헤딩 경계로만 자르고 **길이 상한이 없음** → 긴 섹션 하나가 그대로 한 청크
- `nomic-embed-text`의 컨텍스트는 **2048 토큰** (`/api/show`의 `nomic-bert.context_length`, 2026-10-09 실측)
- 2048 토큰을 넘는 청크는 **초과분이 임베딩에 반영되지 않음** — 에러 없이 검색 품질로만 드러남
- 그런데 `hits_to_chunks`(`src/retrieval/pipeline.py:300-310`)는 **원문 전체**를 담고, `build_prompt`(`src/worker.py:62-66`)가 `chunk["text"]`를 그대로 넣음

→ **"검색에는 안 쓰인 텍스트가 프롬프트에는 들어가는" 비대칭.** 벡터로는 찾을 수 없는 내용이 일단 검색되고 나면 답변 근거로는 쓰이는 상태입니다.

참고로 `format_context`는 1200자로 자르지만(`pipeline.py:296`), 청크가 있을 때 `build_prompt`의 `elif ctx.get("analysis")` 분기(`src/worker.py:67`)가 실행되지 않아 **그 절단은 프롬프트에 영향이 없습니다.**

고칠 방향: 청크 분할에 토큰 기준 상한(+ 오버랩)을 두고, 임베딩 대상과 프롬프트 삽입 대상을 동일한 텍스트로 통일.

---

## 11. `delete_source`가 모든 예외를 삼킴 — 삭제 실패 시 옛 청크와 새 청크가 공존, 로그 없음

```python
    def delete_source(self, source: str) -> None:
        try:
            self._collection.delete(where={"source": source})
        except Exception:
            pass
```

`src/retrieval/chroma_store.py:46-50`. `except Exception: pass`라 **어떤 실패도 호출자에게 전달되지 않고 로그도 남지 않습니다.**

`_index_one_file`(`src/retrieval/pipeline.py:189-199`)의 순서가 `delete_source` → 재청킹 → `upsert_chunks`인데, 삭제가 조용히 실패하면:

1. 낡은 청크가 컬렉션에 남음
2. 호출자는 성공으로 간주해 새 청크를 upsert
3. `chunk_id`가 `파일::슬러그::순번`이라 **헤딩명이 바뀐 청크는 새 ID를 받음** → 옛 ID 청크가 지워지지 않고 그대로 생존
4. 매니페스트에는 성공으로 기록되어 다음 실행에서 재시도도 안 됨

→ 삭제된 헤딩·수정 전 내용이 계속 검색되어 **답변 근거로 인용**될 수 있습니다. `index_vault`의 `files_failed` 통계에도 집계되지 않습니다.

고칠 방향: 최소한 `logger.warning`을 남기고, 실패를 `IndexStats.files_failed`에 반영하거나 `append_index_failure`로 DLQ에 적기. `except Exception`을 Chroma가 실제로 던지는 예외 타입으로 좁히기.

---

## 12. `.env`의 `RAG_TOP_K=3` vs 기본값·`.env.example`의 5 — 문서와 실제 동작 불일치

| 출처 | 값 |
|---|---|
| `src/config.py:68` 기본값 | 5 |
| `.env.example:31` | 5 |
| README Phase 3 설명 | 5개 기준으로 서술 |
| **`.env:30` (실제 실행)** | **3** |

실측 확인: `TASK-42f5e6b6`의 `task_status`에 `hits: 3`, `refs` 3건 (8번 항목의 실행 증거 참조).

`VaultRetriever.search`의 후보 pool도 따라 달라집니다 — `pool = min(max(k*4, k), 20)`이므로 `k=3`이면 12, `k=5`면 20. 즉 **후보 폭까지 절반 가까이 줄어든 상태**로 돌고 있습니다. 현재 컬렉션 청크가 30개이므로 후보 12개 = 전체의 40%.

고칠 방향: 의도한 값을 하나로 정하고 `.env`·`.env.example`·README를 일치시키기. 3이 의도라면 `.env.example`과 README를, 5가 의도라면 `.env`를 고치기.

---

## 13. `validate`가 답변 내부 모순을 못 잡음

`validate_node`(`src/agents/nodes.py:258-279`)의 판정은 **두 가지뿐**입니다.

```python
valid = len(answer) >= min_len and not answer.lower().startswith("error")
```

길이 8자 이상 + `"error"`로 시작하지 않음. 내용 검증은 전혀 없습니다.

**실제 사례 — `TASK-42f5e6b6`**: 같은 답변 안에서 **하나의 합격 기준을 본문 서술과 표에서 서로 다른 수치로 두 번 적었는데도**(본문 쪽이 오류) `valid: True`로 통과했습니다.

```
answer_len: 811
valid: True
status: completed
```

검색 자체는 정상 동작했습니다(청크 3개가 모두 의도한 노트에서 나옴 — 8번 항목 `refs` 참조). **생성 단계에서 같은 답변 내부의 수치 정합성이 깨진** 사례입니다. 질문에 쓰인 노트는 개인 학습 자료라 원문·수치를 인용하지 않습니다.

못 잡는 것들:

| 유형 | 현재 탐지 |
|---|---|
| 빈 답변 | ✅ (8자 규칙) |
| `"error..."`로 시작하는 문자열 | ✅ |
| 답변 내부 숫자·기준 모순 | ❌ |
| 검색 청크에 없는 내용(환각) | ❌ |
| 인용 출처와 본문 불일치 | ❌ |

`min_len = 8`이 지역 변수 하드코딩이라 조정도 안 됩니다(`:260`).

고칠 방향: `retrieved_chunks`와 답변을 대조하는 검증 노드를 추가(근거 문장이 청크에 존재하는지 확인), 또는 숫자·기준이 걸린 질문에 한해 2차 LLM 검증(self-consistency) 추가. 최소한 `min_len`을 `Settings`로 올리기.

---

## 14. 서킷 브레이커 사실상 무동작 — `MAX_TOOL_STEPS=5`에 도달 불가

`plan_route`(`src/agents/hermes_router.py:119-124`)의 서킷 브레이커는 `tool_step_count >= settings.max_tool_steps`에서 발동합니다. 그런데 `tool_step_count`는 **검색을 실제로 수행할 때만 +1** 되고(`:115`, `:151`, `:191`), 검색 후 그래프는 `_route_branch`의 "청크 보유 시 answer" 분기(`src/agents/graph.py:30-32`)로 `retrieve`를 건너뛰어 곧바로 `answer`로 갑니다. 즉 **한 라운드에 최대 1 증가**합니다.

라운드를 더 돌리는 유일한 경로는 `validate` 실패 재시도인데, 그 횟수가 `GRAPH_MAX_RETRIES`로 묶여 있습니다.

**실측 (langgraph 0.6.11, 실제 `validate_node` + `_validate_branch` 사용, 답변을 항상 빈 문자열로 강제):**

```
GRAPH_MAX_RETRIES (.env): 2 | MAX_TOOL_STEPS: 5
visits: {'route': 2, 'answer': 2, 'validate': 2}
final error_count: 2 | tool_step_count: 2
```

→ `route` 방문은 **2회**가 상한입니다. `error_count`가 0→1(통과)→2(`2 >= 2` 종료)로 오르므로 `max_retries=2`는 "초기 1회 + 재시도 2회 = 3회"가 아니라 **총 2회 시도**입니다.

| 값 | 상한 |
|---|---|
| `route` 방문 | 2 |
| `tool_step_count` 최대 도달값 | **2** |
| `MAX_TOOL_STEPS` 설정값 | 5 |

→ 설정값 5는 상한 2로는 **영원히 도달할 수 없습니다.** `.env`에서 `MAX_TOOL_STEPS`를 조절해도 동작이 바뀌지 않고, ADR-003이 Consequences에 명시한 안전장치가 실질적으로 비활성 상태입니다.

> `MAX_TOOL_STEPS`는 본래 **에이전트가 툴을 연쇄 호출하는 루프**(tool → 관찰 → tool → …)를 끊기 위한 장치입니다. 현재 구조는 `tool_calls[:1]`로 첫 호출만 쓰고 그래프도 한 번만 검색하므로, 끊어야 할 루프 자체가 없습니다.

고칠 방향: 멀티스텝 툴 루프를 실제로 구현할 때 함께 살리거나, 지금은 작동하지 않는다는 주석을 달아 두기. 아울러 `GRAPH_MAX_RETRIES`의 의미를 "총 시도 횟수"로 맞추려면 `_validate_branch`의 비교를 `>` 로 바꾸거나 이름을 `GRAPH_MAX_ATTEMPTS`로 정정.

---

## 15. `_chat`의 JSON 파싱 실패 미처리 — `httpx.HTTPError`만 잡음

`_chat`(`src/agents/hermes_router.py:80-83`)은 응답을 `resp.json()`으로 역직렬화합니다.

```python
with httpx.Client(timeout=settings.ollama_timeout_sec) as client:
    resp = client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()
```

호출부(`:130-138`)는 `except httpx.HTTPError`만 받습니다.

```python
try:
    data = _chat(messages, settings)
except httpx.HTTPError as exc:
    logger.warning("Hermes router HTTP error: %s", exc)
    return {"route_decision": "simple", ...}
```

`resp.json()`이 던지는 `json.JSONDecodeError`(및 httpx의 `ResponseNotRead` 류)는 **`httpx.HTTPError`의 하위 타입이 아니므로** 이 `except`를 통과해 `hermes_route_node` → LangGraph 바깥으로 전파됩니다. 그래프가 `simple`로 우아하게 폴백하지 못하고 **작업 전체가 예외로 죽습니다.**

발생 조건: Ollama가 200과 함께 비정상 본문(빈 응답, 프록시 HTML 오류 페이지, 스트리밍 조각)을 돌려주는 경우. 다른 경로들과 비교하면 일관성도 깨져 있습니다.

| 위치 | JSON 파싱 실패 처리 |
|---|---|
| `_chat` (`:83`) | ❌ 미처리 |
| 툴 인자 파싱 (`:175-183`) | ✅ `except (ValidationError, json.JSONDecodeError)` |
| 워커 Envelope 파싱 (`src/worker.py:82`) | ✅ `except (json.JSONDecodeError, ValueError)` |

고칠 방향: `:132`의 `except`를 `except (httpx.HTTPError, json.JSONDecodeError, ValueError)`로 넓히거나, `_chat` 안에서 파싱까지 감싸 실패 시 빈 딕셔너리를 반환하기.

---

## 16. 라우터 모델 선택에 측정 근거 없음

ADR-003(`docs/decisions/003-phase4-hermes-router.md`)에는 **"검토한 대안(Alternatives considered)" 항목이 없습니다.** 구성은 Decision · PoC results · Consequences · Not in scope 뿐이며, `hermes3:8b`를 라우터로 쓴다는 결정만 있고 **왜 `qwen3:8b`가 아닌지는 어디에도 없습니다.**

`docs/`, `archive/`, `handoff/`(로컬 전용 문서, 비공개), `README.md` 전체 검색 결과 qwen3의 툴 지원과 hermes3를 비교한 서술은 한 줄도 없습니다. 근거에 가장 가까운 텍스트는 `docs/model-comparison.md:44`의 **"8B FC router" / "Tool 라우터 (Phase 4)"** 라벨 하나로, 측정이 아니라 통념 기반 **역할 배정**입니다.

**실측 (2026-10-09, Ollama 0.35.1 `POST /api/show`):**

```
hermes3:8b  capabilities: completion, tools         | 8.0B Q4_0    | ctx 131072
qwen3:8b    capabilities: completion, tools, thinking | 8.2B Q4_K_M | ctx  40960
```

→ **`qwen3:8b`도 `tools`를 지원합니다.**

역방향 증거는 오히려 레포에 남아 있습니다 — hermes3는 정작 `tool_calls`를 거의 반환하지 않았습니다.

| 위치 | 기록 |
|---|---|
| ADR-003:22 | 네이티브 `tool_calls`가 "Ollama 0.24에서 자주 비어 있음" |
| `docs/development-log.md:147` | "Hermes가 `search_vault` tool 미호출 → Qwen만 답 → 환각" |
| `src/agents/hermes_router.py:32` | "Hermes on Ollama often skips tool_calls; keyword fallback…" |

성공 사례(`TASK-8f744eba`, `TASK-a9198b0e`)도 `hermes:fallback_search:1_hits`로 기록돼 **툴 호출이 아니라 키워드 폴백 경유**입니다. `handoff/2026-05-26-to-claude.md:111`(로컬 전용 문서, 비공개)에 "다른 8B FC 모델?"이라는 질문이 열린 채 남아 있고, 다음 날 핸드오프(`:26`)에서 "Hermes tool 대개편 — 시간 대비 이득 작음"으로 보류됐습니다. **qwen3로 라우팅을 시도한 기록은 없습니다.**

비용: 라우터 전용 모델 때문에 ADR-003이 **VRAM 동시 적재 금지 + 스왑 지연 수용**이라는 제약을 떠안았고(10GB), 모델 1개(~4.7GB)를 추가로 보관합니다. 라우터를 `qwen3:8b`로 통일하면 **스왑 자체가 사라집니다.**

고칠 방향: `.env`의 `OLLAMA_ROUTER_MODEL=qwen3:8b` 한 줄만 바꿔 `run_hermes_once` + `--ood`를 돌려 `tool_calls` 반환율을 비교(모델 교체만으로 A/B 가능). 결과를 ADR-003에 "Alternatives considered"로 추가하거나 ADR-004로 기록. 현재 Ollama가 0.24 → **0.35.1**이라 당시 관측이 그대로 유효하지 않을 가능성도 함께 확인.

---

## 묶어서 보면

**설정 누락 묶음 (1·2·5·6·7)** — "Ollama 호출에 `options`/`keep_alive`/`think`를 아무것도 안 넘긴다"는 한 원인. `src/worker.py:call_ollama` 페이로드에 `options`(`num_ctx`, `temperature`) + `keep_alive` + `think`를 추가하고 그 값을 `Settings`에 올리면 다섯 개가 함께 정리됨. 1·7은 곱해져 악화되는 조합.

**예산 불일치 묶음 (3·4·14)** — 재시도·타임아웃·툴 스텝 상한이 서로 모르는 채 각각 정해짐. `GRAPH_MAX_RETRIES`는 이름과 실제 횟수가 어긋나고(실측 총 2회), `MAX_TOOL_STEPS`는 도달 불가, 워커·오케스트레이터 타임아웃은 역전. **세 예산을 한자리에서 계산해야 함.**

**검색 품질 묶음 (9·10)** — 임베딩이 본 텍스트와 프롬프트에 들어가는 텍스트, 벡터 점수와 키워드 점수가 각각 어긋남.

**조용한 실패 묶음 (8·11)** — 에러 없이 기능이 죽거나 데이터가 오염되고 **로그조차 남지 않음**. 테스트도 통과하므로 가장 늦게 발견됨. 8번은 한 줄 수정이지만 **우선순위 최상위**.

**예외 처리 일관성 (15)** — 워커 Envelope 파싱과 툴 인자 파싱은 JSON 실패를 잡는데 `_chat`만 안 잡음. 같은 패턴을 맞추면 끝.

**문서·근거 (12·13·16)** — 12는 값 하나 맞추면 끝. 16은 `.env` 한 줄로 A/B가 가능하니 측정 후 ADR 보강. 13은 구조적 과제로 검증 노드 설계가 필요함.

---

## 부록 — 이 문서를 쓰며 정정한 것

| 항목 | 처음 적은 값 | 실측 후 |
|---|---|---|
| `GRAPH_MAX_RETRIES=2`의 시도 횟수 (4번 항목) | 최대 3회 | **총 2회** (`route` 방문 2회) |

> `docs/study/00-MALA-study-guide.md:277`에도 "`max_retries=2`(최대 3회 시도)" 서술이 있습니다. 같은 off-by-one이므로 함께 정정이 필요합니다(이 노트에서는 건드리지 않았습니다).

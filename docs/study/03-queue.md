# Redis 큐 경로 전체 코드 — Envelope · Broker · Worker · answer_via_queue

> 학습용 읽기 전용 노트 (2026-10-09 작성). 코드 수정 없음.
> 관련 노트: [`02-ollama-calls.md`](02-ollama-calls.md) · [`fix-later.md`](fix-later.md)

오케스트레이터가 질문을 큐에 넣고 답을 받아오는 왕복 경로에 관여하는 코드 전부입니다.

```
answer_via_queue ──push_task──> [task_queue] ──claim_task(BRPOPLPUSH)──> handle_message
       ^                                          │                          │
       └──pop_result(BLPOP)── [result_queue] <──push_result──────────────────┘
                                                  └──> [processing_queue] / [dead_letter_queue]
```

---

## 1. `src/schemas/message.py` (전체 79줄)

A2A 메시지 계약. 큐를 오가는 모든 JSON의 형태를 여기서만 정의합니다.

```python
"""JSON Envelope — Phase 1 A2A contract."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Intent(str, Enum):
    ROUTE = "route"
    ANALYZE = "analyze"
    CODE = "code"


class TaskStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    INVALID = "invalid"


class EnvelopeHeader(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sender: str
    receiver: str
    task_id: str


class EnvelopePayload(BaseModel):
    intent: Intent
    instruction: str
    context: dict[str, Any] = Field(default_factory=dict)
    context_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class TaskEnvelope(BaseModel):
    header: EnvelopeHeader
    payload: EnvelopePayload

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> TaskEnvelope:
        return cls.model_validate_json(raw)


class ResultHeader(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    task_id: str
    status: TaskStatus
    error: str | None = None


class ResultPayload(BaseModel):
    response: str = ""
    model: str | None = None


class ResultEnvelope(BaseModel):
    header: ResultHeader
    payload: ResultPayload

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> ResultEnvelope:
        return cls.model_validate_json(raw)
```

**함수·클래스별 한 줄 설명**

| 대상 | 설명 |
|---|---|
| `Intent` | 작업 종류 3가지(`route`/`analyze`/`code`)를 문자열 Enum으로 고정해 오타를 막는다. |
| `TaskStatus` | 결과 상태 3가지(`success`/`error`/`invalid`)를 문자열 Enum으로 고정한다. |
| `EnvelopeHeader` | 누가·누구에게·언제 보냈는지와 `task_id`를 담고, `message_id`·`timestamp`는 생성 시 자동 채운다. |
| `EnvelopePayload` | 실제 지시문(`instruction`) + 검색된 컨텍스트(`context`) + 출처 ID(`context_refs`) + 제약(`constraints`)을 담는다. |
| `TaskEnvelope` | 헤더 + 페이로드를 묶은 요청 봉투. |
| `TaskEnvelope.to_json` | Pydantic 모델을 Redis에 넣을 JSON 문자열로 직렬화한다. |
| `TaskEnvelope.from_json` | 큐에서 꺼낸 원문을 검증하며 역직렬화한다(스키마 위반 시 예외 → 워커가 DLQ로 보냄). |
| `ResultHeader` | 결과의 `task_id`·`status`와, 실패 시 `error` 문자열을 담는다. |
| `ResultPayload` | 모델 응답 본문(`response`)과 어떤 모델이 답했는지(`model`)를 담는다. |
| `ResultEnvelope` | 헤더 + 페이로드를 묶은 응답 봉투. |
| `ResultEnvelope.to_json` / `from_json` | 요청 봉투와 동일한 직렬화·역직렬화 쌍. |

> `ResultPayload.response`의 기본값이 `""`라서 **실패 결과도 스키마상 유효**합니다. 그래서 빈 답 판정은 스키마가 아니라 `validate_node`의 "8자 이상" 규칙이 담당합니다.

---

## 2. `src/broker/redis_queue.py` (전체 59줄)

Redis 리스트 4개를 다루는 얇은 래퍼. 큐 이름은 모두 `Settings`에서 주입됩니다.

```python
"""Redis list queues — reliable claim via BRPOPLPUSH (Redis 5+ compatible)."""

from __future__ import annotations

import redis

from src.config import Settings, get_settings


class RedisBroker:
    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._client = redis.Redis(
            host=self._s.redis_host,
            port=self._s.redis_port,
            db=self._s.redis_db,
            decode_responses=True,
        )

    @property
    def client(self) -> redis.Redis:
        return self._client

    def ping(self) -> bool:
        return bool(self._client.ping())

    def push_task(self, raw: str) -> None:
        self._client.rpush(self._s.task_queue, raw)

    def claim_task(self, timeout: int = 0) -> str | None:
        """Atomically move one message task_queue → processing_queue."""
        return self._client.brpoplpush(
            self._s.task_queue,
            self._s.processing_queue,
            timeout,
        )

    def ack_processing(self, raw: str) -> None:
        self._client.lrem(self._s.processing_queue, 1, raw)

    def push_result(self, raw: str) -> None:
        self._client.rpush(self._s.result_queue, raw)

    def pop_result(self, timeout: int = 30) -> str | None:
        item = self._client.blpop(self._s.result_queue, timeout)
        if item is None:
            return None
        _, raw = item
        return raw

    def push_dead_letter(self, raw: str) -> None:
        self._client.rpush(self._s.dead_letter_queue, raw)

    def requeue_processing(self, raw: str) -> None:
        """Return a stuck processing message to task_queue (manual recovery)."""
        pipe = self._client.pipeline()
        pipe.lrem(self._s.processing_queue, 1, raw)
        pipe.lpush(self._s.task_queue, raw)
        pipe.execute()
```

**메서드별 한 줄 설명**

| 메서드 | 설명 |
|---|---|
| `__init__` | `Settings`로 Redis 커넥션을 만들고 `decode_responses=True`로 문자열을 바로 받게 한다. |
| `client` | 내부 Redis 클라이언트를 읽기 전용으로 노출한다(스크립트에서 직접 조회할 때 사용). |
| `ping` | Redis가 살아 있는지 확인한다(`check_redis.py`와 워커 기동 시 사전 점검). |
| `push_task` | 요청 봉투를 `task_queue` 오른쪽에 넣는다(`RPUSH`). |
| `claim_task` | `BRPOPLPUSH`로 `task_queue` → `processing_queue` **원자적 이동** — 워커가 죽어도 작업이 사라지지 않는다. |
| `ack_processing` | 처리 완료된 원문을 `processing_queue`에서 1건 제거한다(`LREM`). |
| `push_result` | 결과 봉투를 `result_queue` 오른쪽에 넣는다(`RPUSH`). |
| `pop_result` | `BLPOP`으로 `result_queue` 왼쪽에서 결과를 1건 꺼낸다(타임아웃 시 `None`). |
| `push_dead_letter` | 처리 불가 원문을 `dead_letter_queue`에 보관한다. |
| `ack_processing` + `push_dead_letter` | (워커에서 짝으로 호출) 실패 작업을 DLQ에 남기고 처리 큐에서는 뺀다. |
| `requeue_processing` | 멈춰 있는 `processing_queue` 항목을 파이프라인으로 `task_queue`로 되돌린다(**수동** 복구용). |

> 큐 방향이 `RPUSH` + `BRPOPLPUSH`(오른쪽에서 꺼냄)이므로 **작업은 FIFO**입니다. 단 `pop_result`는 `BLPOP`(왼쪽)이고 `push_result`는 `RPUSH`(오른쪽)이라 **결과도 FIFO**입니다.
>
> `requeue_processing`을 자동으로 호출하는 코드는 없습니다 — 워커가 중간에 죽으면 `processing_queue`에 남은 항목은 사람이 직접 되돌려야 합니다.

---

## 3. `src/worker.py:75-115` — `handle_message`

```python
def handle_message(
    broker: RedisBroker,
    settings: Settings,
    raw: str,
) -> None:
    try:
        envelope = TaskEnvelope.from_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Invalid envelope: %s", exc)
        broker.push_dead_letter(raw)
        broker.ack_processing(raw)
        return

    task_id = envelope.header.task_id
    logger.info("Processing task %s", task_id)

    try:
        ollama_result = call_ollama(build_prompt(envelope), settings)
        result = ResultEnvelope(
            header=ResultHeader(task_id=task_id, status=TaskStatus.SUCCESS),
            payload=ResultPayload(
                response=ollama_result.get("response", ""),
                model=settings.ollama_model,
            ),
        )
        broker.push_result(result.to_json())
        broker.ack_processing(raw)
        logger.info("Task %s success", task_id)
    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        error_result = ResultEnvelope(
            header=ResultHeader(
                task_id=task_id,
                status=TaskStatus.ERROR,
                error=str(exc),
            ),
            payload=ResultPayload(response=""),
        )
        broker.push_result(error_result.to_json())
        broker.push_dead_letter(raw)
        broker.ack_processing(raw)
```

**한 줄 설명:** 큐에서 꺼낸 원문을 Envelope로 검증해 Ollama를 호출하고, 성공이든 실패든 결과를 `result_queue`에 넣은 뒤 반드시 `ack_processing`으로 처리 큐를 비운다.

세부 동작 3가지:

| 경로 | 처리 | 코드 |
|---|---|---|
| 스키마 위반 | 결과를 **안 보내고** DLQ + ack만 (오케스트레이터는 타임아웃까지 기다림) | `:82-86` |
| 성공 | `result_queue`에 `SUCCESS` + ack | `:92-102` |
| Ollama 실패 | `result_queue`에 `ERROR` + **DLQ에도 기록** + ack | `:103-115` |

> 세 경로 모두 `ack_processing`을 호출하므로 `processing_queue`가 새지 않습니다. 대신 **재처리는 없습니다** — 실패 작업은 DLQ로 가고 자동 재시도는 오케스트레이터의 `validate` 루프가 담당합니다.
>
> 스키마 위반 경로만 결과를 보내지 않는 비대칭이 있어, 잘못된 Envelope가 들어오면 오케스트레이터는 120초를 꽉 기다립니다 ([`fix-later.md`](fix-later.md) 4번 항목과 연결).

---

## 4. `src/worker.py:132-156` — `main` 루프

```python
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = get_settings()
    broker = RedisBroker(settings)
    if not broker.ping():
        logger.error(
            "Redis unreachable at %s:%s — start Native Redis first.",
            settings.redis_host,
            settings.redis_port,
        )
        sys.exit(1)
    logger.info(
        "Worker %s — waiting for tasks (Ctrl+C to stop)",
        settings.worker_id,
    )
    try:
        while True:
            raw = broker.claim_task(timeout=5)
            if raw:
                handle_message(broker, settings, raw)
    except KeyboardInterrupt:
        logger.info("Worker stopped")
```

**한 줄 설명:** Redis 연결을 먼저 확인하고(실패 시 즉시 종료), 5초 블로킹으로 작업을 하나씩 집어 `handle_message`에 넘기는 단일 스레드 무한 루프를 돈다.

- `ping()` 실패 시 `sys.exit(1)` — 큐가 없는 상태로 조용히 도는 일을 막는다 (`:139-145`)
- `claim_task(timeout=5)`는 5초마다 깨어나므로 `Ctrl+C`(`KeyboardInterrupt`)가 바로 먹는다 (`:152`)
- **동시성 없음** — 작업 1건을 끝낼 때까지 다음 건을 집지 않는다. 워커를 늘리려면 `WORKER_ID`와 `PROCESSING_QUEUE`를 다르게 준 프로세스를 따로 띄워야 한다 (`.env`의 `PROCESSING_QUEUE=mala:processing:worker_1`)

> 같은 파일의 `process_one()`(`:118-129`)은 `timeout=0`(비블로킹)으로 1건만 처리하고 큐가 비면 `False`를 반환하는 테스트·스크립트용 변형입니다.

---

## 5. `src/agents/nodes.py:166-217` — `answer_via_queue`

```python
def answer_via_queue(
    state: dict,
    *,
    settings: Settings,
    broker: RedisBroker,
    store: TaskStatusStore,
    timeout_sec: float = 120,
) -> dict:
    task_id = state["task_id"]
    intent = Intent(state["intent"])
    context, refs = _payload_from_state(state)
    envelope = TaskEnvelope(
        header=EnvelopeHeader(
            sender="orchestrator",
            receiver=settings.worker_id,
            task_id=task_id,
        ),
        payload=EnvelopePayload(
            intent=intent,
            instruction=state["task_input"],
            context=context,
            context_refs=refs,
        ),
    )
    _status(state, store, "answer", {"phase": "queue_publish"})
    broker.push_task(envelope.to_json())

    deadline = time.time() + timeout_sec
    answer = ""
    last_error = ""
    while time.time() < deadline:
        raw = broker.pop_result(timeout=5)
        if not raw:
            continue
        result = ResultEnvelope.from_json(raw)
        if result.header.task_id != task_id:
            logger.warning("Ignoring result for %s", result.header.task_id)
            continue
        if result.header.status == TaskStatus.SUCCESS:
            answer = result.payload.response.strip()
            _status(state, store, "answer", {"phase": "done", "via": "queue"})
            return {"answer": answer, "history": ["answer:queue:ok"]}
        last_error = result.header.error or "worker_error"
        break

    _status(state, store, "answer", {"phase": "failed", "error": last_error})
    return {
        "answer": "",
        "valid": False,
        "last_error": last_error or "result_timeout",
        "history": ["answer:queue:fail"],
    }
```

**한 줄 설명:** 그래프 상태를 요청 Envelope로 조립해 `task_queue`에 넣고, 최대 120초 동안 `result_queue`를 폴링하며 **`task_id`가 일치하는** 성공 결과만 답변으로 채택한다.

단계별로:

| 단계 | 코드 | 동작 |
|---|---|---|
| 1 | `:176-189` | `_payload_from_state`로 검색 청크·출처를 꺼내 `TaskEnvelope` 조립 (`sender=orchestrator`, `receiver=settings.worker_id`) |
| 2 | `:190-191` | `task_status`에 `phase=queue_publish` 기록 후 `push_task` |
| 3 | `:193-199` | 120초 데드라인을 걸고 `pop_result(timeout=5)`로 폴링 (빈 응답은 `continue`) |
| 4 | `:200-203` | `task_id` 불일치 결과는 **로그만 남기고 폐기** |
| 5 | `:204-207` | `SUCCESS`면 `answer` + `history=["answer:queue:ok"]` 반환 |
| 6 | `:208-209` | `ERROR`면 `last_error`를 잡고 **즉시 루프 탈출**(재시도는 `validate`가 담당) |
| 7 | `:211-217` | 타임아웃·에러 모두 `valid=False` + `last_error`(기본 `result_timeout`)로 반환 |

읽을 때 눈여겨볼 지점 3가지:

1. **`timeout_sec=120`이 하드코딩된 기본 인자** (`:172`)입니다. `Settings`에서 오지 않으므로 `.env`의 `OLLAMA_TIMEOUT_SEC`를 늘려도 여기는 그대로 120초입니다 → 워커 최악 366초와 어긋남 ([`fix-later.md`](fix-later.md) 4번).
2. **`task_id` 불일치 결과는 되돌려 놓지 않고 버립니다** (`:202`). 동시에 두 작업이 돌면 남의 결과를 소비해 영구 유실시킵니다. `result_queue`가 단일 소비자 전제라는 뜻입니다.
3. **그래프 재시도 때 `task_id`가 바뀌지 않습니다** (`new_task_state`에서 한 번만 발급, `:288`). 그래서 1차의 늦은 결과가 2차 라운드의 `:201` 필터를 통과해 **조용히 2차 답변으로 채택**될 수 있습니다.

---

## 요약 — 신뢰성 장치와 빈 구멍

| 장치 | 구현 위치 | 상태 |
|---|---|---|
| 작업 유실 방지 | `claim_task`의 `BRPOPLPUSH` | ✅ 원자적 |
| 처리 큐 누수 방지 | `handle_message`의 모든 경로에서 `ack_processing` | ✅ 3경로 모두 |
| 잘못된 메시지 격리 | `push_dead_letter` | ✅ 파싱 실패·실행 실패 모두 |
| 일시적 오류 재시도 | `call_ollama`의 tenacity 3회 | ⚠️ 4xx까지 재시도 ([`fix-later.md`](fix-later.md) 3번) |
| 결과 라우팅 | `task_id` 비교 | ⚠️ 단일 소비자 전제, 불일치는 폐기 |
| 워커 크래시 복구 | `requeue_processing` | ⚠️ **수동 전용** — 자동 호출부 없음 |
| 타임아웃 예산 | 워커 366초 vs 오케스트레이터 120초 | ⚠️ 역전 ([`fix-later.md`](fix-later.md) 4번) |

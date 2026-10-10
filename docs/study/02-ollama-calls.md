# Ollama 호출 지점 정리 — call_ollama / _chat / _embed_batch

> 학습용 읽기 전용 노트 (2026-10-09 작성). 코드 수정 없음.
> MALA에서 Ollama HTTP API를 때리는 곳은 아래 3개 파일, 4개 엔드포인트가 전부입니다.

| # | 파일 | 함수 | 엔드포인트 |
|---|---|---|---|
| 1 | `src/worker.py` | `call_ollama` | `/api/generate` |
| 2 | `src/agents/hermes_router.py` | `_chat` | `/api/chat` |
| 3 | `src/retrieval/embedder.py` | `_embed_batch` | `/api/embed` → `/api/embeddings` (폴백) |

---

## 1. `src/worker.py:30-48` — `call_ollama`

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
    reraise=True,
)
def call_ollama(prompt: str, settings: Settings) -> dict:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
    with httpx.Client(timeout=settings.ollama_timeout_sec) as client:
        response = client.post(
            url,
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()
```

**한 줄 설명:** 완성된 프롬프트를 Ollama `/api/generate`에 비스트리밍으로 POST하고, 네트워크·HTTP 오류는 tenacity로 최대 3회 지수 백오프 재시도한다.

---

## 2. `src/agents/hermes_router.py:68-83` — `_chat` (`/api/chat` 호출부)

```python
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
```

호출 지점은 `plan_route()` 안의 `hermes_router.py:131` (`data = _chat(messages, settings)`), 그 직전 `:126-129`에서 `system`(SYSTEM_PROMPT) + `user`(task_input) 2개 메시지를 조립합니다.

**한 줄 설명:** 라우터 모델(`hermes3:8b`)에 `search_vault` 툴 스펙을 붙여 `/api/chat`을 temperature 0으로 한 번 호출하고, 응답의 `message.tool_calls`를 그대로 반환한다.

---

## 3. `src/retrieval/embedder.py:20-51` — 임베딩 호출 + 폴백

```python
    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []
        return _embed_batch(input, self._settings)


def _embed_batch(texts: list[str], settings: Settings) -> list[list[float]]:
    """Call Ollama /api/embed (fallback /api/embeddings)."""
    timeout = settings.ollama_timeout_sec
    with httpx.Client(timeout=timeout) as client:
        try:
            resp = client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/embed",
                json={"model": settings.ollama_embed_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings")
            if embeddings:
                return embeddings
        except httpx.HTTPError as exc:
            logger.debug("Ollama /api/embed failed: %s", exc)

        out: list[list[float]] = []
        for text in texts:
            resp = client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
                json={"model": settings.ollama_embed_model, "prompt": text},
            )
            resp.raise_for_status()
            out.append(resp.json()["embedding"])
        return out
```

**한 줄 설명:** 신규 배치 API `/api/embed`에 전체 텍스트를 한 번에 보내고, HTTP 오류이거나 `embeddings` 키가 비어 있으면 구버전 `/api/embeddings`로 한 건씩 순차 재호출한다.

> 폴백 트리거가 두 가지인 점이 포인트입니다 — `except httpx.HTTPError`(예외)뿐 아니라 `if embeddings:`가 falsy인 경우(200 응답이지만 빈 결과)에도 `try` 블록을 그냥 빠져나와 아래 루프로 내려갑니다.

---

## 옵션 비교: `num_ctx` · `keep_alive` · `temperature`

| 호출 | `options.num_ctx` | `keep_alive` | `options.temperature` | 실제로 들어가는 것 |
|---|---|---|---|---|
| `worker.py` `/api/generate` | ❌ 없음 | ❌ 없음 | ❌ 없음 | `model`, `prompt`, `stream: False` 뿐 |
| `hermes_router.py` `/api/chat` | ❌ 없음 | ❌ 없음 | ✅ **`0`** | `model`, `messages`, `tools`, `stream: False`, `options.temperature` |
| `embedder.py` `/api/embed` | ❌ 없음 | ❌ 없음 | ❌ 해당 없음 | `model`, `input` |
| `embedder.py` `/api/embeddings` | ❌ 없음 | ❌ 없음 | ❌ 해당 없음 | `model`, `prompt` |

**정리하면 `temperature=0`은 Hermes 라우터 호출에만 있고, `num_ctx`와 `keep_alive`는 레포 전체에서 단 한 번도 전송되지 않습니다.**

레포 전체 확인 결과 `num_ctx`/`keep_alive` 문자열은 `src/` 어디에도 없고, `options` 딕셔너리를 만드는 곳도 `hermes_router.py:78` 한 곳뿐입니다. `.env.example`에는 `MAX_MODEL_LEN=4096`, `GPU_MEMORY_UTILIZATION=0.85`가 있지만 `config.py`의 `Settings`에 해당 필드가 없어 **읽히지 않습니다** (vLLM 시절 잔재로 보이고, 파일 주석도 "Phase 1+ reference; Ollama manages VRAM"이라고 적어 둠).

### 실질적 영향 3가지

1. **컨텍스트 길이**는 Ollama 서버 측 모델 기본값(`qwen3:8b` modelfile)에 전적으로 맡겨집니다. `build_prompt`가 청크 5개 × 최대 1200자를 붙이므로(`pipeline.py:296`, `RAG_TOP_K=5`) 기본 `num_ctx`가 작으면 앞쪽 컨텍스트가 조용히 잘릴 수 있습니다 — 잘려도 에러가 아니라 그냥 답변 품질로만 나타납니다.
2. **모델 언로드 타이밍**도 Ollama 기본값(마지막 호출 후 5분)에 맡겨집니다. ADR-003의 "Hermes와 Qwen 동시 적재 금지" 정책은 `keep_alive: 0`으로 코드에서 강제한 게 아니라, 호출 순서(라우터 → 임베딩 → 워커 생성)와 Ollama의 자동 스왑에 의존합니다.
3. **답변 모델의 temperature는 미지정**이라 `/api/generate` 호출은 모델 기본값(비결정적)을 씁니다. 라우팅만 결정적이고 최종 답변은 매 실행마다 달라질 수 있습니다.

---

## 참고

- 타임아웃은 3곳 모두 `settings.ollama_timeout_sec` (`.env`의 `OLLAMA_TIMEOUT_SEC`, 기본 120초) 공유
- 재시도(tenacity)는 `call_ollama`에만 걸려 있고, `_chat`과 `_embed_batch`에는 없음
- 관련 ADR: [`docs/decisions/003-phase4-hermes-router.md`](../decisions/003-phase4-hermes-router.md) — VRAM 10GB 동시 적재 금지 정책

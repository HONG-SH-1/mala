"""LangGraph nodes — route, retrieve (stub), answer, validate."""

from __future__ import annotations

import logging
import time
import uuid

from src.broker import RedisBroker
from src.broker.task_status import TaskStatusStore
from src.config import Settings, get_settings
from src.schemas import (
    EnvelopeHeader,
    EnvelopePayload,
    Intent,
    ResultEnvelope,
    TaskEnvelope,
    TaskStatus,
)
from src.retrieval.pipeline import VaultRetriever
from src.worker import build_prompt, call_ollama

logger = logging.getLogger(__name__)

_RETRIEVAL_KEYWORDS = ("옵시디언", "노트", "rag", "검색", "wiki", "[[", "vault")


def _status(
    state: dict,
    store: TaskStatusStore,
    node: str,
    extra: dict | None = None,
) -> None:
    task_id = state["task_id"]
    fields = {
        "node": node,
        "route": state.get("route_decision", ""),
        "error_count": state.get("error_count", 0),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        fields.update(extra)
    store.update(task_id, fields)


def route_node(state: dict, *, store: TaskStatusStore) -> dict:
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


def _payload_from_state(state: dict) -> tuple[dict, list[str]]:
    chunks = state.get("retrieved_chunks") or []
    refs = state.get("context_refs") or []
    context: dict = {}
    if chunks:
        context["retrieved"] = chunks
    if state.get("analysis_result"):
        context["analysis"] = state["analysis_result"]
    return context, refs


def retrieve_node(
    state: dict,
    *,
    store: TaskStatusStore,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    query = state["task_input"]
    try:
        retriever = VaultRetriever(settings)
        hits = retriever.search(query)
        context_text = retriever.format_context(hits)
        chunk_dicts = retriever.hits_to_chunks(hits)
        refs = [c["id"] for c in chunk_dicts]
        _status(
            state,
            store,
            "retrieve",
            {
                "hits": len(hits),
                "refs": ",".join(refs[:5]),
            },
        )
        return {
            "analysis_result": context_text,
            "retrieved_chunks": chunk_dicts,
            "context_refs": refs,
            "history": [f"retrieve:{len(hits)}_hits"],
        }
    except Exception as exc:
        logger.exception("Retrieve failed: %s", exc)
        _status(state, store, "retrieve", {"error": str(exc)})
        return {
            "analysis_result": "",
            "retrieved_chunks": [],
            "context_refs": [],
            "history": ["retrieve:error"],
            "last_error": str(exc),
        }


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


def answer_inline(
    state: dict,
    *,
    settings: Settings,
    store: TaskStatusStore,
) -> dict:
    """Direct Ollama call when no worker process is running."""
    task_id = state["task_id"]
    intent = Intent(state["intent"])
    context, refs = _payload_from_state(state)
    envelope = TaskEnvelope(
        header=EnvelopeHeader(
            sender="orchestrator",
            receiver="worker_1",
            task_id=task_id,
        ),
        payload=EnvelopePayload(
            intent=intent,
            instruction=state["task_input"],
            context=context,
            context_refs=refs,
        ),
    )
    _status(state, store, "answer", {"phase": "inline"})
    try:
        result = call_ollama(build_prompt(envelope), settings)
        answer = result.get("response", "").strip()
        _status(state, store, "answer", {"phase": "done", "via": "inline"})
        return {"answer": answer, "history": ["answer:inline:ok"]}
    except Exception as exc:
        return {
            "answer": "",
            "valid": False,
            "last_error": str(exc),
            "history": ["answer:inline:fail"],
        }


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
        "max_retries": max_retries,
        "valid": False,
        "history": [],
    }

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
) -> dict:
    """
    Returns partial state update: route_decision, optional retrieved_chunks, tool_step_count, history.
    """
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

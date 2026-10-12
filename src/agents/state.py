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

    # study 모드 플래그. 여기 선언하지 않으면 LangGraph가 그래프 입력에서 조용히 버린다 (fix-later #8).
    force_vault_rag: bool

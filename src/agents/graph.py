"""LangGraph orchestrator — Phase 2 minimal loop."""

from __future__ import annotations

import logging
from functools import partial
from typing import Literal

from langgraph.graph import END, StateGraph

from src.agents.nodes import (
    answer_inline,
    answer_via_queue,
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
) -> AgentState:
    settings = settings or get_settings()
    store = TaskStatusStore(settings)
    initial = new_task_state(
        task_input,
        max_retries=settings.graph_max_retries,
    )
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

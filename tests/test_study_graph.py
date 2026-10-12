"""Study mode through a compiled LangGraph graph (fix-later #8).

test_study_route.py calls route_node with a plain dict, which skips
LangGraph's input filtering. Keys not declared in AgentState are dropped
before the first node runs, so that unit test passed while study mode
was silently broken. This test goes through StateGraph(AgentState) so the
real schema decides what reaches the node.
"""

from functools import partial

from langgraph.graph import END, StateGraph

from src.agents.nodes import route_node
from src.agents.state import AgentState


class _NoOpStore:
    def update(self, task_id: str, fields: dict) -> None:
        pass


def _compiled_route_graph():
    graph = StateGraph(AgentState)
    graph.add_node("route", partial(route_node, store=_NoOpStore()))
    graph.set_entry_point("route")
    graph.add_edge("route", END)
    return graph.compile()


def test_force_vault_rag_survives_graph_input():
    app = _compiled_route_graph()
    final = app.invoke(
        {
            "task_id": "T-study-graph",
            "task_input": "인증 흐름이 뭐야?",  # no retrieval keyword
            "error_count": 0,
            "force_vault_rag": True,
        }
    )
    assert final["route_decision"] == "needs_context"
    assert final["history"][0] == "route:needs_context:study"


def test_without_flag_keywordless_question_stays_simple():
    app = _compiled_route_graph()
    final = app.invoke(
        {
            "task_id": "T-no-study",
            "task_input": "인증 흐름이 뭐야?",
            "error_count": 0,
        }
    )
    assert final["route_decision"] == "simple"
    assert final["history"][0] == "route:simple"

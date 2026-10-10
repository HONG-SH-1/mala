"""Study mode forces vault RAG routing."""

from src.agents.nodes import route_node


class _NoOpStore:
    def update(self, task_id: str, fields: dict) -> None:
        pass


def test_route_force_vault_rag_without_keywords():
    state = {
        "task_id": "T-study",
        "task_input": "인증 흐름이 뭐야?",
        "error_count": 0,
        "force_vault_rag": True,
    }
    out = route_node(state, store=_NoOpStore())
    assert out["route_decision"] == "needs_context"
    assert "study" in out["history"][0]

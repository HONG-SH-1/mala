"""Phase 2 — route node branching (no Redis/Ollama)."""

from src.agents.nodes import route_node


class _NoOpStore:
    def update(self, task_id: str, fields: dict) -> None:
        pass


def _route(text: str) -> str:
    state = {"task_id": "T-test", "task_input": text, "error_count": 0}
    out = route_node(state, store=_NoOpStore())
    return out["route_decision"]


def test_route_needs_context_korean():
    assert _route("옵시디언 노트에서 검색해줘") == "needs_context"


def test_route_simple_code():
    assert _route("write python code for fibonacci") == "simple"


def test_route_simple_default():
    assert _route("hello world") == "simple"

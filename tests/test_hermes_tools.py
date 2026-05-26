from src.agents.hermes_router import fallback_vault_query
from src.schemas.tools import SearchVaultArgs, search_vault_tool_spec


def test_search_vault_args():
    args = SearchVaultArgs.model_validate({"query": "MALA Phase 2"})
    assert args.query == "MALA Phase 2"


def test_tool_spec_has_name():
    spec = search_vault_tool_spec()
    assert spec["function"]["name"] == "search_vault"


def test_fallback_vault_query_obsidian():
    q = "옵시디언 노트에서 환영 메시지가 뭐라고 적혀 있어?"
    assert fallback_vault_query(q) == q


def test_fallback_vault_query_ood():
    q = "2026년 FIFA 월드컵 우승팀은 어느 나라야?"
    assert fallback_vault_query(q) is None

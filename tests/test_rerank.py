from src.retrieval.chroma_store import SearchHit
from src.retrieval.rerank import rerank_hits


def test_rerank_prefers_phase2_file():
    hits = [
        SearchHit("a", "Phase-3-RAG.md", "Demo", "vault Phase 2 설명", 0.1),
        SearchHit(
            "b",
            "Phase-2-Agent.md",
            "Phase 2 — Agent Layer",
            "LangGraph orchestrator Redis",
            0.5,
        ),
        SearchHit("c", "MALA-Overview.md", "Overview", "local LLM", 0.2),
    ]
    out = rerank_hits("vault 노트에서 MALA Phase 2 설명", hits, 2)
    assert out[0].source == "Phase-2-Agent.md"

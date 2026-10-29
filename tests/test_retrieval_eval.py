"""검색만 재기(--retrieval-only)와 RAG_RERANK 스위치 — Ollama, Chroma 없이 가짜로 확인한다."""

from dataclasses import replace

import pytest

from src.config import get_settings
from src.eval.runner import (
    Question,
    evidence_ranks,
    render_retrieval_markdown,
    run_retrieval_eval,
    summarize_retrieval,
)
from src.retrieval.chroma_store import SearchHit
from src.retrieval.pipeline import VaultRetriever

# --- RAG_RERANK 스위치 ------------------------------------------------------


class _FakeStore:
    """Chroma처럼 거리순으로 돌려준다."""

    def __init__(self, hits):
        self.hits = hits

    def search(self, query, top_k):
        return self.hits[:top_k]


HITS = [
    SearchHit("c1", "a.md", "무관한 제목", "본문", 0.1),
    SearchHit("c2", "b.md", "Redis 큐", "Redis 큐 설명", 0.5),
]


def _retriever(mode: str) -> VaultRetriever:
    r = VaultRetriever.__new__(VaultRetriever)  # 실제 Chroma를 열지 않는다
    r._settings = replace(get_settings(), rag_rerank=mode, rag_top_k=1)
    r._store = _FakeStore(HITS)
    return r


def test_rerank_keyword_is_current_behavior():
    # 키워드 점수가 먼저라 거리가 먼 b.md가 올라온다 (지금 동작).
    assert [h.chunk_id for h in _retriever("keyword").search("Redis 큐")] == ["c2"]


def test_rerank_off_keeps_distance_order():
    assert [h.chunk_id for h in _retriever("off").search("Redis 큐")] == ["c1"]


def test_rerank_default_and_invalid_value(monkeypatch):
    monkeypatch.delenv("RAG_RERANK", raising=False)
    assert get_settings().rag_rerank == "keyword"
    monkeypatch.setenv("RAG_RERANK", "OFF")
    assert get_settings().rag_rerank == "off"
    monkeypatch.setenv("RAG_RERANK", "bm25")
    with pytest.raises(ValueError):
        get_settings()


# --- 답 근거 청크 -----------------------------------------------------------

Q = Question("q1", "?", "in_notes", ["a.md"], ["Ollama", "BIOS"])


def _chunk(source, context, chars=500):
    return {"chunk_id": source, "source": source, "heading": "", "chars": chars,
            "distance": 0.1, "context": context}


def test_evidence_loose_and_strict():
    chunks = [
        _chunk("other.md", "ollama와 bios 이야기"),  # 단어는 다 있지만 기대 출처가 아님
        _chunk("a.md", "Ollama만"),  # 기대 출처지만 단어가 모자람
        _chunk("a.md", "BIOS 때문에 Ollama를 호스트에"),
    ]
    assert evidence_ranks(Q, chunks) == (1, 3)


def test_evidence_words_split_across_chunks_do_not_count():
    chunks = [_chunk("a.md", "Ollama"), _chunk("a.md", "BIOS")]
    assert evidence_ranks(Q, chunks) == (None, None)


def test_evidence_without_keywords_is_not_judged():
    q = Question("q2", "?", "in_notes", ["a.md"], [])
    assert evidence_ranks(q, [_chunk("a.md", "아무거나")]) == (None, None)


def test_default_search_checks_text_cut_at_1200_chars():
    # format_context가 본문을 1200자에서 자르므로, 그 뒤의 단어는 프롬프트에 없다.
    r = VaultRetriever.__new__(VaultRetriever)
    hit = SearchHit("c1", "a.md", "제목", "Ollama " + "x" * 1300 + " BIOS", 0.1)
    context = r.format_context([hit])
    assert evidence_ranks(Q, [_chunk("a.md", context)]) == (None, None)


# --- 실행과 요약 ------------------------------------------------------------


def test_run_retrieval_eval_summary_and_markdown():
    questions = [
        Q,
        Question("q2", "?", "in_notes", ["b.md"], ["Redis"]),
        Question("q3", "?", "not_in_notes"),  # 검색 평가에서는 뺀다
    ]
    fake = {
        "q1": [_chunk("a.md", "BIOS Ollama", chars=150), _chunk("c.md", "x", chars=900)],
        "q2": [_chunk("b.md", "제목만", chars=24), _chunk("c.md", "Redis", chars=300)],
    }
    by_text = {"Q1": "q1", "Q2": "q2"}
    questions[0] = replace(Q, question="Q1")
    questions[1] = replace(questions[1], question="Q2")

    records = run_retrieval_eval(
        questions, search_fn=lambda text: fake[by_text[text]], label="t"
    )
    assert [r["id"] for r in records] == ["q1", "q2"]
    assert "context" not in records[0]["retrieved"][0]  # 결과 파일에는 본문을 안 남긴다

    s = summarize_retrieval(records)
    assert s["source_hit"] == (1.0, 2, 2)
    assert s["evidence_expected"] == (0.5, 1, 2)  # q2는 b.md 청크에 Redis가 없음
    assert s["evidence_any"] == (1.0, 2, 2)
    assert s["short_chunks"] == (0.5, 2, 4)

    meta = {
        "label": "t", "started_at": "now", "git_commit": "abc", "git_dirty_src": False,
        "vault": "data/eval_corpus/docs-20261028", "collection": "mala_eval_docs",
        "rag_top_k": 2, "rag_rerank": "off", "embed_model": "nomic-embed-text",
        "questions_file": "eval/questions.yaml",
    }
    md = render_retrieval_markdown(meta, s, records)
    assert "TOP_K: 2, rerank: off" in md
    assert "볼트: data/eval_corpus/docs-20261028, 컬렉션: mala_eval_docs" in md
    assert "| q2 | O | X | 2 | b.md:24, c.md:300 |" in md


def test_search_error_is_recorded_and_run_continues():
    def boom(text):
        raise RuntimeError("Ollama down")

    records = run_retrieval_eval([Q], search_fn=boom, label="t")
    assert records[0]["error"] == "Ollama down"
    assert records[0]["source_hit"] is False
    assert summarize_retrieval(records)["errors"] == 1


# --- must_include 다른 표기 (라벨 v2) -----------------------------------------


def test_must_include_alternatives_in_answer_and_chunk():
    from src.eval.runner import auto_verdict

    q = Question("q7", "?", "in_notes", ["a.md"], [["7559", "7,559"], "MiB"])
    assert auto_verdict(q, "peak는 7,559 MiB") is True
    assert auto_verdict(q, "peak는 7559") is False  # 두 번째 항목(MiB)이 없음
    assert evidence_ranks(q, [_chunk("a.md", "7,559 mib")]) == (1, 1)


def test_load_questions_reads_old_and_new_must_include(tmp_path):
    from src.eval.runner import load_questions

    p = tmp_path / "q.yaml"
    p.write_text(
        "- {id: a, question: '?', type: in_notes, expected_sources: [x.md], must_include: [Redis]}\n"
        "- {id: b, question: '?', type: in_notes, expected_sources: [x.md],"
        " must_include: [[총 파라미터, total param], MoE]}\n",
        encoding="utf-8",
    )
    a, b = load_questions(p)
    assert a.must_include == ["Redis"]
    assert b.must_include == [["총 파라미터", "total param"], "MoE"]


@pytest.mark.parametrize("bad", ["[[]]", "[['']]", "[{x: 1}]", "[null]"])
def test_load_questions_rejects_bad_must_include(tmp_path, bad):
    from src.eval.runner import load_questions

    p = tmp_path / "q.yaml"
    p.write_text(
        f"- {{id: a, question: '?', type: in_notes, expected_sources: [x.md], must_include: {bad}}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must_include"):
        load_questions(p)

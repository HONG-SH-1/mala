"""0단계 평가 러너 — Ollama, Redis, Chroma 없이 가짜로 확인한다.

마지막 두 테스트는 실제 LangGraph 그래프(build_graph)를 그대로 통과시킨다.
바깥 연결(Redis 상태 저장, 벡터 검색, Ollama)만 가짜로 바꾼다.
"""

from pathlib import Path

import pytest

from src.agents import graph as graph_mod
from src.agents import nodes as nodes_mod
from src.config import get_settings
from src.eval.runner import (
    Question,
    auto_verdict,
    default_run_fn,
    load_questions,
    recording_ollama,
    render_markdown,
    run_eval,
    source_hit,
    strip_think,
    summarize,
)
from src.retrieval.chroma_store import SearchHit

EXAMPLE = Path(__file__).resolve().parents[1] / "eval" / "questions.example.yaml"


# --- 질문 파일 -------------------------------------------------------------


def test_example_file_loads():
    qs = load_questions(EXAMPLE)
    assert [q.id for q in qs] == ["q01", "q02", "q03", "q04"]
    assert qs[-1].type == "not_in_notes"


def test_load_reports_all_errors_at_once(tmp_path):
    bad = tmp_path / "q.yaml"
    bad.write_text(
        "- {id: a, question: x, type: in_notes}\n"
        "- {id: a, question: y, type: not_in_notes}\n"
        "- {id: b, question: z, type: maybe}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as e:
        load_questions(bad)
    msg = str(e.value)
    assert "expected_sources" in msg
    assert "중복" in msg
    assert "type" in msg


# --- 판정 ------------------------------------------------------------------


def test_strip_think_removes_reasoning():
    assert strip_think("<think>음...</think>\n답은 SHA-256") == "답은 SHA-256"


def test_source_hit_handles_windows_paths_and_folders():
    assert source_hit(["Phase-3-RAG.md"], ["notes\\Phase-3-RAG.md"])
    assert source_hit(["notes/Phase-3-RAG.md"], ["Notes/phase-3-rag.md"])
    assert not source_hit(["Phase-3-RAG.md"], ["Phase-2-Agent.md"])
    # 이름 일부만 같은 다른 파일은 맞다고 보지 않는다
    assert not source_hit(["RAG.md"], ["Phase-3-RAG.md"])


def test_auto_verdict():
    q_in = Question("q", "?", "in_notes", ["a.md"], ["SHA-256", "manifest"])
    assert auto_verdict(q_in, "sha-256 해시를 manifest에 저장") is True
    assert auto_verdict(q_in, "SHA-256만 언급") is False

    q_manual = Question("q", "?", "in_notes", ["a.md"], [])
    assert auto_verdict(q_manual, "아무 답") is None

    q_out = Question("q", "?", "not_in_notes")
    assert auto_verdict(q_out, "노트에 그 내용은 나와 있지 않습니다.") is True
    assert auto_verdict(q_out, "월 20달러 요금제를 씁니다.") is False


# --- 기록기 ----------------------------------------------------------------


def test_recording_restores_original_even_on_error():
    original = nodes_mod.call_ollama
    with pytest.raises(RuntimeError):
        with recording_ollama(lambda p, s: {}):
            assert nodes_mod.call_ollama is not original
            raise RuntimeError("boom")
    assert nodes_mod.call_ollama is original


# --- 실제 그래프 통과 -------------------------------------------------------


class _NoOpStore:
    def __init__(self, *a, **k):
        pass

    def update(self, task_id, fields):
        pass


class _NoOpBroker:
    def __init__(self, *a, **k):
        pass


class _FakeRetriever:
    def __init__(self, *a, **k):
        pass

    def search(self, query, top_k=None):
        return [
            SearchHit("c1", "notes\\Phase-3-RAG.md", "Incremental index", "SHA-256 ...", 0.1),
            SearchHit("c2", "Phase-2-Agent.md", "Workflow", "route ...", 0.4),
        ]

    def format_context(self, hits):
        return "ctx"

    def hits_to_chunks(self, hits):
        return [
            {"id": h.chunk_id, "source": h.source, "heading": h.heading, "text": h.text}
            for h in hits
        ]


@pytest.fixture
def offline_graph(monkeypatch):
    monkeypatch.setattr(graph_mod, "TaskStatusStore", _NoOpStore)
    monkeypatch.setattr(graph_mod, "RedisBroker", _NoOpBroker)
    monkeypatch.setattr(nodes_mod, "VaultRetriever", _FakeRetriever)
    return default_run_fn(get_settings())


def _fake_ollama(replies):
    it = iter(replies)

    def _call(prompt, settings):
        assert "SHA-256" in prompt  # 검색한 노트 조각이 프롬프트에 들어갔는지
        return {
            "response": next(it),
            "prompt_eval_count": 300,
            "eval_count": 40,
            "total_duration": 2_000_000_000,
            "load_duration": 500_000_000,
        }

    return _call


def test_end_to_end_records_tokens_sources_and_verdict(offline_graph):
    q = Question("q02", "바뀐 파일만 고르는 법?", "in_notes", ["Phase-3-RAG.md"], ["SHA-256"])
    records = run_eval(
        [q],
        run_fn=offline_graph,
        label="test",
        inner_ollama=_fake_ollama(["<think>생각</think>파일마다 SHA-256을 비교합니다."]),
    )
    r = records[0]
    assert r["valid"] is True
    assert r["answer"] == "파일마다 SHA-256을 비교합니다."
    assert r["had_think_block"] is True
    assert r["source_hit"] is True
    assert r["auto_correct"] is True
    assert r["ollama_calls"] == 1
    assert (r["prompt_tokens"], r["output_tokens"]) == (300, 40)
    assert (r["ollama_total_ms"], r["load_ms"]) == (2000, 500)
    assert r["history"][0] == "route:needs_context:study"


def test_retry_is_counted_and_summary_shows_it(offline_graph):
    q = Question("q03", "짧은 답이면?", "in_notes", ["Phase-2-Agent.md"], ["재시도"])
    out = Question("q04", "요금제?", "not_in_notes")
    records = run_eval(
        [q, out],
        run_fn=offline_graph,
        label="test",
        repeat=2,
        # q03: 너무 짧아 검증 실패 → 재시도에서 통과. q04: 모른다고 답함.
        inner_ollama=_fake_ollama(
            ["짧음", "검증에 실패하면 재시도합니다.", "노트에 없는 내용입니다. 모르겠습니다.",
             "검증에 실패하면 재시도합니다.", "그런 정보가 없습니다."]
        ),
    )
    first = {r["id"]: r for r in records if r["repeat"] == 1}
    assert first["q03"]["ollama_calls"] == 2
    assert first["q03"]["output_tokens"] == 80
    assert first["q04"]["source_hit"] is None

    s = summarize(records)
    assert s["questions"] == 2 and s["repeats"] == 2
    assert s["retried_questions"] == 1
    assert s["auto_correct_rate"] == 1.0
    assert s["same_verdict_rate"] == 1.0
    assert s["same_answer_text_rate"] == 0.5  # q04 답이 1회차와 2회차에 다름

    md = render_markdown(
        {"label": "test", "started_at": "now", "git_commit": "abc", "git_dirty_src": False,
         "answer_model": "m", "embed_model": "e", "rag_top_k": 5},
        s,
        records,
    )
    assert "| q03 | in_notes | O | O |" in md


# --- Ollama 버전·digest (fix-later 19번) ---------------------------------------

import httpx  # noqa: E402

from src.eval.runner import UNKNOWN, ollama_info, render_retrieval_markdown  # noqa: E402


def _ollama(handler):
    from dataclasses import replace

    from src.config import get_settings

    s = replace(get_settings(), ollama_model="qwen3:8b", ollama_embed_model="nomic-embed-text")
    return ollama_info(s, transport=httpx.MockTransport(handler))


def test_ollama_info_reads_version_and_digests():
    def handler(req):
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.13"})
        return httpx.Response(
            200,
            json={"models": [
                {"name": "qwen3:8b", "digest": "aaa111"},
                {"name": "nomic-embed-text:latest", "digest": "bbb222"},  # 태그 없는 설정값과 맞춘다
            ]},
        )

    assert _ollama(handler) == {"version": "0.40.13", "answer_digest": "aaa111", "embed_digest": "bbb222"}


def test_ollama_info_missing_model_is_unknown():
    def handler(req):
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.13"})
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "digest": "aaa111"}]})

    assert _ollama(handler)["embed_digest"] == UNKNOWN


def test_ollama_info_connection_failure_is_unknown():
    def handler(req):
        raise httpx.ConnectError("refused")

    assert _ollama(handler) == {"version": UNKNOWN, "answer_digest": UNKNOWN, "embed_digest": UNKNOWN}


def test_retrieval_header_shows_ollama_and_prefix():
    meta = {
        "label": "t", "started_at": "now", "git_commit": "abc", "git_dirty_src": False,
        "vault": "v", "collection": "c", "rag_top_k": 3, "rag_rerank": "keyword",
        "embed_model": "nomic-embed-text", "questions_file": "q.yaml", "questions_sha8": "x",
        "embed_prefix": "nomic",
        "ollama": {"version": "0.40.13", "answer_digest": UNKNOWN, "embed_digest": "sha256:0123456789abcdef"},
    }
    summary = {k: (None, 0, 0) for k in ("evidence_expected", "evidence_any", "source_hit", "short_chunks")}
    md = render_retrieval_markdown(meta, {**summary, "questions": 0, "errors": 0}, [])
    assert "- Ollama: 0.40.13, digest: 답변 알 수 없음, 임베딩 0123456789ab, 임베딩 접두어: nomic" in md

"""재채점 스크립트 — 가짜 결과 jsonl로 확인한다. 모델, Redis, Chroma 없음."""

import json

import pytest

from src.eval.runner import Question
from src.scripts import eval_rescore
from src.scripts.eval_rescore import load_manual, rescore, summarize_rescored


def _rec(qid, qtype, repeat, answer, sources=(), manual=None):
    return {
        "label": "t",
        "repeat": repeat,
        "id": qid,
        "type": qtype,
        "question": "?",
        "answer": answer,
        "valid": True,
        "had_think_block": False,
        "retrieved_sources": list(sources),
        "source_hit": None,
        "auto_correct": None,
        "manual_correct": manual,
        "ollama_calls": 1,
        "prompt_tokens": 10,
        "output_tokens": 5,
        "wall_ms": 100,
    }


QUESTIONS = [
    Question("q1", "?", "in_notes", ["a.md", "b.md"], ["Ollama"]),
    Question("q2", "?", "not_in_notes"),
]

RECORDS = [
    _rec("q1", "in_notes", 1, "Ollama입니다", ["b.md"]),
    _rec("q2", "not_in_notes", 1, "모르겠습니다"),
    _rec("q1", "in_notes", 2, "Ollama라는 말은 있지만 확인할 수 없습니다", ["c.md"]),
    _rec("q2", "not_in_notes", 2, "추정값은 9GB입니다"),
]


def test_rescore_recomputes_from_question_file():
    out = rescore(RECORDS, QUESTIONS)
    # 질문 파일의 두 번째 출처(b.md)로도 출처 일치가 잡힌다.
    assert [r["source_hit"] for r in out] == [True, None, False, None]
    assert [r["auto_correct"] for r in out] == [True, True, True, False]
    assert [r["correct"] for r in out] == [True, True, True, False]


def test_manual_overrides_auto_per_repeat():
    out = rescore(RECORDS, QUESTIONS, {"q1": [True, False], "q2": [True]})
    assert [r["manual_correct"] for r in out] == [True, True, False, True]
    assert [r["correct"] for r in out] == [True, True, False, True]

    s = summarize_rescored(out)
    assert s["auto_correct_rate"] == 1.0  # 1회차 자동 판정은 그대로
    assert s["final_all_repeats_rate"] == 0.75
    assert s["manual_changed"] == 2
    assert s["final_same_verdict_rate"] == 0.5


def test_manual_in_jsonl_is_kept_when_no_manual_file():
    records = [_rec("q2", "not_in_notes", 1, "모르겠습니다", manual=False)]
    out = rescore(records, QUESTIONS)
    assert out[0]["auto_correct"] is True
    assert out[0]["correct"] is False


def test_rescore_does_not_change_input_records():
    before = json.dumps(RECORDS, sort_keys=True)
    rescore(RECORDS, QUESTIONS, {"q1": [False]})
    assert json.dumps(RECORDS, sort_keys=True) == before


def test_rescore_rejects_mismatched_ids_and_repeat_count():
    with pytest.raises(ValueError) as e:
        rescore(RECORDS, QUESTIONS[:1], {"q9": [True], "q1": [True, True, True]})
    msg = str(e.value)
    assert "q2: 질문 파일에 없는 id" in msg
    assert "q9: 결과에 없는 id" in msg
    assert "q1: 회차별 판정이 3개" in msg


def test_load_manual_rejects_non_bool(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("q1: O\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_manual(p)


def test_main_writes_rescored_files_and_keeps_original(tmp_path):
    results = tmp_path / "run.jsonl"
    results.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in RECORDS), encoding="utf-8"
    )
    original = results.read_bytes()
    questions = tmp_path / "q.yaml"
    questions.write_text(
        "- {id: q1, question: '?', type: in_notes, expected_sources: [a.md, b.md], "
        "must_include: [Ollama]}\n"
        "- {id: q2, question: '?', type: not_in_notes}\n",
        encoding="utf-8",
    )
    manual = tmp_path / "m.yaml"
    manual.write_text("q1: [true, false]\n", encoding="utf-8")

    rc = eval_rescore.main(
        [str(results), "--questions", str(questions), "--manual", str(manual)]
    )

    assert rc == 0
    assert results.read_bytes() == original
    rows = [
        json.loads(line)
        for line in (tmp_path / "run_rescored.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [r["correct"] for r in rows] == [True, True, False, False]
    md = (tmp_path / "run_rescored.md").read_text(encoding="utf-8")
    assert "| q1 | in_notes | O | O/O | O/X | O/X |" in md


def test_main_suffix_keeps_earlier_rescore(tmp_path):
    results = tmp_path / "run.jsonl"
    results.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in RECORDS), encoding="utf-8"
    )
    questions = tmp_path / "q.yaml"
    questions.write_text(
        "- {id: q1, question: '?', type: in_notes, expected_sources: [a.md], "
        "must_include: [[Ollama, vLLM]]}\n"
        "- {id: q2, question: '?', type: not_in_notes}\n",
        encoding="utf-8",
    )
    old = tmp_path / "run_rescored.md"
    old.write_text("v1", encoding="utf-8")

    rc = eval_rescore.main([str(results), "--questions", str(questions), "--suffix", "_rescored-v2"])

    assert rc == 0
    assert old.read_text(encoding="utf-8") == "v1"
    md = (tmp_path / "run_rescored-v2.md").read_text(encoding="utf-8")
    assert "sha256 " in md and "sha256 -" not in md

"""정답을 아는 교란 답(합성): 기계적으로 만들고, 정답이 확실한 것만 쓰고, 공식 평가와 분리한다."""

import json
import random
from pathlib import Path

import pytest

import src.scripts.eval_synth as es
from src.eval.judge_guard import check_external_judges
from src.eval.judge_report import DEFAULT_CORPUS
from src.eval.runner import Question
from src.eval.synth import CONTROL, PERTURBED, SWAPS, build_synthetic, perturb, wrong_value

ROOT = Path(__file__).resolve().parents[1]


def q(qid, must, qtype="in_notes", sources=("a.md",)):
    return Question(qid, f"질문 {qid}", qtype, list(sources) if qtype == "in_notes" else [], must)


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.md").write_text("Ollama 를 쓴다. 포트는 6379 이다. CPU 는 5600X.\n", encoding="utf-8")
    return d


def rec(qid, answer, label="L", repeat=1, correct=True):
    return {"label": label, "id": qid, "repeat": repeat, "question": f"질문 {qid}", "answer": answer, "auto_correct": correct,
            "correct": correct, "retrieved_sources": ["a.md"]}


# ---- 틀린 값 ---------------------------------------------------------------------------------


def test_wrong_value_table_and_numbers():
    assert wrong_value("Ollama") == "vLLM" and wrong_value("5600X") == "7800X3D" and wrong_value("키워드 폴백") == "BM25 폴백"
    for n in ("7559", "7,559", "31.9", "6379", "1", "9", "0"):
        w = wrong_value(n)
        assert w and w != n and w[0] != n[0] and w[1:] == n[1:]  # 첫 자리만 다른 수로
    assert wrong_value("처음 보는 말") is None  # 치환표에도 없고 숫자도 아니면 쓰지 않는다
    assert "2026-05-19" not in SWAPS and "yyyy-mm-dd" not in SWAPS  # 다른 표기로 또 말할 수 있는 날짜, 형식은 뺐다


def test_wrong_values_never_equal_the_original_value():
    for k, v in SWAPS.items():
        assert v.lower() != k.lower()


# ---- 교란 -----------------------------------------------------------------------------------


def test_perturb_replaces_every_occurrence_and_leaves_no_original():
    rng = random.Random(1)
    new, replaced = perturb("Ollama 는 좋다. ollama 와 OLLAMA 를 쓴다.", ["Ollama"], "문서", rng)
    assert replaced == [["Ollama", "vLLM"]] and "ollama" not in new.lower() and new.count("vLLM") == 3


def test_perturb_handles_alternative_spellings_together():
    new, replaced = perturb("포트는 7,559 이고 7559 라고도 쓴다.", [["7559", "7,559"]], "문서", random.Random(1))
    assert "7559" not in new and "7,559" not in new and sorted(r[0] for r in replaced) == ["7,559", "7559"]


@pytest.mark.parametrize("answer,must,docs", [
    ("키워드가 답에 없다", ["Ollama"], "문서"),                      # 필수 사실이 답에 없음
    ("Ollama 를 쓴다", ["Ollama"], "문서에 vllm 이 있다"),           # 틀린 값이 근거 문서에 있음: 우연히 맞는 값이 될 수 있다
    ("처음 보는 말 이 필요", ["처음 보는 말"], "문서"),               # 치환표에 없음
])
def test_perturb_refuses_when_the_truth_would_not_be_certain(answer, must, docs):
    assert perturb(answer, must, docs, random.Random(1)) is None


def test_perturb_changes_only_one_required_fact_of_several():
    new, replaced = perturb("retrieve 다음 validate 한다", ["retrieve", "validate"], "문서", random.Random(2))
    assert len(replaced) == 1
    kept = {"retrieve", "validate"} - {replaced[0][0]}
    assert all(k in new for k in kept)


# ---- 만들기 -------------------------------------------------------------------------------------


QS = [q("q01", ["Ollama"]), q("q02", ["5600X"]), q("q03", ["Redis"]), q("q04", [], qtype="not_in_notes")]


def records():
    out = []
    for i in range(1, 4):
        out += [rec("q01", f"Ollama {i} 를 쓴다", repeat=i), rec("q02", f"CPU 는 5600X {i}", repeat=i), rec("q03", f"Redis {i} 큐", repeat=i)]
    out.append(rec("q04", "모른다", repeat=1))
    out.append(rec("q01", "Ollama 인데 틀린 답", repeat=9, correct=False))
    return out


def test_build_synthetic_uses_only_correct_in_notes_answers_and_labels_truth(corpus):
    rows = build_synthetic(records(), QS, corpus, n_perturbed=6, n_controls=0, seed=3)
    assert len(rows) == 6 and {r["label"] for r in rows} == {PERTURBED}
    for r in rows:
        assert r["correct"] is False and r["auto_correct"] is False and r["type"] == "in_notes"
        assert r["id"] in ("q01", "q02", "q03")  # not_in_notes와 원래 틀린 답은 쓰지 않는다
        assert r["synthetic"]["kind"] == "perturbed" and r["synthetic"]["replaced"] and r["synthetic"]["origin"].startswith("L|")
        orig = {"q01": "ollama", "q02": "5600x", "q03": "redis"}[r["id"]]
        assert orig not in r["answer"].lower()  # 원래 값이 하나도 안 남았다
        assert r["synthetic"]["replaced"][0][1].lower() in r["answer"].lower()


def test_questions_are_spread_and_keys_are_unique(corpus):
    rows = build_synthetic(records(), QS, corpus, n_perturbed=6, n_controls=0, seed=3)
    keys = [f"{r['label']}|{r['id']}|{r['repeat']}" for r in rows]
    assert len(set(keys)) == len(keys)
    per_q = {}
    for r in rows:
        per_q[r["id"]] = per_q.get(r["id"], 0) + 1
    assert max(per_q.values()) - min(per_q.values()) <= 1  # 질문을 돌아가며 뽑는다


def test_deterministic_for_the_same_seed_and_different_for_another(corpus):
    a = build_synthetic(records(), QS, corpus, n_perturbed=5, n_controls=0, seed=3)
    assert a == build_synthetic(records(), QS, corpus, n_perturbed=5, n_controls=0, seed=3)
    assert a != build_synthetic(records(), QS, corpus, n_perturbed=5, n_controls=0, seed=4)


def test_controls_only_from_human_blind_passes(corpus):
    recs = records()
    passed = {"L|q01|2", "L|q02|1", "L|q01|9"}  # q01|9 는 원래 correct=False라 통제로 못 쓴다
    rows = build_synthetic(recs, QS, corpus, human_blind_pass=passed, n_perturbed=0, n_controls=5, seed=3)
    assert {r["label"] for r in rows} == {CONTROL} and len(rows) == 2
    for r in rows:
        assert r["correct"] is True and r["synthetic"]["kind"] == "control" and "replaced" not in r["synthetic"]
    assert build_synthetic(recs, QS, corpus, n_perturbed=0, n_controls=5, seed=3) == []  # 사람 판정이 없으면 통제 답은 없다


def test_fewer_perturbed_than_requested_when_conditions_cannot_be_met(corpus):
    only_unknown = [rec("q01", "아무 말", repeat=1)]
    assert build_synthetic(only_unknown, QS, corpus, n_perturbed=5, n_controls=0) == []


# ---- 파일, 안전장치 ---------------------------------------------------------------------------------


def make_sources(tmp_path, collection="mala_eval_docs"):
    res = tmp_path / "res"
    res.mkdir()
    f = res / "docs-run_rescored-v2.jsonl"
    f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records()), encoding="utf-8")
    (res / "docs-run.md").write_text(f"- 볼트: data/eval_corpus/x, 컬렉션: {collection}\n", encoding="utf-8")
    qf = tmp_path / "q.yaml"
    qf.write_text("".join(f"- id: {x.id}\n  question: \"{x.question}\"\n  type: {x.type}\n  expected_sources: {json.dumps(x.expected_sources)}\n"
                          f"  must_include: {json.dumps(x.must_include, ensure_ascii=False)}\n" for x in QS), encoding="utf-8")
    return f, qf


def test_make_writes_separate_files_that_pass_the_public_docs_guard(tmp_path, corpus):
    src, qf = make_sources(tmp_path)
    before = src.read_bytes()
    out = tmp_path / "synthetic"
    jsonl, p, c = es.make("s1", [str(src)], str(qf), None, 5, 0, 3, out_dir=out, root=tmp_path, corpus_dir=corpus)
    assert jsonl == out / "s1_rescored-v2.jsonl" and p == 5 and c == 0
    md = (out / "s1.md").read_text(encoding="utf-8")
    assert "컬렉션: mala_eval_docs" in md and "공식 평가가 아님" in md
    check_external_judges([str(jsonl)], ["claude", "codex", "gemini"], tmp_path)  # 이 파일이 면접관 도구의 안전장치를 통과한다
    assert src.read_bytes() == before  # 원래 결과는 그대로
    assert ROOT.joinpath("eval", "results") not in jsonl.parents  # 공식 결과 폴더에 쓰지 않는다


def test_make_refuses_sources_that_are_not_public_docs(tmp_path, corpus):
    src, qf = make_sources(tmp_path, collection="mala_vault")
    with pytest.raises(SystemExit) as ei:
        es.make("s2", [str(src)], str(qf), None, 5, 0, 3, out_dir=tmp_path / "o", root=tmp_path, corpus_dir=corpus)
    assert "합성하지 않습니다" in str(ei.value) and not (tmp_path / "o").exists()


def test_default_output_is_under_ignored_data_dir():
    assert es.SYNTH_DIR == ROOT / "data" / "eval" / "synthetic"


# ---- 실제 데이터로 한 번 (사본이 있을 때만) -------------------------------------------------------------


@pytest.mark.skipif(not DEFAULT_CORPUS.is_dir() or not (ROOT / es.DEFAULT_FROM[0]).is_file(), reason="평가용 사본이 없으면 건너뜀")
def test_real_data_gives_certain_perturbations(tmp_path):
    jsonl, p, c = es.make("real", [str(ROOT / f) for f in es.DEFAULT_FROM], str(ROOT / "eval" / "questions.yaml"), None, 20, 0, 11,
                          out_dir=tmp_path / "o")
    assert 15 <= p <= 20 and c == 0  # 조건을 만족하는 답이 모자라면 요청보다 적게 나온다 (날짜, 형식 항목은 정답이 불확실해 뺐다)
    from src.eval.runner import load_questions

    by_q = {x.id: x for x in load_questions(ROOT / "eval" / "questions.yaml")}
    rows = [json.loads(ln) for ln in jsonl.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        group_alts = [a for rep in r["synthetic"]["replaced"] for a in rep[:1]]
        assert not any(a.lower() in r["answer"].lower() for a in group_alts)  # 원래 값이 남지 않음
        docs = "\n".join((DEFAULT_CORPUS / s).read_text(encoding="utf-8").lower() for s in by_q[r["id"]].expected_sources)
        assert not any(rep[1].lower() in docs for rep in r["synthetic"]["replaced"])  # 틀린 값이 근거 문서에 없음
        assert r["correct"] is False

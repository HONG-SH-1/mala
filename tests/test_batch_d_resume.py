"""배치 D (정확성 1~4): 이어하기.

1. 실행 때 질문 파일, 채점 지시문의 지문을 남기고 다르면 멈춘다.
2. run.json에 모델이 없어도(창을 닫아 끝난 실행) 판정 파일의 model_requested로 모델을 고정한다.
3. 판정 파일 마지막 줄이 쓰다 만 상태여도 실행 전체가 죽지 않는다.
4. 형식 오류는 판정불가로 두고 이어하기에서 다시 돈다.
가짜 면접관만 쓴다 (실제 claude, codex, gemini 호출 없음).
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from src.eval import judge
from src.eval.judge import (
    JUDGE_INSTRUCTION,
    UNAVAILABLE,
    CallError,
    CallResult,
    JudgeSpec,
    RetryLog,
    build_items,
    execute,
    input_fingerprint,
    load_rows,
    parse_row,
    pending_counts,
    pinned_model,
    reconcile,
    run_judge,
    verify_inputs,
)
from src.eval.runner import Question
from src.scripts import eval_judge as ej

OK = '{"verdict":"합격","reason":"맞게 답함","cause":"없음"}'
NOW = lambda: datetime(2026, 11, 7, 12, 0, 0)  # noqa: E731


def make_items(n=4):
    qs, recs = [], []
    for i in range(n):
        qid = f"q{i:02d}"
        qs.append(Question(qid, f"질문{i}", "in_notes", ["a.md"], ["kw"]))
        recs.append({"label": "A", "id": qid, "repeat": 1, "answer": f"답{i}", "auto_correct": True, "correct": True})
    return build_items(recs, qs)


class FakeJudge:
    def __init__(self, name="fake", model="m1", script=(OK,)):
        self.name, self.model, self.script, self.calls = name, model, list(script), []

    def call(self, prompt):
        self.calls.append(prompt)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, CallError):
            raise step
        return CallResult(text=step, model=self.model)


def log_for(tmp_path):
    return RetryLog(tmp_path / "retries.log", NOW)


# ---- 정확성 1: 지문 ---------------------------------------------------------------------------------------------------


def test_fingerprint_changes_with_the_questions_and_ignores_line_endings(tmp_path):
    q = tmp_path / "q.yaml"
    q.write_bytes("- id: q00\n  question: 질문\n".encode("utf-8"))
    a = input_fingerprint(q)
    q.write_bytes("- id: q00\r\n  question: 질문\r\n".encode("utf-8"))  # 체크아웃 줄바꿈만 다름
    assert input_fingerprint(q) == a
    q.write_bytes("- id: q00\n  question: 질문2\n".encode("utf-8"))
    assert input_fingerprint(q)["questions_sha"] != a["questions_sha"]
    assert input_fingerprint(q)["instruction_sha"] == a["instruction_sha"] and len(a["instruction_sha"]) == 12
    assert input_fingerprint(tmp_path / "없음.yaml")["questions_sha"] is None


def test_verify_inputs_passes_when_same_and_stops_when_different(tmp_path, monkeypatch):
    q = tmp_path / "q.yaml"
    q.write_text("- id: q00\n", encoding="utf-8")
    meta = {"questions": str(q), **input_fingerprint(q)}
    assert verify_inputs(meta) is None
    q.write_text("- id: q00\n  label: 바뀜\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        verify_inputs(meta)
    assert "질문 파일" in str(ei.value) and "새 실행" in str(ei.value)
    q.write_text("- id: q00\n", encoding="utf-8")
    assert verify_inputs(meta) is None  # 되돌리면 다시 통과
    monkeypatch.setattr(judge, "JUDGE_INSTRUCTION", JUDGE_INSTRUCTION + " (고침)")
    with pytest.raises(SystemExit) as ei:
        verify_inputs(meta)
    assert "채점 지시문" in str(ei.value)


def test_verify_inputs_stops_when_the_question_file_cannot_be_read(tmp_path):
    q = tmp_path / "q.yaml"
    q.write_text("x\n", encoding="utf-8")
    meta = {"questions": str(q), **input_fingerprint(q)}
    q.unlink()
    with pytest.raises(SystemExit):
        verify_inputs(meta)


def test_old_folder_without_fingerprint_only_warns(tmp_path):
    msg = verify_inputs({"questions": str(tmp_path / "q.yaml")})
    assert msg and "지문이 없어" in msg


def make_folder(tmp_path, *, fingerprint=True, judges=("claude",), with_files_sha=True):
    qfile = tmp_path / "q.yaml"
    qfile.write_text("".join(f"- id: q0{i}\n  question: 질문{i}\n  type: in_notes\n  expected_sources: [a.md]\n  must_include: [kw]\n"
                             for i in range(3)), encoding="utf-8")
    rec = tmp_path / "docs-run_rescored-v2.jsonl"
    rec.write_text("".join(json.dumps({"label": "L", "id": f"q0{i}", "repeat": 1, "answer": f"답{i}", "auto_correct": True, "correct": True}) + "\n"
                           for i in range(3)), encoding="utf-8")
    (tmp_path / "docs-run.md").write_text("- 볼트: data/eval_corpus/x, 컬렉션: mala_eval_docs\n", encoding="utf-8")
    folder = tmp_path / "judge" / "20261121-1000_t"
    folder.mkdir(parents=True)
    meta = {"files": [str(rec)], "judges": list(judges), "seed": 3, "limit": None, "questions": str(qfile)}
    if fingerprint:
        meta.update(input_fingerprint(qfile, [str(rec)]))
        if not with_files_sha:
            meta.pop("files_sha")  # 결과 파일 지문이 생기기 전 형식
    (folder / "inputs.json").write_text(json.dumps(meta), encoding="utf-8")
    items = ej.shuffle_items(ej.build_items(ej.load_records(str(rec)), ej.load_questions(str(qfile))), 3)
    specs = [JudgeSpec(n, [None], lambda m, n=n: FakeJudge(n, "m", [OK]), ping=False) for n in judges]
    execute(specs, items, folder, seed=3, sleep=lambda s: None, now=NOW)
    return folder, qfile, tmp_path


def boom_specs(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("지문이 다르면 면접관을 만들기 전에 멈춰야 한다")

    monkeypatch.setattr(ej, "_build_specs", boom)
    monkeypatch.setattr(ej, "load_dotenv", lambda *a, **k: None)


@pytest.mark.parametrize("flag", ["--resume", "--rebuild"])
def test_changed_question_file_stops_resume_and_rebuild(tmp_path, monkeypatch, flag):
    folder, qfile, _ = make_folder(tmp_path)
    boom_specs(monkeypatch)
    before = sorted((p.name, p.stat().st_size) for p in folder.iterdir())
    qfile.write_text(qfile.read_text(encoding="utf-8").replace("질문0", "질문0 (라벨 바꿈)"), encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        ej.main([flag, str(folder)])
    assert "입력이 다릅니다" in str(ei.value)
    assert sorted((p.name, p.stat().st_size) for p in folder.iterdir()) == before  # 아무것도 안 바뀜


def test_changed_question_file_stops_debate_too(tmp_path, monkeypatch):
    folder, qfile, _ = make_folder(tmp_path, judges=("claude", "codex", "gemini"))
    boom_specs(monkeypatch)
    qfile.write_text(qfile.read_text(encoding="utf-8") + "- id: q99\n  question: 새 질문\n  type: in_notes\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        ej.main(["--debate", str(folder), "--dry-run"])
    assert not (folder / "debate").exists()


def test_unchanged_inputs_rebuild_normally(tmp_path, monkeypatch, capsys):
    folder, _q, _ = make_folder(tmp_path)
    boom_specs(monkeypatch)
    assert ej.main(["--rebuild", str(folder)]) == 0
    assert "경고" not in capsys.readouterr().err


def test_folder_without_fingerprint_warns_and_still_rebuilds(tmp_path, monkeypatch, capsys):
    folder, _q, _ = make_folder(tmp_path, fingerprint=False)
    boom_specs(monkeypatch)
    assert ej.main(["--rebuild", str(folder)]) == 0
    assert "지문이 없어" in capsys.readouterr().err


def append_row(rec, **extra):
    row = {"label": "L", "id": "q00", "repeat": 2, "answer": "바뀐 답", "auto_correct": True, "correct": True, **extra}
    with open(rec, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


@pytest.mark.parametrize("flag", ["--resume", "--rebuild"])
def test_changed_result_file_stops_resume_and_rebuild(tmp_path, monkeypatch, flag):
    folder, _q, root = make_folder(tmp_path)
    boom_specs(monkeypatch)
    before = sorted((p.name, p.stat().st_size) for p in folder.iterdir())
    append_row(root / "docs-run_rescored-v2.jsonl")  # 입력 결과 파일(답)이 바뀜
    with pytest.raises(SystemExit) as ei:
        ej.main([flag, str(folder)])
    assert "입력 결과 파일" in str(ei.value) and "docs-run_rescored-v2.jsonl" in str(ei.value)
    assert sorted((p.name, p.stat().st_size) for p in folder.iterdir()) == before


def test_changed_result_file_stops_debate(tmp_path, monkeypatch):
    folder, _q, root = make_folder(tmp_path, judges=("claude", "codex", "gemini"))
    boom_specs(monkeypatch)
    append_row(root / "docs-run_rescored-v2.jsonl")
    with pytest.raises(SystemExit):
        ej.main(["--debate", str(folder), "--dry-run"])
    assert not (folder / "debate").exists()


def test_missing_result_file_stops_too(tmp_path, monkeypatch):
    folder, _q, root = make_folder(tmp_path)
    boom_specs(monkeypatch)
    (root / "docs-run_rescored-v2.jsonl").unlink()
    with pytest.raises(SystemExit) as ei:
        ej.main(["--rebuild", str(folder)])
    assert "입력 결과 파일" in str(ei.value)


def test_result_file_line_endings_alone_do_not_stop(tmp_path, monkeypatch):
    folder, _q, root = make_folder(tmp_path)
    boom_specs(monkeypatch)
    rec = root / "docs-run_rescored-v2.jsonl"
    lf = rec.read_bytes().replace(b"\r\n", b"\n")
    for data in (lf, lf.replace(b"\n", b"\r\n")):  # 줄바꿈만 LF, CRLF로 바뀐 경우 둘 다
        rec.write_bytes(data)
        assert ej.main(["--rebuild", str(folder)]) == 0


def test_folder_whose_fingerprint_has_no_result_files_only_warns(tmp_path, monkeypatch, capsys):
    folder, _q, root = make_folder(tmp_path, with_files_sha=False)
    boom_specs(monkeypatch)
    append_row(root / "docs-run_rescored-v2.jsonl")  # 확인할 지문이 없으니 못 잡는다 (경고만)
    assert ej.main(["--rebuild", str(folder)]) == 0
    assert "입력 결과 파일이 없어" in capsys.readouterr().err


def test_new_run_saves_the_result_file_fingerprints(tmp_path, monkeypatch):
    _folder, qfile, root = make_folder(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("JUDGE_WORKDIR", str(work))
    monkeypatch.setattr(ej, "JUDGE_DIR", tmp_path / "newjudge2")
    monkeypatch.setattr(ej, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(ej, "_build_specs", lambda names, wd, rpm: ([JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "m", [OK]), ping=False)], []))
    rec = str(root / "docs-run_rescored-v2.jsonl")
    assert ej.main([rec, "--judges", "claude", "--questions", str(qfile), "--tag", "t"]) == 0
    (out,) = (tmp_path / "newjudge2").iterdir()
    meta = json.loads((out / "inputs.json").read_text(encoding="utf-8"))
    assert meta["files_sha"] == input_fingerprint(qfile, [rec])["files_sha"] and meta["files_sha"][rec]


def test_new_run_saves_the_fingerprint_in_inputs_json(tmp_path, monkeypatch):
    _folder, qfile, _ = make_folder(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("JUDGE_WORKDIR", str(work))
    monkeypatch.setattr(ej, "JUDGE_DIR", tmp_path / "newjudge")
    monkeypatch.setattr(ej, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(ej, "_build_specs", lambda names, wd, rpm: ([JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "m", [OK]), ping=False)], []))
    rec = str(tmp_path / "docs-run_rescored-v2.jsonl")
    assert ej.main([rec, "--judges", "claude", "--questions", str(qfile), "--tag", "t"]) == 0
    (out,) = (tmp_path / "newjudge").iterdir()
    meta = json.loads((out / "inputs.json").read_text(encoding="utf-8"))
    assert meta["questions_sha"] == input_fingerprint(qfile)["questions_sha"] and meta["instruction_sha"] == input_fingerprint(qfile)["instruction_sha"]


# ---- 정확성 2: 모델 고정 -----------------------------------------------------------------------------------------------


def test_pinned_model_is_the_latest_requested_model_in_the_file(tmp_path):
    p = tmp_path / "judge_codex.jsonl"
    assert pinned_model(p) is None
    rows = [{"key": "a", "verdict": "합격", "model_requested": "c1"}, {"key": "b", "verdict": "합격", "model_requested": "c2"}]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows) + '{"key": "c", "ver', encoding="utf-8")
    assert pinned_model(p) == "c2"


def test_resume_pins_the_model_from_judge_file_when_run_json_has_no_judges(tmp_path, monkeypatch):
    """창을 닫아 끝난 실행: run.json의 judges가 비어 있어도 모델을 다시 고르지 않는다."""
    items = make_items(4)
    made = []
    spec = JudgeSpec("codex", ["c1", "c2"], lambda m: made.append(m) or FakeJudge("codex", m, [OK]))
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    assert made[0] == "c1"  # 처음에는 우선순위 첫 모델
    path = tmp_path / "judge_codex.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")  # 2건만 남은 상태
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    state["judges"], state["ended"] = {}, False  # 시작 때 저장된 모양 그대로
    (tmp_path / "run.json").write_text(json.dumps(state), encoding="utf-8")

    def no_ping(*a, **k):
        raise AssertionError("모델을 다시 고르면(시작 확인 요청) 안 된다")

    monkeypatch.setattr(judge, "pick_model", no_ping)
    made2 = []
    spec2 = JudgeSpec("codex", ["c2", "c1"], lambda m: made2.append(m) or FakeJudge("codex", m, [OK]))  # 우선순위가 바뀌어도
    execute([spec2], items, tmp_path, seed=1, resume=True, sleep=lambda s: None, now=NOW)
    assert made2 == ["c1"]
    assert {r["model_requested"] for r in load_rows(path).values()} == {"c1"}
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["judges"]["codex"]["model"] == "c1"


def test_mixed_models_in_one_judge_file_warn_on_stderr_but_pinning_is_unchanged(tmp_path, monkeypatch, capsys):
    p = tmp_path / "judge_codex.jsonl"
    rows = [{"key": "a", "verdict": "합격", "model_requested": "c1"}, {"key": "b", "verdict": "합격", "model_requested": "c2"},
            {"key": "c", "verdict": "합격", "model_requested": "c1"}]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    msg = judge.mixed_models_warning("codex", p)
    assert msg and "codex" in msg and "2개" in msg and "c1" in msg and "c2" in msg
    assert pinned_model(p) == "c1"  # 고정은 그대로: 가장 나중 줄

    items = make_items(3)
    state = {"seed": 1, "judges": {}, "started": "x", "items": [it.key for it in items], "ended": False}
    (tmp_path / "run.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(judge, "pick_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("다시 고르면 안 된다")))
    made = []
    execute([JudgeSpec("codex", ["c2"], lambda m: made.append(m) or FakeJudge("codex", m, [OK]))], items, tmp_path, seed=1, resume=True,
            sleep=lambda s: None, now=NOW)
    assert made == ["c1"]
    err = capsys.readouterr().err
    assert err.count("요청 모델이 2개 섞여") == 1 and "codex" in err


def test_single_model_or_no_file_gives_no_warning(tmp_path):
    p = tmp_path / "judge_codex.jsonl"
    assert judge.mixed_models_warning("codex", p) is None
    p.write_text("".join(json.dumps({"key": k, "verdict": "합격", "model_requested": "c1"}) + "\n" for k in "ab"), encoding="utf-8")
    assert judge.mixed_models_warning("codex", p) is None


def test_no_judge_lines_yet_means_the_model_is_picked_normally(tmp_path):
    items = make_items(2)
    pinged = []

    class Pinger(FakeJudge):
        def call(self, prompt):
            if prompt == judge.PING_PROMPT:
                pinged.append(self.model)
                return CallResult("OK", self.model)
            return super().call(prompt)

    state = {"seed": 1, "judges": {}, "started": "x", "items": [it.key for it in items], "ended": False}
    (tmp_path / "run.json").write_text(json.dumps(state), encoding="utf-8")
    execute([JudgeSpec("codex", ["c1"], lambda m: Pinger("codex", m))], items, tmp_path, seed=1, resume=True, sleep=lambda s: None, now=NOW)
    assert pinged == ["c1"]


def test_claude_without_ping_keeps_model_none_in_state(tmp_path):
    items = make_items(2)
    spec = JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "haiku", [OK]), ping=False)
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    state["judges"], state["ended"] = {}, False
    (tmp_path / "run.json").write_text(json.dumps(state), encoding="utf-8")
    execute([spec], items, tmp_path, seed=1, resume=True, sleep=lambda s: None, now=NOW)
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["judges"]["claude"]["model"] is None


# ---- 정확성 3: 쓰다 만 줄 -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ['{"key": "a|q|0", "ver', "[1, 2]", "123", '"text"', "null", '{"verdict": "합격"}', '{"key": 5, "verdict": "합격"}',
                                 '{"key": "x"}', "{{", "\x00\x01"])
def test_load_rows_skips_lines_that_are_not_rows(tmp_path, bad):
    good = {"key": "k1", "verdict": "합격"}
    p = tmp_path / "j.jsonl"
    p.write_text(json.dumps(good) + "\n" + bad + "\n" + json.dumps({"key": "k2", "verdict": "불합격"}) + "\n" + bad, encoding="utf-8")
    assert list(load_rows(p)) == ["k1", "k2"]
    assert parse_row(bad) is None


def test_load_rows_survives_bytes_that_are_not_utf8(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_bytes(json.dumps({"key": "k1", "verdict": "합격"}).encode("utf-8") + b"\n" + b'{"key": "\xff\xfe')
    assert list(load_rows(p)) == ["k1"]


def test_load_rows_keeps_the_last_line_per_key(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text("".join(json.dumps({"key": "k", "verdict": v}) + "\n" for v in (UNAVAILABLE, "합격")), encoding="utf-8")
    assert load_rows(p)["k"]["verdict"] == "합격"


def test_reconcile_repairs_a_file_even_when_run_json_has_no_judges(tmp_path):
    p = tmp_path / "judge_claude.jsonl"
    p.write_text(json.dumps({"key": "a", "verdict": "합격"}) + "\n" + '{"key": "a|q|0", "ver', encoding="utf-8")
    fixed = reconcile(tmp_path, {"judges": {}, "items": ["a", "b"]})
    assert fixed == {"duplicates": 0, "broken": 1, "missing": 0}  # 상태에 없는 면접관은 '빠진 건'을 세지 않는다
    assert p.read_text(encoding="utf-8") == json.dumps({"key": "a", "verdict": "합격"}, ensure_ascii=False) + "\n"


def test_reconcile_adds_the_missing_newline_so_the_next_append_does_not_merge_lines(tmp_path):
    p = tmp_path / "judge_claude.jsonl"
    p.write_text(json.dumps({"key": "a", "verdict": "합격"}), encoding="utf-8")  # 끝 개행 없음
    reconcile(tmp_path, {"judges": {}})
    judge._append(p, {"key": "b", "verdict": "불합격"})
    assert list(load_rows(p)) == ["a", "b"] and len(p.read_text(encoding="utf-8").splitlines()) == 2


def test_resume_with_a_half_written_last_line_finishes_instead_of_crashing(tmp_path):
    """재현: 창을 닫아 끝난 실행(judges가 비어 있음) + 마지막 줄이 쓰다 만 상태 → 예전에는 JSONDecodeError로 실행 전체가 죽었다."""
    items = make_items(4)
    spec = JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "haiku", [OK]), ping=False)
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    path = tmp_path / "judge_claude.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n" + '{"key": "A|q02|1", "ver', encoding="utf-8")
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    state["judges"], state["ended"] = {}, False
    (tmp_path / "run.json").write_text(json.dumps(state), encoding="utf-8")
    again = FakeJudge("claude", "haiku", [OK])
    execute([JudgeSpec("claude", [None], lambda m: again, ping=False)], items, tmp_path, seed=1, resume=True, sleep=lambda s: None, now=NOW)
    assert len(again.calls) == 2 and len(load_rows(path)) == 4  # 남은 두 건만 다시
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["reconciled"]["broken"] == 1


# ---- 정확성 4: 형식 오류는 판정불가 ---------------------------------------------------------------------------------------


def test_format_error_is_saved_as_unavailable_with_a_reason(tmp_path):
    run_judge(FakeJudge(script=["not json"]), make_items(1), tmp_path / "j.jsonl", log=log_for(tmp_path), sleep=lambda s: None)
    (row,) = load_rows(tmp_path / "j.jsonl").values()
    assert row["verdict"] == UNAVAILABLE and row["status"] == "format_error" and "형식 오류" in row["reason"] and row["model_reported"] == "m1"


def test_format_errors_do_not_count_toward_stopping_the_judge(tmp_path):
    items = make_items(8)
    res = run_judge(FakeJudge(script=["not json"]), items, tmp_path / "j.jsonl", log=log_for(tmp_path), sleep=lambda s: None, fail_limit=3)
    assert res == {"stopped": None} and len(load_rows(tmp_path / "j.jsonl")) == 8  # 연속 3건 한도를 넘겨도 멈추지 않는다


def test_resume_calls_the_format_error_item_again_and_it_becomes_ok(tmp_path):
    items = make_items(3)
    first = FakeJudge("claude", "haiku", ["not json", OK, OK])
    spec = JudgeSpec("claude", [None], lambda m: first, ping=False)
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    rows = load_rows(tmp_path / "judge_claude.jsonl")
    assert [r["status"] for r in rows.values()].count("format_error") == 1
    assert pending_counts(tmp_path, items, ["claude"]) == {"claude": 1}  # 아직 할 일로 센다
    second = FakeJudge("claude", "haiku", [OK])
    execute([JudgeSpec("claude", [None], lambda m: second, ping=False)], items, tmp_path, seed=1, resume=True, sleep=lambda s: None, now=NOW)
    assert len(second.calls) == 1  # 형식 오류였던 한 건만
    rows = load_rows(tmp_path / "judge_claude.jsonl")
    assert all(r["status"] == "ok" and r["verdict"] == "합격" for r in rows.values())


def test_format_error_shows_up_as_unavailable_in_the_review_files(tmp_path):
    items = make_items(2)
    spec = JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "haiku", ["not json", OK]), ping=False)
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    maj = [json.loads(line) for line in (tmp_path / "majority.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(m["verdicts"]["claude"] for m in maj) == sorted([UNAVAILABLE, "합격"])
    assert "판정 불가 있음" in (tmp_path / "review.md").read_text(encoding="utf-8")

"""배치 E (정확성 5, 6): Codex 오류 분류와 시간 초과 상한. 가짜 runner, 가짜 면접관만 쓴다.

5. 분류는 stderr만 본다. --json 출력(stdout)에는 모델이 쓴 글이 섞여 "401", "login"이 나올 수 있다.
6. 시간 초과는 건당 TIMEOUT_ATTEMPTS번, 연속 TIMEOUT_FAIL_LIMIT건이면 면접관을 멈춘다 (최악 6번 호출).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime

import pytest

from src.eval import judge
from src.eval.judge import (
    TIMEOUT_ATTEMPTS,
    TIMEOUT_FAIL_LIMIT,
    UNAVAILABLE,
    CallError,
    CallResult,
    ClaudeJudge,
    CodexJudge,
    JudgeSpec,
    RetryLog,
    build_items,
    call_with_retry,
    execute,
    load_rows,
    pick_model,
    run_judge,
    _codex_error_kind,
)
from src.eval.runner import Question

OK = '{"verdict":"합격","reason":"맞게 답함","cause":"없음"}'
NOW = lambda: datetime(2026, 11, 7, 12, 0, 0)  # noqa: E731
TIMEOUT = CallError("transient", "timeout")


def make_items(n=4):
    qs, recs = [], []
    for i in range(n):
        qid = f"q{i:02d}"
        qs.append(Question(qid, f"질문{i}", "in_notes", ["a.md"], ["kw"]))
        recs.append({"label": "A", "id": qid, "repeat": 1, "answer": f"답{i}", "auto_correct": True, "correct": True})
    return build_items(recs, qs)


def log_for(tmp_path):
    return RetryLog(tmp_path / "retries.log", NOW)


class ByPrompt:
    """prompt마다 정해 둔 단계를 차례로 꺼내 쓴다. 정해 두지 않은 prompt는 성공. 모든 호출을 기록한다."""

    name, model = "fake", "m1"

    def __init__(self, plan=None, default=OK):
        self.plan, self.default, self.calls = {k: list(v) for k, v in (plan or {}).items()}, default, []

    def call(self, prompt):
        self.calls.append(prompt)
        steps = self.plan.get(prompt)
        step = (steps.pop(0) if len(steps) > 1 else steps[0]) if steps else self.default
        if isinstance(step, CallError):
            raise CallError(step.kind, step.status)
        return CallResult(text=step, model=self.model)


class AlwaysFail:
    name, model = "fake", "m1"

    def __init__(self, err):
        self.err, self.calls = err, 0

    def call(self, prompt):
        self.calls += 1
        raise CallError(self.err.kind, self.err.status)


# ---- 정확성 5: Codex 오류 분류 ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("stderr", [
    "unexpected status 401 Unauthorized: invalid token", "HTTP 403 Forbidden", "error: 401", "Unauthorized", "UNAUTHORISED",
    "You are not logged in. Run `codex login`.", "Error 401.", "status=401 body=...",
])
def test_real_auth_failures_in_stderr_are_auth(stderr):
    assert _codex_error_kind(stderr) == ("auth", "auth")


@pytest.mark.parametrize("stderr", [
    "", "connection reset by peer", "stream disconnected before completion", "rate limited, retry later",
    "please log in again later", "login server is busy", "relogin required soon", "session login refreshed",
    "request id 4012 failed", "retrying in 401ms", "src/exec/run.rs:401 panicked", "id=a401b", "version 1.401.0", "port 14010",
    "model_provider overloaded",  # model이라는 글자만으로는 모델 오류가 아니다
])
def test_other_text_is_transient_not_auth(stderr):
    assert _codex_error_kind(stderr) == ("transient", "")


@pytest.mark.parametrize("stderr", [
    "The model `gpt-x` does not exist", "model not found: gpt-x", "unknown model gpt-x", "Model gpt-x is not supported", "404 Not Found",
    "HTTP 400 Bad Request", "invalid model name",
])
def test_model_errors_are_bad(stderr):
    assert _codex_error_kind(stderr) == ("bad", "model")


def fake_run(stdout="", stderr="", rc=1):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr=stderr)


def codex_call(tmp_path, **kw):
    with pytest.raises(CallError) as ei:
        CodexJudge(tmp_path, "gpt-x", "low", runner=fake_run(**kw)).call("p")
    return ei.value


def test_401_and_login_in_stdout_only_is_a_transient_error(tmp_path):
    """재현: 출력(--json 이벤트)에 모델이 쓴 글로 "401", "login"이 있어도 일시 오류를 인증 실패로 보지 않는다."""
    events = "\n".join(json.dumps(e, ensure_ascii=False) for e in (
        {"type": "item.completed", "item": {"type": "agent_message", "text": "답에 401 이라는 숫자와 login 이라는 글자가 있다"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Unauthorized, not logged in, 403, model not found 404"}},
    ))
    exc = codex_call(tmp_path, stdout=events, stderr="stream disconnected")
    assert exc.kind == "transient" and exc.status == "exit1"
    exc = codex_call(tmp_path, stdout=events, stderr="")
    assert exc.kind == "transient"


def test_auth_failure_in_stderr_still_stops_the_judge(tmp_path):
    exc = codex_call(tmp_path, stdout="", stderr="unexpected status 401 Unauthorized")
    assert exc.kind == "auth" and exc.status == "auth"
    exc = codex_call(tmp_path, stdout="login", stderr="The model `gpt-x` does not exist")
    assert exc.kind == "bad" and exc.status == "model"


def test_transient_codex_failure_with_login_text_does_not_stop_the_run(tmp_path):
    items = make_items(3)

    class Flaky(ByPrompt):
        def call(self, prompt):
            self.calls.append(prompt)
            if len(self.calls) == 1:  # 첫 호출만 일시 오류 (출력에 login 글자)
                return CodexJudge(tmp_path, "gpt-x", "low", runner=fake_run(stdout="please login", stderr="stream error")).call(prompt)
            return CallResult(OK, "gpt-x")

    spec = JudgeSpec("codex", [None], lambda m: Flaky(), ping=False)
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert state["judges"]["codex"]["status"] == "active" and len(load_rows(tmp_path / "judge_codex.jsonl")) == 3


# ---- 정확성 6: 시간 초과 상한 ------------------------------------------------------------------------------------------


def test_the_limits_are_the_approved_numbers_and_the_worst_case_is_six_calls(tmp_path):
    assert (TIMEOUT_ATTEMPTS, TIMEOUT_FAIL_LIMIT) == (2, 3)
    worst_calls = TIMEOUT_ATTEMPTS * TIMEOUT_FAIL_LIMIT
    assert worst_calls == 6
    assert CodexJudge(tmp_path, "gpt-x", "low").timeout * worst_calls / 60 == 30  # 분 (예전 약 155분)
    assert ClaudeJudge(tmp_path).timeout * worst_calls / 60 == 18  # 분 (예전 95분)
    assert judge.RUN_ATTEMPTS * judge.CONSECUTIVE_FAIL_LIMIT == 30  # 예전 최악의 호출 수


def test_one_item_gives_up_after_two_timeouts(tmp_path):
    j = AlwaysFail(TIMEOUT)
    waits = []
    with pytest.raises(CallError) as ei:
        call_with_retry(j, "p", max_attempts=judge.RUN_ATTEMPTS, log=log_for(tmp_path), sleep=waits.append)
    assert j.calls == 2 and ei.value.attempts == 2 and ei.value.status == "timeout"
    assert waits == [2.0]  # 첫 실패 뒤에만 기다린다
    lines = (tmp_path / "retries.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0].endswith("try1\twait2") and lines[1].endswith("try2\twait0")


def test_a_timeout_then_success_is_fine(tmp_path):
    j = ByPrompt({"p": [TIMEOUT, OK]})
    res, attempts = call_with_retry(j, "p", max_attempts=6, log=log_for(tmp_path), sleep=lambda s: None)
    assert attempts == 2 and res.text == OK


def test_only_timeouts_count_toward_the_per_item_timeout_limit(tmp_path):
    j = ByPrompt({"p": [CallError("transient", 503), TIMEOUT, CallError("transient", 503), TIMEOUT]})
    with pytest.raises(CallError) as ei:
        call_with_retry(j, "p", max_attempts=6, log=log_for(tmp_path), sleep=lambda s: None)
    assert len(j.calls) == 4 and ei.value.status == "timeout"  # 503 두 번은 세지 않고, 시간 초과 두 번째에서 포기


def test_other_transient_errors_keep_the_old_six_tries(tmp_path):
    j = AlwaysFail(CallError("transient", 503))
    with pytest.raises(CallError):
        call_with_retry(j, "p", max_attempts=judge.RUN_ATTEMPTS, log=log_for(tmp_path), sleep=lambda s: None)
    assert j.calls == 6


def test_three_items_in_a_row_with_timeouts_stop_the_judge_after_six_calls(tmp_path):
    items = make_items(10)
    j = AlwaysFail(TIMEOUT)
    res = run_judge(j, items, tmp_path / "j.jsonl", log=log_for(tmp_path), sleep=lambda s: None)
    assert j.calls == 6  # 예전에는 30번
    assert "연속 3건 시간 초과" in res["stopped"] and "2번" in res["stopped"]
    rows = list(load_rows(tmp_path / "j.jsonl").values())
    assert len(rows) == 3 and all(r["verdict"] == UNAVAILABLE and r["status"] == "failed:timeout" and r["attempts"] == 2 for r in rows)


def test_a_success_resets_the_timeout_streak(tmp_path):
    items = make_items(8)
    plan = {it.prompt: [TIMEOUT] for k, it in enumerate(items) if k in (0, 1, 3, 4, 6, 7)}  # 시간 초과 2건, 성공 1건 반복
    j = ByPrompt(plan)
    res = run_judge(j, items, tmp_path / "j.jsonl", log=log_for(tmp_path), sleep=lambda s: None)
    assert res == {"stopped": None} and len(load_rows(tmp_path / "j.jsonl")) == 8


def test_another_kind_of_failure_resets_the_timeout_streak(tmp_path):
    items = make_items(5)
    plan = {items[0].prompt: [TIMEOUT], items[1].prompt: [TIMEOUT], items[2].prompt: [CallError("transient", 503)], items[3].prompt: [TIMEOUT]}
    j = ByPrompt(plan)
    res = run_judge(j, items, tmp_path / "j.jsonl", log=log_for(tmp_path), sleep=lambda s: None)
    assert res == {"stopped": None}  # T, T, 503, T, 성공: 시간 초과 3연속이 아니고 일반 실패도 4연속이라 한도(5) 미만


def test_ordinary_transient_failures_still_stop_at_five_items_and_thirty_calls(tmp_path):
    j = AlwaysFail(CallError("transient", 503))
    res = run_judge(j, make_items(10), tmp_path / "j.jsonl", log=log_for(tmp_path), sleep=lambda s: None)
    assert j.calls == 30 and res["stopped"] == "연속 5건 실패 (마지막 503)"


def test_timeout_limit_can_be_set(tmp_path):
    j = AlwaysFail(TIMEOUT)
    res = run_judge(j, make_items(10), tmp_path / "j.jsonl", log=log_for(tmp_path), sleep=lambda s: None, timeout_fail_limit=2)
    assert j.calls == 4 and "연속 2건 시간 초과" in res["stopped"]


def test_startup_check_also_gives_up_after_two_timeouts_per_model(tmp_path):
    made = []

    def make(m):
        j = AlwaysFail(TIMEOUT)
        made.append(j)
        return j

    out = pick_model(JudgeSpec("codex", ["c1", "c2"], make), log=log_for(tmp_path), sleep=lambda s: None)
    assert out["status"] == "skipped" and [j.calls for j in made] == [2, 2]  # 모델마다 3번이 아니라 2번


def test_stopped_by_timeouts_is_recorded_and_resume_finishes_the_rest(tmp_path):
    items = make_items(6)
    bad = AlwaysFail(TIMEOUT)
    execute([JudgeSpec("codex", [None], lambda m: bad, ping=False)], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert state["judges"]["codex"]["status"] == "stopped" and "연속 3건 시간 초과" in state["judges"]["codex"]["stopped"]
    assert bad.calls == 6
    good = ByPrompt()
    execute([JudgeSpec("codex", [None], lambda m: good, ping=False)], items, tmp_path, seed=1, resume=True, sleep=lambda s: None, now=NOW)
    rows = load_rows(tmp_path / "judge_codex.jsonl")
    assert len(rows) == 6 and all(r["verdict"] == "합격" for r in rows.values())
    assert len(good.calls) == 6  # 판정불가 3건과 못 돈 3건

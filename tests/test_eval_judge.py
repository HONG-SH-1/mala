"""면접관 자동화 — 실제 키, 네트워크, CLI 없이 가짜로 확인한다."""

import json
import subprocess
from datetime import datetime

import httpx
import pytest

from src.eval.judge import (
    CallError,
    CallResult,
    ClaudeJudge,
    CodexJudge,
    GeminiJudge,
    JudgeSpec,
    RateLimiter,
    RetryLog,
    build_items,
    call_with_retry,
    decide,
    execute,
    extract_codex_tokens,
    load_rows,
    parse_verdict,
    pick_model,
    run_judge,
    select_items,
)
from src.eval.runner import Question
from src.keystore import Secret

FAKE_KEY = "AQ." + "k" * 50
OK = '{"verdict":"합격","reason":"맞게 답함","cause":"없음"}'
NO = '{"verdict":"불합격","reason":"틀림","cause":"생성 오류"}'
NOW = lambda: datetime(2026, 11, 7, 12, 0, 0)  # noqa: E731


def gemini_body(text=OK, model="gemini-x-001"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}], "modelVersion": model}


def make_items(n=4, labels=("A",), types=("in_notes", "not_in_notes")):
    qs, recs = [], []
    for i in range(n):
        qid = f"q{i:02d}"
        qtype = types[i % len(types)]
        qs.append(Question(qid, f"질문{i}", qtype, ["a.md"] if qtype == "in_notes" else [], ["kw"]))
        for lab in labels:
            recs.append({"label": lab, "id": qid, "repeat": 1, "answer": f"답{i}", "auto_correct": True, "correct": True})
    return build_items(recs, qs)


class FakeJudge:
    """script: 호출마다 하나씩 꺼내 쓴다. str이면 성공 텍스트, CallError면 던진다. 다 쓰면 마지막 것을 반복."""

    def __init__(self, name="fake", model="m1", script=(OK,)):
        self.name, self.model, self.script, self.calls = name, model, list(script), []

    def call(self, prompt):
        self.calls.append(prompt)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, CallError):
            raise step
        return CallResult(text=step, model=self.model)


@pytest.fixture
def log(tmp_path):
    return RetryLog(tmp_path / "retries.log", NOW)


# ---- 재시도 ---------------------------------------------------------------


def test_503_then_success_with_backoff(tmp_path, log):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(503) if len(seen) <= 2 else httpx.Response(200, json=gemini_body())

    judge = GeminiJudge("gemini-x", Secret(FAKE_KEY), client=httpx.Client(transport=httpx.MockTransport(handler)))
    waits = []
    res, attempts = call_with_retry(judge, "p", max_attempts=6, log=log, sleep=waits.append)
    assert (attempts, waits, res.text) == (3, [2.0, 4.0], OK)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0].split("\t")[1:] == ["gemini", "gemini-x", "503", "try1", "wait2"]
    # 키는 헤더로만 간다 (URL에 없음)
    assert seen[0].headers["x-goog-api-key"] == FAKE_KEY and FAKE_KEY not in str(seen[0].url)


def test_retry_after_header_is_used(log):
    seq = iter([httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200, json=gemini_body())])
    judge = GeminiJudge("g", Secret(FAKE_KEY), client=httpx.Client(transport=httpx.MockTransport(lambda r: next(seq))))
    waits = []
    call_with_retry(judge, "p", max_attempts=6, log=log, sleep=waits.append)
    assert waits == [7.0]


def test_gives_up_after_five_retries(log):
    judge = FakeJudge(script=[CallError("transient", 503)])
    waits = []
    with pytest.raises(CallError):
        call_with_retry(judge, "p", max_attempts=6, log=log, sleep=waits.append)
    assert waits == [2, 4, 8, 16, 32] and len(judge.calls) == 6


def test_401_stops_without_retry(log):
    hits = []
    judge = GeminiJudge("g", Secret(FAKE_KEY), client=httpx.Client(transport=httpx.MockTransport(lambda r: hits.append(1) or httpx.Response(401))))
    waits = []
    with pytest.raises(CallError) as ei:
        call_with_retry(judge, "p", max_attempts=6, log=log, sleep=waits.append)
    assert ei.value.kind == "auth" and len(hits) == 1 and waits == []


def test_401_stops_that_judge_only(tmp_path):
    items = make_items(3)
    bad = FakeJudge("codex", "c1", [CallError("auth", 401)])
    good = FakeJudge("claude", "haiku", [OK])
    specs = [JudgeSpec("codex", ["c1"], lambda m: bad, ping=False), JudgeSpec("claude", [None], lambda m: good, ping=False)]
    execute(specs, items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert state["judges"]["codex"]["status"] == "stopped" and "401" in state["judges"]["codex"]["stopped"]
    assert len(bad.calls) == 1  # 재시도도, 다음 건도 안 함
    assert len(good.calls) == 3


def test_400_in_run_phase_stops_judge(tmp_path, log):
    j = FakeJudge(script=[CallError("bad", 400)])
    out = run_judge(j, make_items(3), tmp_path / "j.jsonl", log=log, sleep=lambda s: None)
    assert "400" in out["stopped"] and len(j.calls) == 1


# ---- 모델 고정 -------------------------------------------------------------


def _gemini_spec(handler, models, tmp_path=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return JudgeSpec("gemini", models, lambda m: GeminiJudge(str(m), Secret(FAKE_KEY), client=client))


def _model_of(req):
    return req.url.path.split("/models/")[1].split(":")[0]


def test_ping_failure_falls_to_next_model(log):
    called = []

    def handler(req):
        called.append(_model_of(req))
        return httpx.Response(404) if _model_of(req) == "m1" else httpx.Response(200, json=gemini_body())

    info = pick_model(_gemini_spec(handler, ["m1", "m2"]), log=log, sleep=lambda s: None)
    assert info["status"] == "active" and info["model"] == "m2"
    assert called == ["m1", "m2"]  # 404(모델 없음)는 재시도 없이 바로 다음 모델


def test_ping_three_transient_failures_then_next_model(log):
    called = []

    def handler(req):
        called.append(_model_of(req))
        return httpx.Response(503) if _model_of(req) == "m1" else httpx.Response(200, json=gemini_body())

    info = pick_model(_gemini_spec(handler, ["m1", "m2"]), log=log, sleep=lambda s: None)
    assert info["model"] == "m2" and called == ["m1", "m1", "m1", "m2"]


def test_ping_auth_failure_skips_judge_with_reason(log):
    info = pick_model(_gemini_spec(lambda r: httpx.Response(403), ["m1", "m2"]), log=log, sleep=lambda s: None)
    assert info["status"] == "skipped" and "403" in info["reason"]


def test_all_models_fail_skips_only_that_judge(tmp_path):
    items = make_items(2)
    codex = JudgeSpec("codex", ["a", "b"], lambda m: FakeJudge("codex", m, [CallError("bad", "model")]))
    claude = FakeJudge("claude", "haiku", [OK])
    execute([codex, JudgeSpec("claude", [None], lambda m: claude, ping=False)], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert state["judges"]["codex"]["status"] == "skipped" and "a:" in state["judges"]["codex"]["reason"]
    assert len(claude.calls) == 2
    assert "codex" in (tmp_path / "summary.md").read_text(encoding="utf-8")  # 이유가 요약에 남는다


def test_model_never_changes_mid_run(tmp_path):
    items = make_items(5)
    used = []

    def handler(req):
        used.append(_model_of(req))
        n = len(used)
        if n == 4:  # 본 판정 중간에 첫 모델이 한 건 완전히 죽는다
            return httpx.Response(503)
        return httpx.Response(200, json=gemini_body(model=_model_of(req)))

    spec = _gemini_spec(handler, ["m1", "m2"])
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    assert set(used) == {"m1"}  # m2는 한 번도 안 불림 (재시도도 같은 모델)
    rows = load_rows(tmp_path / "judge_gemini.jsonl")
    assert {r["model_requested"] for r in rows.values()} == {"m1"}


# ---- 이어하기 ---------------------------------------------------------------


def test_resume_reruns_only_unavailable_with_same_model(tmp_path):
    items = make_items(4)
    fail_prompt = items[1].prompt
    pings = []

    class Flaky(FakeJudge):
        def call(self, prompt):
            if prompt == "OK라고만 답해.":
                pings.append(self.model)
                return CallResult("OK", self.model)
            if prompt == fail_prompt:
                raise CallError("transient", 503)
            return CallResult(OK, self.model)

    spec = JudgeSpec("gemini", ["m1", "m2"], lambda m: Flaky("gemini", m))
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    rows = load_rows(tmp_path / "judge_gemini.jsonl")
    assert [r["verdict"] for r in rows.values()].count("판정불가") == 1

    # 이어하기: 정상 건은 0번, 판정 불가 건 1번만 호출. 시작 확인도 다시 안 한다.
    resumed = FakeJudge("gemini", "m1", [OK])
    spec2 = JudgeSpec("gemini", ["m1", "m2"], lambda m: resumed)
    execute([spec2], items, tmp_path, seed=1, resume=True, sleep=lambda s: None, now=NOW)
    assert resumed.calls == [fail_prompt]
    rows = load_rows(tmp_path / "judge_gemini.jsonl")
    assert all(r["verdict"] == "합격" for r in rows.values()) and len(rows) == 4
    assert pings == ["m1"]


def test_consecutive_failures_stop_judge(tmp_path, log):
    j = FakeJudge(script=[CallError("transient", 500)])
    out = run_judge(j, make_items(8), tmp_path / "j.jsonl", log=log, sleep=lambda s: None, fail_limit=2)
    assert "연속 2건" in out["stopped"]


# ---- 키 유출 없음 --------------------------------------------------------------


def test_key_never_leaks(tmp_path, capsys):
    items = make_items(3)

    def handler(req):
        # 일부러 예외 메시지와 응답 본문에 키를 심는다
        if "m1" in str(req.url) and not getattr(handler, "pinged", False):
            handler.pinged = True
            return httpx.Response(200, json=gemini_body(model="m1"))
        raise httpx.ConnectError(f"cannot reach host key={FAKE_KEY}")

    spec = _gemini_spec(handler, ["m1"])
    execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW, secrets=(Secret(FAKE_KEY),))
    out = capsys.readouterr()
    assert FAKE_KEY not in out.out and FAKE_KEY not in out.err
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert FAKE_KEY not in p.read_text(encoding="utf-8"), p.name
    judge = GeminiJudge("m1", Secret(FAKE_KEY), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(CallError) as ei:
        judge.call("p")
    assert FAKE_KEY not in str(ei.value) and FAKE_KEY not in repr(ei.value) and FAKE_KEY not in repr(judge.__dict__)


def test_retries_log_has_no_prompt_or_answer(tmp_path, log):
    item = make_items(1)[0]
    j = FakeJudge(script=[CallError("transient", 503), OK])
    run_judge(j, [item], tmp_path / "j.jsonl", log=log, sleep=lambda s: None)
    text = log.path.read_text(encoding="utf-8")
    assert item.answer not in text and item.question not in text and "[질문]" not in text


# ---- 판정 형식, 다수결, 목록 ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["", "합격", '```json\n' + OK + '\n```', '{"verdict":"통과","reason":"x","cause":"없음"}',
     '{"verdict":"합격","reason":"x"}', '{"verdict":"합격","reason":"x","cause":"몰라"}',
     '{"verdict":"합격","reason":"x","cause":"없음","extra":1}'],
)
def test_strict_format(text):
    assert parse_verdict(text)[0] is None


def test_valid_format():
    assert parse_verdict(OK)[0]["verdict"] == "합격"


def test_bad_format_counts_as_hold(tmp_path, log):
    j = FakeJudge(script=["not json"])
    run_judge(j, make_items(1), tmp_path / "j.jsonl", log=log, sleep=lambda s: None)
    row = next(iter(load_rows(tmp_path / "j.jsonl").values()))
    assert row["verdict"] == "보류" and row["status"] == "format_error"


def test_decide():
    assert decide({"a": "합격", "b": "합격", "c": "불합격"}) == ("합격", "")
    assert decide({"a": "불합격", "b": "불합격", "c": "보류"}) == ("불합격", "")
    assert decide({"a": "합격", "b": "불합격", "c": "보류"})[0] == "미정"
    assert decide({"a": "합격", "b": "합격"})[0] == "합격"  # 면접관 하나가 빠져도 2표
    assert decide({"a": "합격", "b": "판정불가"})[0] == "미정"
    assert decide({"a": "합격"}) == ("합격", "단독")


def test_review_list_hides_label_and_flags(tmp_path):
    items = make_items(3, labels=("접두어", "기준선"))
    a = FakeJudge("claude", "haiku", [OK])
    b = FakeJudge("codex", "c1", [NO])  # 항상 엇갈림
    execute([JudgeSpec("claude", [None], lambda m: a, ping=False), JudgeSpec("codex", ["c1"], lambda m: b, ping=False)],
            items, tmp_path, seed=3, sleep=lambda s: None, now=NOW)
    review = (tmp_path / "review.md").read_text(encoding="utf-8")
    assert "접두어" not in review and "기준선" not in review and "#01" in review
    assert "면접관끼리 엇갈림" in review
    bm = json.loads((tmp_path / "blind_map.json").read_text(encoding="utf-8"))
    assert {v["label"] for v in bm.values()} == {"접두어", "기준선"}
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    for needle in ("일치율", "사람이 볼 건수", "재시도", "판정 불가", "Codex 사용 토큰"):
        assert needle in summary


def test_auto_mismatch_is_flagged(tmp_path):
    items = make_items(2)
    for it in items:
        it.auto_correct = False  # 키워드 자동 판정은 불합격, 면접관은 합격
    j = FakeJudge("claude", "haiku", [OK])
    execute([JudgeSpec("claude", [None], lambda m: j, ping=False)], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    assert "키워드 자동 판정과 다름" in (tmp_path / "review.md").read_text(encoding="utf-8")


def test_prompt_has_no_result_name_or_verdicts():
    it = make_items(1, labels=("접두어",))[0]
    assert "접두어" not in it.prompt and "<answer>" in it.prompt and "[must_include]" in it.prompt
    assert "auto" not in it.prompt.lower()


# ---- 표본 뽑기 ---------------------------------------------------------------


def test_select_items_is_balanced_and_deterministic():
    items = make_items(10, labels=("A", "B", "C"))
    pick = select_items(items, 10, seed=11)
    assert len(pick) == 10 and len({i.key for i in pick}) == 10
    assert {i.label for i in pick} == {"A", "B", "C"}
    assert {i.qtype for i in pick} == {"in_notes", "not_in_notes"}
    assert [i.key for i in pick] == [i.key for i in select_items(items, 10, seed=11)]
    assert [i.key for i in pick] != [i.key for i in select_items(items, 10, seed=12)]
    assert len(select_items(items, None, 11)) == 30


# ---- 개별 면접관 ----------------------------------------------------------------


class Rec:
    def __init__(self, stdout="", stderr="", rc=0, write=None):
        self.stdout, self.stderr, self.rc, self.write, self.calls = stdout, stderr, rc, write, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.write is not None and "-o" in cmd:
            open(cmd[cmd.index("-o") + 1], "w", encoding="utf-8").write(self.write)
        return subprocess.CompletedProcess(cmd, self.rc, stdout=self.stdout, stderr=self.stderr)


def test_codex_command_and_tokens(tmp_path):
    events = '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
    r = Rec(stdout=events, write=OK)
    res = CodexJudge(tmp_path, "gpt-x", "low", runner=r).call("PROMPT")
    cmd, kw = r.calls[0]
    assert cmd[1:3] == ["exec", "--skip-git-repo-check"] and "read-only" in cmd
    assert "--ignore-user-config" in cmd
    assert cmd[cmd.index("cli_auth_credentials_store=keyring") - 1] == "-c"
    assert cmd[cmd.index("-m") + 1] == "gpt-x" and 'model_reasoning_effort="low"' in cmd
    assert kw["input"] == "PROMPT" and kw["cwd"] == str(tmp_path)
    assert (res.text, res.model, res.tokens) == (OK, "gpt-x", 120)


def test_codex_tokens_unknown_is_none():
    assert extract_codex_tokens('{"type":"x"}\nnot json\n') is None


def test_codex_error_classification(tmp_path):
    for stderr, want in [("401 Unauthorized", "auth"), ("model gpt-x does not exist", "bad"), ("boom", "transient")]:
        with pytest.raises(CallError) as ei:
            CodexJudge(tmp_path, "gpt-x", "low", runner=Rec(stderr=stderr, rc=1)).call("p")
        assert ei.value.kind == want
        assert stderr not in str(ei.value)  # 본문은 버린다


def test_claude_command_and_model_name(tmp_path):
    out = json.dumps({"result": OK, "modelUsage": {"claude-haiku-9": {}}})
    r = Rec(stdout=out)
    res = ClaudeJudge(tmp_path, runner=r).call("P")
    cmd = r.calls[0][0]
    for flag in ("-p", "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--setting-sources") + 1] == "local"
    assert (res.text, res.model) == (OK, "claude-haiku-9")
    with pytest.raises(CallError):
        ClaudeJudge(tmp_path, runner=Rec(rc=1)).call("P")


def test_claude_model_name_falls_back_to_alias(tmp_path):
    for out in (json.dumps({"result": OK}), json.dumps({"result": OK, "modelUsage": {}}), "not json " + OK):
        res = ClaudeJudge(tmp_path, runner=Rec(stdout=out)).call("P")
        assert res.model == "haiku(별칭)"


def test_resolve_workdir(tmp_path):
    from src.scripts.eval_judge import resolve_workdir

    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    outside = tmp_path / "judge"
    outside.mkdir()
    assert resolve_workdir(str(outside), root) == outside.resolve()
    for bad in (None, "", str(tmp_path / "nope"), str(root), str(root / "sub")):
        with pytest.raises(SystemExit):
            resolve_workdir(bad, root)


def quota_body(quota_id, delay=None):
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
         "quotaId": quota_id, "quotaDimensions": {"model": "x"}, "quotaValue": "5"}]}]
    if delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    return {"error": {"code": 429, "message": "SECRET-BODY-TEXT", "details": details}}


def test_429_per_minute_waits_retry_delay_and_logs_only_quota(tmp_path):
    seq = iter([httpx.Response(429, json=quota_body("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "37s")),
                httpx.Response(200, json=gemini_body())])
    judge = GeminiJudge("g", Secret(FAKE_KEY), client=httpx.Client(transport=httpx.MockTransport(lambda r: next(seq))))
    log, slept = RetryLog(tmp_path / "r.log", NOW), []
    res, attempts = call_with_retry(judge, "p", max_attempts=3, log=log, sleep=slept.append)
    assert attempts == 2 and slept == [37.0]
    text = (tmp_path / "r.log").read_text(encoding="utf-8")
    assert "quota_id=GenerateRequestsPerMinute" in text and "quota_value=5" in text and "wait37" in text
    assert "SECRET-BODY-TEXT" not in text and "quotaDimensions" not in text


def test_429_per_day_stops_without_retry_and_resume_message(tmp_path):
    hits = []

    def handler(req):
        hits.append(1)
        return httpx.Response(429, json=quota_body("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "20s"))

    items = make_items(3)
    spec = JudgeSpec("gemini", ["m1"], lambda m: GeminiJudge(
        "m1", Secret(FAKE_KEY), client=httpx.Client(transport=httpx.MockTransport(handler))), ping=False)
    summary = execute([spec], items, tmp_path, seed=1, sleep=lambda s: pytest.fail("기다리면 안 됨"), now=NOW)
    assert len(hits) == 1  # 한 건 시도하고 바로 멈춤, 재시도 없음
    assert "하루 한도, --resume으로 이어 하기" in summary
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["judges"]["gemini"]["status"] == "stopped"
    assert "PerDay" in (tmp_path / "retries.log").read_text(encoding="utf-8")


def test_429_ping_per_day_skips_judge_without_trying_next_model(tmp_path, log):
    hits = []

    def handler(req):
        hits.append(_model_of(req))
        return httpx.Response(429, json=quota_body("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))

    info = pick_model(_gemini_spec(handler, ["m1", "m2"]), log=log, sleep=lambda s: None)
    assert info["status"] == "skipped" and "하루 한도" in info["reason"] and hits == ["m1"]


def test_requested_and_reported_model_are_recorded_and_changes_flagged(tmp_path):
    items = make_items(2)
    names = iter(["gemini-3.6-flash", "gemini-3.6-flash", "gemini-3.7-flash"])  # 첫 이름은 시작 확인용
    spec = _gemini_spec(lambda req: httpx.Response(200, json=gemini_body(model=next(names))), ["gemini-3.5-flash"])
    summary = execute([spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    rows = load_rows(tmp_path / "judge_gemini.jsonl").values()
    assert {r["model_requested"] for r in rows} == {"gemini-3.5-flash"}
    assert {r["model_reported"] for r in rows} == {"gemini-3.6-flash", "gemini-3.7-flash"}
    assert "요청한 모델" in summary and "gemini-3.5-flash" in summary and "바뀜" in summary


def test_reported_model_same_gives_no_change_flag(tmp_path):
    spec = _gemini_spec(lambda req: httpx.Response(200, json=gemini_body(model="gemini-3.6-flash")), ["gemini-3.5-flash"])
    summary = execute([spec], make_items(2), tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    assert "gemini-3.6-flash" in summary and "바뀜" not in summary


def test_resume_skipped_judge_repicks_model_and_runs_missing(tmp_path):
    items = make_items(3)
    codex_bad = JudgeSpec("codex", ["c1"], lambda m: FakeJudge("codex", m, [CallError("bad", "model")]))
    claude = FakeJudge("claude", "haiku", [OK])
    claude_spec = JudgeSpec("claude", [None], lambda m: claude, ping=False)
    execute([codex_bad, claude_spec], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert state["judges"]["codex"]["status"] == "skipped"

    pinged = []

    class Codex(FakeJudge):
        def call(self, prompt):
            if prompt == "OK라고만 답해.":
                pinged.append(self.model)
            return CallResult(OK if prompt != "OK라고만 답해." else "OK", self.model)

    # 이어하기: 건너뛴 codex는 모델을 다시 골라(c1 실패 → c2) 모든 건을 돈다. claude는 이미 끝나 호출 0번.
    codex_ok = JudgeSpec("codex", ["c1", "c2"], lambda m: Codex("codex", m) if m == "c2" else FakeJudge("codex", m, [CallError("bad", "model")]))
    claude2 = FakeJudge("claude", "haiku", [OK])
    execute([codex_ok, JudgeSpec("claude", [None], lambda m: claude2, ping=False)], items, tmp_path, seed=1,
            resume=True, sleep=lambda s: None, now=NOW)
    assert pinged == ["c2"] and claude2.calls == []
    assert len(load_rows(tmp_path / "judge_codex.jsonl")) == 3


def test_resolve_gemini_rpm():
    from src.scripts.eval_judge import resolve_gemini_rpm

    assert resolve_gemini_rpm(None, None) == 4 and resolve_gemini_rpm(None, "") == 4
    assert resolve_gemini_rpm(None, "3") == 3 and resolve_gemini_rpm(6, "3") == 6
    assert resolve_gemini_rpm(0, "3") is None
    with pytest.raises(SystemExit):
        resolve_gemini_rpm(None, "abc")


def test_stop_during_retry_wait_saves_progress_and_resumes(tmp_path):
    import threading

    items = make_items(4)
    stop = threading.Event()
    calls = []

    class Flaky(FakeJudge):
        def call(self, prompt):
            calls.append(prompt)
            if len(calls) == 3:  # 두 건 판정 뒤 세 번째 건이 503
                raise CallError("transient", 503)
            return CallResult(OK, self.model)

    waits = []

    def fake_sleep(secs):  # 대기 중에 사용자가 Ctrl+C를 누른 상황
        waits.append(secs)
        stop.set()

    execute([JudgeSpec("claude", [None], lambda m: Flaky("claude", "haiku"), ping=False)], items, tmp_path,
            seed=1, sleep=fake_sleep, now=NOW, stop=stop)
    assert len(waits) == 1 and len(calls) == 3  # 대기 뒤 재시도하지 않고 멈춤
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert state["interrupted"] and state["judges"]["claude"]["status"] == "stopped"
    assert len(load_rows(tmp_path / "judge_claude.jsonl")) == 2  # 판정한 건은 저장됨
    assert "중단" in (tmp_path / "summary.md").read_text(encoding="utf-8")

    resumed = FakeJudge("claude", "haiku", [OK])
    execute([JudgeSpec("claude", [None], lambda m: resumed, ping=False)], items, tmp_path, seed=1,
            resume=True, sleep=lambda s: None, now=NOW)
    assert len(resumed.calls) == 2 and len(load_rows(tmp_path / "judge_claude.jsonl")) == 4
    assert "interrupted" not in json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))


def test_real_sleep_wakes_when_stopped():
    import threading
    import time as _t

    items = make_items(2)
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    t0 = _t.monotonic()
    j = FakeJudge(script=[CallError("transient", 503, retry_after=30)])
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        execute([JudgeSpec("claude", [None], lambda m: j, ping=False)], items, Path(d), seed=1, now=NOW, stop=stop)
    assert _t.monotonic() - t0 < 5  # 30초 대기를 기다리지 않는다


def test_gemini_http_timeout_is_set():
    j = GeminiJudge("g", Secret(FAKE_KEY))
    assert j.client.timeout.read == 60.0


def test_summary_splits_agreement_by_final_verdict(tmp_path):
    items = make_items(4)
    for i, it in enumerate(items):
        it.correct = i < 2  # 두 건은 최종 합격, 두 건은 최종 불합격
    lenient = FakeJudge("claude", "haiku", [OK])  # 늘 합격만 줌
    summary = execute([JudgeSpec("claude", [None], lambda m: lenient, ping=False)], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    assert "최종 합격 건에서" in summary and "최종 불합격 건에서" in summary
    assert "| claude | 2/4 (50%) | 2/2 (100%) | 0/2 (0%) |" in summary


def test_rate_limiter_spaces_calls():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    lim = RateLimiter(30, clock=lambda: t[0], sleep=sleep)  # 2초 간격
    lim.wait(); lim.wait(); lim.wait()
    assert slept == [2.0, 2.0]

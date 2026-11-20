"""배치 F (보안 1): Codex 도구 끄기, 도구 호출 감지, 인증 실패 분류 보완. 가짜 runner만 쓴다 (실제 codex 호출 없음).

- 도구를 끄는 옵션 목록은 상수 하나(CODEX_DISABLED_FEATURES)이고 CodexJudge가 쓴다. 토론 중재자와 3단계 검토자도 CodexJudge다.
- --json의 item.started / item.completed에서 item.type이 agent_message, reasoning, error가 아니면 도구 호출 → 판정불가.
- 실패 분류: stderr + stdout의 type이 error, turn.failed인 줄의 message (turn.failed 우선). 모델이 쓴 글은 보지 않는다.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from src.eval.judge import (
    CODEX_ALLOWED_ITEM_TYPES,
    CODEX_DISABLED_FEATURES,
    UNAVAILABLE,
    CallError,
    CodexJudge,
    JudgeSpec,
    RetryLog,
    build_items,
    codex_failure_text,
    codex_tool_args,
    codex_tool_item_types,
    execute,
    load_rows,
    pick_model,
    run_judge,
    _codex_error_kind,
)
from src.eval.runner import Question

OK = '{"verdict":"합격","reason":"맞게 답함","cause":"없음"}'
NOW = lambda: datetime(2026, 11, 7, 12, 0, 0)  # noqa: E731

USER_LIST = [
    "shell_tool", "unified_exec", "apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
    "browser_use_full_cdp_access", "computer_use", "image_generation", "view_image", "multi_agent", "tool_suggest", "skill_search",
]


def ev(**kw):
    return json.dumps(kw, ensure_ascii=False)


def item(kind, phase="item.completed", **extra):
    return ev(type=phase, item={"type": kind, **extra})


MSG = item("agent_message", text="합격입니다")
WS_FALLBACK = item("error", message="Falling back from WebSockets to HTTPS transport. stream disconnected before completion")


def make_items(n=4):
    qs, recs = [], []
    for i in range(n):
        qid = f"q{i:02d}"
        qs.append(Question(qid, f"질문{i}", "in_notes", ["a.md"], ["kw"]))
        recs.append({"label": "A", "id": qid, "repeat": 1, "answer": f"답{i}", "auto_correct": True, "correct": True})
    return build_items(recs, qs)


class Runner:
    """가짜 codex: 받은 명령을 기록하고, -o 파일에 답을 쓰고, 정해 둔 stdout을 돌려준다."""

    def __init__(self, stdout="", stderr="", rc=0, answer=OK):
        self.stdout, self.stderr, self.rc, self.answer, self.cmds = stdout, stderr, rc, answer, []

    def __call__(self, cmd, **kw):
        self.cmds.append(list(cmd))
        if self.answer is not None and self.rc == 0:
            Path(cmd[cmd.index("-o") + 1]).write_text(self.answer, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.rc, stdout=self.stdout, stderr=self.stderr)


def judge_with(tmp_path, runner):
    return CodexJudge(tmp_path, "gpt-x", "low", runner=runner)


def new_log(tmp_path, name="retries.log"):
    return RetryLog(tmp_path / name, NOW)


# ---- 1. 옵션 ---------------------------------------------------------------------------------------------------------------


def test_the_constant_is_exactly_the_tested_list_of_14():
    assert list(CODEX_DISABLED_FEATURES) == USER_LIST and len(set(CODEX_DISABLED_FEATURES)) == 14


def test_every_option_is_in_the_command(tmp_path):
    r = Runner(stdout=MSG)
    assert judge_with(tmp_path, r).call("p").text == OK
    (cmd,) = r.cmds
    assert any(cmd[i:i + 2] == ["-c", 'web_search="disabled"'] for i in range(len(cmd) - 1))
    disabled = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--disable"]
    assert disabled == USER_LIST  # 14개 모두, 각각 --disable 하나씩, 순서도 상수대로
    assert cmd.count("--disable") == 14


def test_existing_options_are_untouched(tmp_path):
    r = Runner(stdout=MSG)
    judge_with(tmp_path, r).call("p")
    cmd = r.cmds[0]
    assert cmd[1] == "exec" and cmd[cmd.index("--sandbox") + 1] == "read-only"
    for flag in ("--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--json"):
        assert flag in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-x" and 'model_reasoning_effort="low"' in cmd and cmd[-1] == "-"
    assert cmd[cmd.index("-C") + 1] == str(tmp_path)
    assert "--search" not in cmd  # 웹 검색을 켜는 옵션은 없다


def test_codex_tool_args_shape():
    args = codex_tool_args()
    assert args[:2] == ["-c", 'web_search="disabled"'] and len(args) == 2 + 2 * 14
    assert args[2::2] == ["--disable"] * 14 and args[3::2] == USER_LIST


def test_the_command_is_built_in_exactly_one_place():
    """1라운드 면접관, 토론 중재자, 3단계 검토자가 모두 같은 옵션을 쓰려면 codex 명령이 한 곳에서만 만들어져야 한다."""
    root = Path(__file__).resolve().parents[1]
    hits = sorted(p.relative_to(root).as_posix() for p in (root / "src").rglob("*.py") if '_which("codex")' in p.read_text(encoding="utf-8"))
    assert hits == ["src/eval/judge.py"]
    others = [p.name for p in (root / "src").rglob("*.py") if p.name != "judge.py" and '"codex", "exec"' in p.read_text(encoding="utf-8")]
    assert others == []


def test_the_arbiter_gets_the_same_options(tmp_path):
    from src.scripts import eval_judge as ej

    r = Runner(stdout=MSG)
    arb = CodexJudge(tmp_path, "gpt-x", ej.DEFAULT_ARBITER_EFFORT, runner=r)  # debate_main의 make_arb가 만드는 모양
    arb.call("p")
    assert [r.cmds[0][i + 1] for i, a in enumerate(r.cmds[0]) if a == "--disable"] == USER_LIST


# ---- 2. 도구 호출 감지 -------------------------------------------------------------------------------------------------


def test_allowed_types_are_exactly_message_reasoning_error():
    assert CODEX_ALLOWED_ITEM_TYPES == ("agent_message", "reasoning", "error")


def test_normal_output_has_no_tool_items():
    out = "\n".join([ev(type="thread.started", thread_id="t"), ev(type="turn.started"), item("reasoning", "item.started", text="..."),
                     item("reasoning", text="생각"), WS_FALLBACK, MSG, ev(type="turn.completed", usage={"input_tokens": 5, "output_tokens": 2})])
    assert codex_tool_item_types(out) == []


@pytest.mark.parametrize("kind", ["mcp_tool_call", "web_search", "command_execution", "file_change", "collab_tool_call", "todo_list",
                                  "image_generation_call", "unknown_future_type", "AGENT_MESSAGE", "agent_message2", ""])
@pytest.mark.parametrize("phase", ["item.started", "item.completed"])
def test_any_other_item_type_counts_as_a_tool_call(kind, phase):
    out = "\n".join([MSG, item(kind, phase)])
    assert codex_tool_item_types(out) == [kind or "?"]


def test_item_without_a_type_or_with_a_strange_type_is_blocked_too():
    for bad in ({"id": "x"}, {"type": None}, {"type": 5}, {"type": ["agent_message"]}):
        assert codex_tool_item_types(ev(type="item.completed", item=bad)) == ["?"]
    assert codex_tool_item_types(ev(type="item.completed", item="agent_message")) == ["?"]  # item이 객체가 아님
    assert codex_tool_item_types(ev(type="item.completed")) == ["?"]  # item이 없음


def test_other_event_types_are_not_looked_at():
    out = "\n".join([ev(type="turn.completed", item={"type": "command_execution"}), ev(type="error", message="x"), "not json {", "", "[1,2]"])
    assert codex_tool_item_types(out) == []


def test_type_names_are_cleaned_before_they_reach_logs_and_rows():
    assert codex_tool_item_types(item('a&b|c\n"d" e')) == ["abcde"]
    assert len(codex_tool_item_types(item("x" * 500))[0]) == 40
    assert codex_tool_item_types(item("&|<>")) == ["?"]


def test_several_types_are_listed_once_each_in_order():
    out = "\n".join([item("web_search", "item.started"), item("web_search"), item("mcp_tool_call"), item("command_execution")])
    assert codex_tool_item_types(out) == ["web_search", "mcp_tool_call", "command_execution"]


def test_a_tool_call_makes_the_call_fail_even_when_the_answer_looks_fine(tmp_path):
    r = Runner(stdout="\n".join([item("mcp_tool_call", "item.started"), item("mcp_tool_call"), MSG]))
    with pytest.raises(CallError) as ei:
        judge_with(tmp_path, r).call("p")
    exc = ei.value
    assert exc.kind == "tool" and exc.status == "tool_call" and "mcp_tool_call" in exc.detail
    assert not list(tmp_path.glob("codex-last-*.txt"))  # 출력 파일도 남기지 않는다


def test_the_websocket_fallback_notice_is_not_a_tool_call(tmp_path):
    r = Runner(stdout="\n".join([WS_FALLBACK, MSG]))
    assert judge_with(tmp_path, r).call("p").text == OK


def test_tool_call_is_saved_as_unavailable_with_the_reason_and_is_not_retried(tmp_path):
    r = Runner(stdout="\n".join([item("web_search"), MSG]))
    res = run_judge(judge_with(tmp_path, r), make_items(3), tmp_path / "j.jsonl", log=new_log(tmp_path), sleep=lambda s: None)
    assert res == {"stopped": None}  # 이 건들만 판정불가로 두고 계속한다
    assert len(r.cmds) == 3  # 건마다 한 번, 재시도 없음
    rows = list(load_rows(tmp_path / "j.jsonl").values())
    assert len(rows) == 3 and all(x["verdict"] == UNAVAILABLE and x["status"] == "failed:tool_call" and x["attempts"] == 1 for x in rows)
    assert all("web_search" in x["reason"] for x in rows)
    assert "web_search" in (tmp_path / "retries.log").read_text(encoding="utf-8")


def test_repeated_tool_calls_stop_the_judge_at_five_in_a_row(tmp_path):
    r = Runner(stdout=item("command_execution"))
    res = run_judge(judge_with(tmp_path, r), make_items(9), tmp_path / "j.jsonl", log=new_log(tmp_path), sleep=lambda s: None)
    assert len(r.cmds) == 5 and res["stopped"] == "연속 5건 실패 (마지막 tool_call)"


def test_a_good_call_after_a_tool_call_is_saved_normally_and_resume_reruns_the_failed_one(tmp_path):
    items = make_items(3)
    outs = iter([item("web_search"), MSG, MSG])

    class Seq(Runner):
        def __call__(self, cmd, **kw):
            self.stdout = next(outs)
            return super().__call__(cmd, **kw)

    seq = Seq()
    execute([JudgeSpec("codex", [None], lambda m: judge_with(tmp_path, seq), ping=False)], items, tmp_path, seed=1, sleep=lambda s: None, now=NOW)
    rows = load_rows(tmp_path / "judge_codex.jsonl")
    assert sorted(x["verdict"] for x in rows.values()) == sorted([UNAVAILABLE, "합격", "합격"])
    again = Runner(stdout=MSG)
    execute([JudgeSpec("codex", [None], lambda m: judge_with(tmp_path, again), ping=False)], items, tmp_path, seed=1, resume=True,
            sleep=lambda s: None, now=NOW)
    assert len(again.cmds) == 1 and all(x["verdict"] == "합격" for x in load_rows(tmp_path / "judge_codex.jsonl").values())


def test_startup_check_skips_codex_when_tools_are_not_off(tmp_path):
    r = Runner(stdout=item("mcp_tool_call"))
    made = []
    spec = JudgeSpec("codex", ["c1", "c2"], lambda m: made.append(m) or judge_with(tmp_path, r))
    out = pick_model(spec, log=new_log(tmp_path), sleep=lambda s: None)
    assert out["status"] == "skipped" and "도구가 꺼져 있지 않음" in out["reason"] and "mcp_tool_call" in out["reason"]
    assert made == ["c1"] and len(r.cmds) == 1  # 다른 모델로 다시 보내지 않는다


# ---- 3. 인증 실패 분류 보완 ---------------------------------------------------------------------------------------------

STDERR_WS = "failed to connect to Responses WebSocket"
RECONNECT = ev(type="error", message="Reconnecting... 5/5 (unexpected status 401 Unauthorized: Missing bearer or basic authentication)")
TURN_FAILED = ev(type="turn.failed", error={"message": "unexpected status 401 Unauthorized: Missing bearer or basic authentication"})


def failing(tmp_path, stdout, stderr):
    with pytest.raises(CallError) as ei:
        judge_with(tmp_path, Runner(stdout=stdout, stderr=stderr, rc=1)).call("p")
    return ei.value


def test_a_logged_out_run_is_auth_even_though_stderr_only_mentions_the_websocket(tmp_path):
    """PC 시험: 로그인 정보가 없으면 stderr에는 WebSocket 연결 실패만 있고 401은 stdout 이벤트에만 나온다."""
    exc = failing(tmp_path, "\n".join([ev(type="thread.started", thread_id="t"), RECONNECT, TURN_FAILED]), STDERR_WS)
    assert exc.kind == "auth" and exc.status == "auth"


def test_error_event_alone_is_enough(tmp_path):
    assert failing(tmp_path, RECONNECT, STDERR_WS).kind == "auth"


def test_401_inside_a_model_message_is_not_auth(tmp_path):
    """E의 재현 테스트가 계속 통과해야 한다: 모델이 쓴 글의 401은 안 본다."""
    out = "\n".join([item("agent_message", text="오류 401 Unauthorized, not logged in, login"), item("reasoning", text="403 forbidden")])
    exc = failing(tmp_path, out, "stream disconnected")
    assert exc.kind == "transient" and exc.status == "exit1"


def test_items_of_type_error_are_not_failure_events(tmp_path):
    """item.completed 안의 type=error 알림은 정상 경로에도 나온다. 최상위 type이 error, turn.failed인 줄만 본다."""
    out = item("error", message="unexpected status 401 Unauthorized (fell back)")
    assert failing(tmp_path, out, "stream disconnected").kind == "transient"


def test_turn_failed_wins_over_earlier_error_events():
    out = "\n".join([RECONNECT, ev(type="turn.failed", error={"message": "stream closed before response.completed"})])
    assert "401" not in codex_failure_text("", out) and _codex_error_kind(codex_failure_text("", out)) == ("transient", "")
    out2 = "\n".join([ev(type="error", message="stream closed"), TURN_FAILED])
    assert _codex_error_kind(codex_failure_text("", out2)) == ("auth", "auth")


def test_failure_text_ignores_everything_else():
    out = "\n".join([MSG, item("agent_message", text="401"), ev(type="turn.completed"), "not json 401", "[401]", ev(type="error"),
                     ev(type="error", message=401), ev(type="turn.failed"), ev(type="turn.failed", error="401"),
                     ev(type="turn.failed", error={"message": 5})])
    assert codex_failure_text("boom", out) == "boom"
    assert codex_failure_text("", "") == "" and codex_failure_text(None, None) == ""  # type: ignore[arg-type]


def test_stderr_is_still_used(tmp_path):
    assert failing(tmp_path, "", "unexpected status 401 Unauthorized").kind == "auth"
    assert failing(tmp_path, "", "The model `gpt-x` does not exist").kind == "bad"


def test_model_error_in_an_event_is_bad(tmp_path):
    out = ev(type="turn.failed", error={"message": "The model `gpt-x` does not exist or you do not have access (404)"})
    exc = failing(tmp_path, out, STDERR_WS)
    assert exc.kind == "bad" and exc.status == "model"


def test_auth_failure_stops_the_judge_but_a_transient_one_does_not(tmp_path):
    items = make_items(9)
    out = run_judge(judge_with(tmp_path, Runner(stdout="\n".join([RECONNECT, TURN_FAILED]), stderr=STDERR_WS, rc=1)), items,
                    tmp_path / "a.jsonl", log=new_log(tmp_path, "r1.log"), sleep=lambda s: None)
    assert out["stopped"] == "auth:auth" and len(load_rows(tmp_path / "a.jsonl")) == 1  # 첫 건에서 멈춘다 (재시도 없음)
    transient = Runner(stdout=item("agent_message", text="401 login"), stderr="stream disconnected", rc=1)
    out = run_judge(judge_with(tmp_path, transient), items, tmp_path / "b.jsonl", log=new_log(tmp_path, "r2.log"), sleep=lambda s: None)
    assert out["stopped"] == "연속 5건 실패 (마지막 exit1)" and len(transient.cmds) == 30  # 일반 일시 오류는 예전 그대로 6번 x 5건

"""배치 C (보안 5): .env 값 검사.

CODEX_JUDGE_MODELS, CODEX_JUDGE_EFFORT, GEMINI_JUDGE_MODELS, JUDGE_WORKDIR, ARBITER_JUDGE, ARBITER_MODEL, ARBITER_EFFORT는
명령 인자(npm으로 깐 codex는 codex.cmd라 cmd.exe가 해석한다)나 URL에 그대로 들어간다.
허용 목록과 글자 검사로 막고, 아무것도 호출하기 전에 읽기 쉬운 메시지로 멈춘다. 가짜 runner만 쓴다.
"""

from __future__ import annotations

import subprocess

import pytest

from src.eval import judge
from src.eval.judge import (
    CODEX_EFFORTS,
    ClaudeJudge,
    CodexJudge,
    GeminiJudge,
    validate_effort,
    validate_model,
)
from src.keystore import Secret
from src.scripts import eval_judge as ej

EVIL_MODELS = [
    "evil&calc", "a|b", "a<b", "a>b", "a^b", "a%PATH%", "a!b", 'x" -c foo', "x'y", "a b", "a;b", "a\nb", "a\tb",
    "-m", "--oss", "-", "", " ", "한글모델", "a/b", "a\\b", "a(b)", "a" * 65, "$(whoami)", "`id`",
]
GOOD_MODELS = ["gpt-5.6-terra", "gpt-x", "o3", "claude-sonnet-5-5", "haiku", "opus[1m]", "gemini-2.5-flash", "a", "gpt-5.6:fast", "m_1.2", "a" * 64]


# ---- 검사 함수 -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", GOOD_MODELS)
def test_good_model_names_pass(value):
    assert validate_model(value) == value


@pytest.mark.parametrize("value", EVIL_MODELS)
def test_evil_model_names_are_refused(value):
    with pytest.raises(ValueError):
        validate_model(value)


def test_non_string_model_is_refused():
    for value in (None, 5, ["a"]):
        with pytest.raises(ValueError):
            validate_model(value)  # type: ignore[arg-type]


def test_error_shows_at_most_40_characters_of_the_value():
    with pytest.raises(ValueError) as ei:
        validate_model("&" + "z" * 200)
    assert "z" * 41 not in str(ei.value)


@pytest.mark.parametrize("value", list(CODEX_EFFORTS))
def test_known_efforts_pass(value):
    assert validate_effort(value) == value


@pytest.mark.parametrize("value", ["minimal", "", "LOW", "low ", 'low"', "low -c x", "medium; whoami", "high&calc", "none", "0"])
def test_unknown_efforts_are_refused(value):
    with pytest.raises(ValueError):
        validate_effort(value)


def test_effort_list_matches_what_codex_catalog_reported():
    assert CODEX_EFFORTS == ("low", "medium", "high", "xhigh", "max", "ultra")  # `codex debug models` (2026-11-21)


# ---- 생성자가 마지막 관문: runner에 닿기 전에 막는다 -------------------------------------------------------------------


def boom_runner(*a, **k):
    raise AssertionError("검사에 걸린 값으로 명령을 만들면 안 된다")


@pytest.mark.parametrize("value", EVIL_MODELS)
def test_judge_constructors_refuse_evil_models(tmp_path, value):
    with pytest.raises(ValueError):
        CodexJudge(tmp_path, value, "low", runner=boom_runner)
    with pytest.raises(ValueError):
        ClaudeJudge(tmp_path, model=value, runner=boom_runner)


@pytest.mark.parametrize("value", ["a:b", "a/b", "../x", "a?b", "a b", "", "-x", "a" * 65, "x#y"])
def test_gemini_model_goes_into_a_url_so_it_is_stricter(value):
    with pytest.raises(ValueError):
        GeminiJudge(value, Secret("k" * 39))


def test_gemini_still_accepts_normal_names():
    for name in ("gemini-2.5-flash", "g", "m1", "gemini-x"):
        assert GeminiJudge(name, Secret("k" * 39)).model == name


@pytest.mark.parametrize("effort", ["minimal", 'low" -c x', "", "low;calc"])
def test_codex_judge_refuses_bad_effort(tmp_path, effort):
    with pytest.raises(ValueError):
        CodexJudge(tmp_path, "gpt-x", effort, runner=boom_runner)


def test_valid_values_reach_the_command_unchanged(tmp_path):
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        raise subprocess.TimeoutExpired("x", 1)

    j = CodexJudge(tmp_path, "gpt-5.6-terra", "xhigh", runner=runner)
    with pytest.raises(judge.CallError):
        j.call("p")
    assert "gpt-5.6-terra" in seen["cmd"] and 'model_reasoning_effort="xhigh"' in seen["cmd"]


# ---- _build_specs: .env 값을 읽는 곳 -------------------------------------------------------------------------------------


def no_secret(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("검사에 걸리면 금고 암호를 묻기 전에 멈춰야 한다")

    monkeypatch.setattr(ej, "get_secret", boom)


@pytest.mark.parametrize("value", ["gpt-x&calc", "gpt-x,evil|b", "-m", "ok,bad name"])
def test_codex_models_env_is_checked_before_anything_runs(tmp_path, monkeypatch, value):
    monkeypatch.setenv("CODEX_JUDGE_MODELS", value)
    monkeypatch.delenv("CODEX_JUDGE_EFFORT", raising=False)
    with pytest.raises(SystemExit) as ei:
        ej._build_specs(["codex"], tmp_path, None)
    assert "CODEX_JUDGE_MODELS" in str(ei.value)


@pytest.mark.parametrize("value", ["minimal", 'low" -c web_search="live', "low&calc", "LOW"])
def test_codex_effort_env_is_checked(tmp_path, monkeypatch, value):
    monkeypatch.setenv("CODEX_JUDGE_MODELS", "gpt-x")
    monkeypatch.setenv("CODEX_JUDGE_EFFORT", value)
    with pytest.raises(SystemExit) as ei:
        ej._build_specs(["codex"], tmp_path, None)
    assert "CODEX_JUDGE_EFFORT" in str(ei.value)


def test_valid_codex_env_builds_specs(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_JUDGE_MODELS", "gpt-5.6-terra, gpt-x")
    monkeypatch.setenv("CODEX_JUDGE_EFFORT", "high")
    specs, _ = ej._build_specs(["codex"], tmp_path, None)
    assert specs[0].models == ["gpt-5.6-terra", "gpt-x"] and specs[0].make("gpt-x").effort == "high"


def test_codex_effort_default_is_valid_and_unset_models_still_skip_codex(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_JUDGE_MODELS", raising=False)
    monkeypatch.delenv("CODEX_JUDGE_EFFORT", raising=False)
    specs, _ = ej._build_specs(["codex"], tmp_path, None)
    assert specs[0].unavailable  # 값이 없는 것은 기존대로 '쓸 수 없음'


@pytest.mark.parametrize("value", ["gemini/../x", "g:x", "a b", "evil&x", "-x"])
def test_gemini_models_env_is_checked_before_the_vault_password_prompt(tmp_path, monkeypatch, value):
    no_secret(monkeypatch)
    monkeypatch.setenv("GEMINI_JUDGE_MODELS", value)
    with pytest.raises(SystemExit) as ei:
        ej._build_specs(["gemini"], tmp_path, None)
    assert "GEMINI_JUDGE_MODELS" in str(ei.value)


def test_checks_only_apply_to_judges_that_are_used(tmp_path, monkeypatch):
    """claude만 쓰는 실행은 codex, gemini의 .env 값이 이상해도 막지 않는다."""
    monkeypatch.setenv("CODEX_JUDGE_MODELS", "evil&calc")
    monkeypatch.setenv("GEMINI_JUDGE_MODELS", "evil&calc")
    specs, _ = ej._build_specs(["claude"], tmp_path, None)
    assert [s.name for s in specs] == ["claude"]


# ---- JUDGE_WORKDIR -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ch", list('&|<>^%!"') + ["\n", "\t", "\x00", "\x1b"])
def test_workdir_with_command_characters_is_refused(tmp_path, ch):
    folder = tmp_path / f"a{ch}b"
    try:
        folder.mkdir()  # 윈도우는 만들 수 없는 글자도 있다. 그래도 검사는 폴더 확인보다 먼저라 같은 결과여야 한다
    except (OSError, ValueError):
        pass
    with pytest.raises(SystemExit) as ei:
        ej.resolve_workdir(str(folder), tmp_path / "repo")
    assert "JUDGE_WORKDIR" in str(ei.value) and "글자" in str(ei.value)


def test_normal_workdir_still_works_including_spaces_and_hangul(tmp_path):
    for name in ("judge work", "면접관 작업", "a-b_c.d (1)"):
        d = tmp_path / name
        d.mkdir()
        assert ej.resolve_workdir(str(d), tmp_path / "repo") == d.resolve()


# ---- ARBITER_JUDGE, ARBITER_MODEL, ARBITER_EFFORT ---------------------------------------------------------------------


MODELS = {"codex": "gpt-x", "gemini": "gem-x", "claude": None}


@pytest.mark.parametrize("name", ["claude", "codex", "gemini"])
def test_arbiter_judge_allows_exactly_three_names(name):
    assert ej.resolve_arbiter(None, {"ARBITER_JUDGE": name}, MODELS)[0] == name


@pytest.mark.parametrize("name", ["claude&calc", "codex|x", "CLAUDE", "Codex", "openai", "claude,codex", "claude codex", "human", "claude\ncodex", "../claude"])
def test_arbiter_judge_refuses_everything_else_from_env_and_cli(name):
    with pytest.raises(SystemExit):
        ej.resolve_arbiter(None, {"ARBITER_JUDGE": name}, MODELS)
    with pytest.raises(SystemExit):
        ej.resolve_arbiter(f"{name}:sonnet", {}, MODELS)


def test_arbiter_judge_message_is_short():
    with pytest.raises(SystemExit) as ei:
        ej.resolve_arbiter(None, {"ARBITER_JUDGE": "x" * 300}, MODELS)
    assert "x" * 41 not in str(ei.value)


@pytest.mark.parametrize("model", ["evil&calc", "a|b", "-m", "x y", 'x"', "a" * 65])
def test_arbiter_model_is_checked_from_env_cli_and_run_state(model):
    for call in (
        lambda: ej.resolve_arbiter(None, {"ARBITER_MODEL": model}, MODELS),
        lambda: ej.resolve_arbiter(f"codex:{model}", {}, MODELS),
        lambda: ej.resolve_arbiter(None, {"ARBITER_JUDGE": "claude", "ARBITER_MODEL": model}, MODELS),
        lambda: ej.resolve_arbiter("codex", {}, {"codex": model}),  # 이전 실행의 run.json에서 온 값도 검사한다
    ):
        with pytest.raises(SystemExit) as ei:
            call()
        assert "형식이 이상합니다" in str(ei.value)


@pytest.mark.parametrize("effort", ["minimal", "medium; whoami", "HIGH", 'low"', "high&calc", "0"])
def test_arbiter_effort_is_checked(effort):
    with pytest.raises(SystemExit) as ei:
        ej.resolve_arbiter(None, {"ARBITER_EFFORT": effort}, MODELS)
    assert "ARBITER_EFFORT" in str(ei.value)


def test_valid_arbiter_settings_pass_and_defaults_are_unchanged():
    assert ej.resolve_arbiter(None, {}, MODELS) == ("claude", "sonnet", "medium")
    assert ej.resolve_arbiter(None, {"ARBITER_JUDGE": "codex", "ARBITER_MODEL": "gpt-5.6-terra", "ARBITER_EFFORT": "xhigh"}, MODELS) == ("codex", "gpt-5.6-terra", "xhigh")
    assert ej.resolve_arbiter("gemini", {}, MODELS) == ("gemini", "gem-x", "medium")


def test_compare_arbiter_checks_the_codex_model(monkeypatch):
    monkeypatch.setenv("CODEX_JUDGE_MODELS", "evil&calc")
    with pytest.raises(SystemExit):
        ej.compare_arbiter("claude", {})
    with pytest.raises(SystemExit):
        ej.compare_arbiter("claude", {"codex": "a|b"})
    assert ej.compare_arbiter("claude", {"codex": "gpt-x"}) == ("codex", "gpt-x", "medium")
    assert ej.compare_arbiter("codex", {})[:2] == ("claude", "sonnet")

"""배치 H: Codex 리뷰 4건. 가짜 면접관, 가짜 runner만 쓴다.

1. 토론 이어하기: debate/config.json의 설정이 지금과 다르면 멈춘다 (덮어쓰지 않음, 우회 스위치 없음).
2. codex_failure_text: turn.failed가 있으면 그 message만으로 분류한다.
3. 2라운드 면접관 하나가 멈추면 중재와 최종 확정을 하지 않는다.
4. 가드 거부 메시지에 볼트 경로 원문을 넣지 않는다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.eval import debate_store as store
from src.eval.debate import debate_settings, run_debate, verify_resume_config
from src.eval.judge import CallError, CodexJudge, codex_failure_text, _codex_error_kind
from src.eval.judge_guard import check_external_judges
from tests.test_debate import NAMES, ROUND2_FULL, Scripted, arb, corpus, judges_for, make_run, real_folder  # noqa: F401  (corpus, real_folder는 fixture)


def go(folder, items, state, corpus_dir, round2, *, arb_model="arb-m", arb_name="claude", arb_effort=None, compare=None, models=None,
       arbiter_script=None, out=None):
    """compare: (이름, 모델, effort) 또는 None."""
    objs, arb_obj = judges_for(round2, arbiter_script if arbiter_script is not None else {"질문2": arb("합격")}, models)
    arb_obj.model = arb_model
    if arb_effort is not None:
        arb_obj.effort = arb_effort
    cmp_pair = None
    if compare:
        cmp_obj = Scripted("cmp", arbiter={"질문2": arb("합격")}, model=compare[1])
        if compare[2] is not None:
            cmp_obj.effort = compare[2]
        cmp_pair = (compare[0], cmp_obj)
    msgs: list[str] = []
    res = run_debate(folder, items, state, judges=objs, arbiter=(arb_name, arb_obj), compare=cmp_pair, corpus_dir=corpus_dir,
                     sleep=lambda s: None, out=out or msgs.append)
    return res, objs, arb_obj, msgs


def stopped_codex_round2(code=401):
    """codex만 2라운드에서 인증 실패로 멈추는 설정."""
    r2 = {n: dict(v) for n, v in ROUND2_FULL.items()}
    r2["codex"] = {q: CallError("auth", code) for q in ("질문0", "질문2", "질문3")}
    return r2


def config_bytes(folder):
    return (store.ddir(folder) / store.CONFIG_FILE).read_bytes()


# ---- 3. 2라운드 면접관이 멈추면 중재, 최종 확정을 하지 않는다 -----------------------------------------------------------


def test_one_judge_stopped_by_auth_means_no_arbiter_call_and_no_final_file(tmp_path, corpus):
    folder, items, state = make_run(tmp_path)
    res, objs, arb_obj, msgs = go(folder, items, state, corpus, stopped_codex_round2())
    assert res["interrupted"] is False and "final" not in res
    assert res["incomplete"] == ["2라운드 미완료: codex: auth:401"]
    assert [m for m in msgs if m.startswith("2라운드 미완료")] == res["incomplete"]  # 화면에도 그대로 보여 준다
    assert arb_obj.prompts == []  # 중재 호출 0번
    d = store.ddir(folder)
    assert not (d / store.FINAL_FILE).exists() and not (d / store.ARBITER_FILE).exists() and not (d / store.COMPARE_FILE).exists()
    cfg = store.load_config(folder)
    assert cfg["incomplete"] == ["2라운드 미완료: codex: auth:401"] and cfg["ended"] is False and cfg["stage"] == "round2"
    assert cfg["stopped"] == {"codex": "auth:401"}


def test_the_round2_lines_already_written_are_kept(tmp_path, corpus):
    folder, items, state = make_run(tmp_path)
    go(folder, items, state, corpus, stopped_codex_round2())
    assert len(store.read_rows(store.round2_path(folder, "claude"))) == 3 and len(store.read_rows(store.round2_path(folder, "gemini"))) == 3
    rows = list(store.read_rows(store.round2_path(folder, "codex")).values())
    assert rows and all(r["status"] == "failed:401" for r in rows)  # 실패한 줄도 그대로 남는다


def test_resume_reruns_only_what_is_left_then_finishes(tmp_path, corpus):
    folder, items, state = make_run(tmp_path)
    go(folder, items, state, corpus, stopped_codex_round2())
    before = {n: store.round2_path(folder, n).read_bytes() for n in ("claude", "gemini")}
    res, objs, arb_obj, _ = go(folder, items, state, corpus, ROUND2_FULL)
    assert res["interrupted"] is False and "incomplete" not in res and res["final"]
    assert objs["claude"].prompts == [] and objs["gemini"].prompts == []  # 끝난 면접관은 다시 안 부른다
    assert len(objs["codex"].prompts) == 3  # 멈췄던 면접관만 남은 건을 돈다
    assert {n: store.round2_path(folder, n).read_bytes() for n in ("claude", "gemini")} == before
    assert len(arb_obj.prompts) == 1 and (store.ddir(folder) / store.FINAL_FILE).exists()
    cfg = store.load_config(folder)
    assert cfg["ended"] is True and "incomplete" not in cfg


def test_two_judges_stopped_are_both_listed(tmp_path, corpus):
    folder, items, state = make_run(tmp_path)
    r2 = stopped_codex_round2()
    r2["gemini"] = {q: ValueError("깨짐") for q in ("질문0", "질문2", "질문3")}
    res, _o, arb_obj, _m = go(folder, items, state, corpus, r2)
    assert sorted(res["incomplete"]) == ["2라운드 미완료: codex: auth:401", "2라운드 미완료: gemini: 예기치 못한 오류 ValueError"]
    assert arb_obj.prompts == []


def test_the_debate_page_shows_the_incomplete_state(tmp_path, corpus):
    from src.eval import judge_web

    folder, items, state = make_run(tmp_path)
    go(folder, items, state, corpus, stopped_codex_round2())
    data = judge_web.build_data(folder, items, {it.key: f"B{i:03d}" for i, it in enumerate(items)}, NAMES, {}, phase="ended", interrupted=False,
                                killed=False, blind=True, retries=0, started="x", stamp=__import__("datetime").datetime(2026, 11, 7),
                                debate=store.load_config(folder))
    assert data["kind"] == "stopped" and "2라운드 미완료: codex: auth:401" in data["status"]


def test_cli_returns_1_makes_no_report_and_never_calls_the_arbiter(real_folder, monkeypatch, capsys, tmp_path):
    """CLI(--debate): 중재, 최종 확정, 보고서를 만들지 않고 이유와 이어하기 명령을 보여 준다. 실제 면접관은 부르지 않는다."""
    from tests.test_debate import ej, no_keys

    folder, _res, _ = real_folder
    no_keys(monkeypatch)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("JUDGE_WORKDIR", str(work))
    objs, arb_obj = judges_for(stopped_codex_round2(), {})
    specs = [ej.JudgeSpec(n, [None], lambda m, n=n: objs[n], ping=False) for n in NAMES]
    monkeypatch.setattr(ej, "_build_specs", lambda names, wd, rpm: (specs, []))
    monkeypatch.setattr(ej, "ClaudeJudge", lambda wd, model=None: arb_obj)  # 진짜 claude가 불릴 수 없게 가짜로 바꾼다
    assert ej.main(["--debate", str(folder), "--yes"]) == 1
    err = capsys.readouterr().err
    assert "2라운드 미완료: codex: auth:401" in err and "중재와 최종 확정은 하지 않았습니다" in err and f"--debate {folder}" in err
    d = store.ddir(folder)
    assert arb_obj.prompts == [] and not (d / store.FINAL_FILE).exists() and not (d / "report.md").exists()


# ---- 1. 이어하기 설정 비교 ------------------------------------------------------------------------------------------------


def first_run(tmp_path, corpus_dir, **kw):
    """config.json을 남기는 첫 실행 (codex 인증 실패로 2라운드 미완료 → 설정만 저장됨)."""
    folder, items, state = make_run(tmp_path)
    go(folder, items, state, corpus_dir, stopped_codex_round2(), **kw)
    return folder, items, state


def assert_refused_without_touching_anything(folder, items, state, corpus_dir, expect, **kw):
    cfg_before = config_bytes(folder)
    files_before = sorted((p.name, p.stat().st_size) for p in store.ddir(folder).iterdir())
    objs, arb_obj = judges_for(ROUND2_FULL, {"질문2": arb("합격")}, kw.get("models"))
    with pytest.raises(SystemExit) as ei:
        go(folder, items, state, corpus_dir, ROUND2_FULL, **kw)
    assert expect in str(ei.value) and "config.json은 고치지 않았습니다" in str(ei.value)
    assert config_bytes(folder) == cfg_before  # 덮어쓰지 않았다
    assert sorted((p.name, p.stat().st_size) for p in store.ddir(folder).iterdir()) == files_before  # 다른 파일도 안 바뀜
    return objs


def test_same_settings_resume_fine(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus)
    res, *_ = go(folder, items, state, corpus, ROUND2_FULL)
    assert res["interrupted"] is False and res["final"]


def test_changed_arbiter_model_stops(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus)
    assert_refused_without_touching_anything(folder, items, state, corpus, "중재자 모델: arb-m → arb-other", arb_model="arb-other")


def test_changed_arbiter_name_stops(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus)
    assert_refused_without_touching_anything(folder, items, state, corpus, "중재자 이름: claude → codex", arb_name="codex")


def test_changed_arbiter_effort_stops(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus, arb_name="codex", arb_effort="medium")
    assert store.load_config(folder)["arbiter"] == {"judge": "codex", "model": "arb-m", "effort": "medium"}
    assert_refused_without_touching_anything(folder, items, state, corpus, "중재자 effort: medium → high", arb_name="codex", arb_effort="high")


def test_effort_of_non_codex_arbiters_is_not_compared(tmp_path, corpus):
    """claude, gemini 면접관 객체에는 effort가 없다 (있어도 쓰지 않는다). codex일 때만 비교한다."""
    folder, items, state = first_run(tmp_path, corpus)
    res, *_ = go(folder, items, state, corpus, ROUND2_FULL, arb_effort="high")  # claude 중재자
    assert res["final"]


def test_adding_removing_or_changing_the_compare_arbiter_stops(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus)  # 비교 중재자 없이 시작
    assert_refused_without_touching_anything(folder, items, state, corpus, "비교 중재자: 없음 → codex", compare=("codex", "cmp-m", "medium"))
    folder2, items2, state2 = first_run(tmp_path / "b", corpus, compare=("codex", "cmp-m", "medium"))
    assert store.load_config(folder2)["compare"] == {"judge": "codex", "model": "cmp-m", "effort": "medium"}
    assert_refused_without_touching_anything(folder2, items2, state2, corpus, "비교 중재자: codex → 없음")
    assert_refused_without_touching_anything(folder2, items2, state2, corpus, "비교 중재자 모델: cmp-m → cmp-x", compare=("codex", "cmp-x", "medium"))
    assert_refused_without_touching_anything(folder2, items2, state2, corpus, "비교 중재자 effort: medium → high", compare=("codex", "cmp-m", "high"))
    assert_refused_without_touching_anything(folder2, items2, state2, corpus, "비교 중재자 이름: codex → gemini", compare=("gemini", "cmp-m", None))


def test_changed_round2_judge_model_stops(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus)
    assert_refused_without_touching_anything(folder, items, state, corpus, "2라운드 면접관 codex 모델: m → m2", models={"codex": "m2"})


def test_a_judge_added_or_removed_counts_as_a_change(tmp_path):
    saved = {"models": {"claude": "m", "codex": "m"}, "arbiter": {"judge": "claude", "model": "a", "effort": None}, "compare": None}
    cur = {"models": {"claude": "m", "codex": "m", "gemini": "m"}, "arbiter": saved["arbiter"], "compare": None}
    with pytest.raises(SystemExit) as ei:
        verify_resume_config(saved, cur)
    assert "gemini" in str(ei.value) and "(없음)" in str(ei.value)


def test_old_config_without_keys_only_warns_and_is_then_rewritten_complete(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus)
    cfg = store.load_config(folder)
    del cfg["models"], cfg["compare"]
    del cfg["arbiter"]["effort"]
    store.write_config(folder, cfg)
    res, _o, _a, msgs = go(folder, items, state, corpus, ROUND2_FULL)
    warns = [m for m in msgs if m.startswith("경고:")]
    assert res["final"] and len(warns) == 3 and all(m.startswith("경고: 이전 설정에") for m in warns)
    assert any("2라운드 면접관 모델" in m for m in warns) and any("중재자 effort" in m for m in warns) and any("비교 중재자 기록" in m for m in warns)
    new = store.load_config(folder)
    assert set(new["models"]) == set(NAMES) and "effort" in new["arbiter"] and "compare" in new


def test_old_config_keys_that_exist_are_still_compared(tmp_path, corpus):
    folder, items, state = first_run(tmp_path, corpus)
    cfg = store.load_config(folder)
    del cfg["arbiter"]["effort"]  # effort만 옛 형식, 모델은 있다
    store.write_config(folder, cfg)
    assert_refused_without_touching_anything(folder, items, state, corpus, "중재자 모델", arb_model="arb-other")


def test_a_first_run_has_nothing_to_compare(tmp_path, corpus):
    folder, items, state = make_run(tmp_path)
    assert store.load_config(folder) is None
    res, *_ = go(folder, items, state, corpus, ROUND2_FULL)
    assert res["final"]


def test_verify_resume_config_unit():
    cur = {"models": {"a": "m"}, "arbiter": {"judge": "claude", "model": "s", "effort": None}, "compare": None}
    assert verify_resume_config(None, cur) == [] and verify_resume_config({}, cur) == []
    assert verify_resume_config(dict(cur), cur) == []
    warns = verify_resume_config({"models": {"a": "m"}}, cur)
    assert len(warns) == 2  # arbiter, compare 기록 없음
    class Obj:  # noqa: E306
        model, effort = "x", "high"
    assert debate_settings({"a": Obj()}, ("codex", Obj()), ("gemini", Obj())) == {
        "models": {"a": "x"}, "arbiter": {"judge": "codex", "model": "x", "effort": "high"}, "compare": {"judge": "gemini", "model": "x", "effort": None}}


# ---- 2. codex_failure_text: turn.failed가 있으면 그 message만 -------------------------------------------------------------


def ev(**kw):
    return json.dumps(kw, ensure_ascii=False)


def failing(tmp_path, stdout, stderr):
    def runner(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout=stdout, stderr=stderr)

    with pytest.raises(CallError) as ei:
        CodexJudge(tmp_path, "gpt-x", "low", runner=runner).call("p")
    return ei.value


TURN_STREAM = ev(type="turn.failed", error={"message": "stream disconnected before completion"})


def test_401_in_stderr_does_not_matter_when_turn_failed_says_stream_disconnected(tmp_path):
    exc = failing(tmp_path, TURN_STREAM, "WARN earlier attempt: unexpected status 401 Unauthorized (token refreshed)")
    assert exc.kind == "transient" and exc.status == "exit1"


def test_model_text_in_stderr_does_not_matter_either(tmp_path):
    assert failing(tmp_path, TURN_STREAM, "The model `x` does not exist").kind == "transient"


def test_turn_failed_401_is_auth_whatever_stderr_says(tmp_path):
    out = ev(type="turn.failed", error={"message": "unexpected status 401 Unauthorized"})
    assert failing(tmp_path, out, "stream disconnected").kind == "auth"


def test_error_lines_with_401_do_not_count_when_turn_failed_exists(tmp_path):
    out = "\n".join([ev(type="error", message="Reconnecting... 5/5 (unexpected status 401 Unauthorized)"), TURN_STREAM])
    assert failing(tmp_path, out, "").kind == "transient"


def test_without_turn_failed_stderr_and_error_lines_are_used(tmp_path):
    assert failing(tmp_path, "", "unexpected status 401 Unauthorized").kind == "auth"
    assert failing(tmp_path, ev(type="error", message="unexpected status 401 Unauthorized"), "failed to connect to Responses WebSocket").kind == "auth"
    assert failing(tmp_path, "", "failed to connect to Responses WebSocket").kind == "transient"


def test_turn_failed_without_a_usable_message_falls_back_to_the_rest(tmp_path):
    for bad in (ev(type="turn.failed"), ev(type="turn.failed", error="401"), ev(type="turn.failed", error={"message": 5})):
        assert failing(tmp_path, bad, "unexpected status 401 Unauthorized").kind == "auth"


def test_failure_text_shape():
    out = "\n".join([ev(type="error", message="E1"), ev(type="turn.failed", error={"message": "T1"}), ev(type="turn.failed", error={"message": "T2"})])
    assert codex_failure_text("S", out) == "T1\nT2"
    assert codex_failure_text("S", ev(type="error", message="E1")) == "S\nE1"
    assert _codex_error_kind(codex_failure_text("401 unauthorized", TURN_STREAM)) == ("transient", "")


# ---- 4. 가드 메시지에 볼트 경로 원문 없음 ---------------------------------------------------------------------------------


def result(d, stem, line):
    (d / f"{stem}.md").write_text("# 결과\n\n" + line + "\n", encoding="utf-8")
    jsonl = d / f"{stem}_rescored-v2.jsonl"
    jsonl.write_text("{}\n", encoding="utf-8")
    return str(jsonl)


@pytest.mark.parametrize("vault", ["C:/Users/me/Documents/진짜볼트", "D:\\PersonProject\\private-vault", "/home/me/secret notes", "../outside",
                                   "data/eval_corpus/../vault", "data/vault-secret", "-", "x"])
def test_refusal_never_contains_the_vault_path(tmp_path, vault):
    f = result(tmp_path, "r", f"- 볼트: {vault}, 컬렉션: mala_eval_docs")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([f], ["claude", "codex"])
    msg = str(ei.value)
    assert "r_rescored-v2.jsonl" in msg and "볼트 경로가 data/eval_corpus/ 밖" in msg
    for piece in (vault, vault.replace("\\", "/"), "진짜볼트", "private-vault", "secret", "Documents"):
        if piece not in ("x", "-", "../outside"):
            assert piece not in msg


def test_collection_names_are_still_shown(tmp_path):
    f = result(tmp_path, "r", "- 볼트: C:/Users/me/vault, 컬렉션: mala_vault_prefix")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([f], ["claude"])
    assert "컬렉션 mala_vault_prefix" in str(ei.value) and "C:/Users" not in str(ei.value)


def test_debate_cli_refusal_has_no_vault_path_either(tmp_path, monkeypatch):
    from tests.test_debate import ej, no_keys  # noqa: F401

    folder, items, state = make_run(tmp_path)  # 다른 폴더 구조가 필요하므로 가드만 직접 확인한다
    f = result(tmp_path, "cli", "- 볼트: C:/Users/me/Documents/진짜볼트, 컬렉션: mala_eval_docs")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([f], ["claude", "codex", "gemini"], Path(tmp_path))
    assert "진짜볼트" not in str(ei.value) and "C:/Users" not in str(ei.value)

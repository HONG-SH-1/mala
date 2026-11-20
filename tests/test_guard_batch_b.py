"""배치 B: 가드 (judge_guard).

- 보안 2: 면제할 이름만 적고 나머지는 전부 외부로 본다 (새 이름도 검사를 받는다).
- 보안 3: 컬렉션 이름만 맞고 볼트 경로가 진짜 볼트인 결과를 막는다 ("볼트:" 줄이 data/eval_corpus/ 안인지).
- 보안 4: claude -p도 외부 전송이라 같은 가드를 탄다.
"""

from __future__ import annotations

import pytest

from src.eval import judge_guard
from src.eval.judge_guard import check_external_judges, vault_is_allowed, vaults_of


def result(d, stem, line):
    """짝 .md에 line을 적고 재채점 .jsonl 경로를 돌려준다."""
    (d / f"{stem}.md").write_text("# 평가 결과\n\n" + line + "\n", encoding="utf-8")
    jsonl = d / f"{stem}_rescored-v2.jsonl"
    jsonl.write_text("{}\n", encoding="utf-8")
    return str(jsonl)


GOOD = "- 볼트: data/eval_corpus/docs-20261028, 컬렉션: mala_eval_docs"


# ---- 보안 2: 이름 ---------------------------------------------------------------------------------------------------------


def test_no_judge_name_is_exempt():
    assert judge_guard.EXEMPT_JUDGES == ()


@pytest.mark.parametrize("who", ["claude", "codex", "gemini", "newjudge", "CODEX", "Claude", "", "claude:sonnet", "human"])
def test_every_name_including_new_ones_is_checked_against_a_vault_result(tmp_path, who):
    f = result(tmp_path, "vault", "- 볼트: data/eval_corpus/x, 컬렉션: mala_vault")
    with pytest.raises(SystemExit):
        check_external_judges([f], [who])


@pytest.mark.parametrize("who", ["claude", "codex", "gemini", "newjudge", "CODEX"])
def test_public_docs_result_passes_for_any_name(tmp_path, who):
    check_external_judges([result(tmp_path, "docs", GOOD)], [who])


def test_no_judges_means_nothing_is_sent_so_nothing_to_check(tmp_path):
    check_external_judges([result(tmp_path, "vault", "- 볼트: data/x, 컬렉션: mala_vault")], [])


def test_error_names_every_judge_once(tmp_path):
    f = result(tmp_path, "vault", "- 볼트: data/eval_corpus/x, 컬렉션: mala_vault")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([f], ["claude", "codex", "claude"])
    msg = str(ei.value)
    assert msg.count("claude") >= 1 and "claude, codex 실행을 거부합니다" in msg and "claude -p도 외부 전송" in msg


# ---- 보안 3: 볼트 경로 ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["claude", "codex", "gemini"])
def test_real_vault_path_with_a_docs_collection_name_is_refused(tmp_path, who):
    """재현: 결과 .md가 '볼트: C:/…/진짜볼트, 컬렉션: mala_eval_docs'여도 예전에는 통과했다."""
    f = result(tmp_path, "r", "- 볼트: C:/Users/me/Documents/진짜볼트, 컬렉션: mala_eval_docs")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([f], [who])
    assert "볼트 경로" in str(ei.value) and "data/eval_corpus/" in str(ei.value)


@pytest.mark.parametrize("raw", [
    "data/eval_corpus/docs-20261028",
    "data/eval_corpus/docs-20261028/",
    "./data/eval_corpus/docs-20261028",
    "data\\eval_corpus\\docs-20261028",
    '"data/eval_corpus/docs-20261028"',
])
def test_corpus_paths_are_allowed(raw):
    assert vault_is_allowed(raw)


@pytest.mark.parametrize("raw", [
    "", "-", "x", "data/x", "data/eval_corpus", "data/eval_corpus/", "data/eval_corpusX/docs",
    "data/eval_corpus/../vault", "data/eval_corpus/..", "../data/eval_corpus/docs",
    "C:/Users/me/vault", "C:\\Users\\me\\vault", "/home/me/vault", "other/data/eval_corpus/docs",
    "Data/Eval_Corpus/docs",
])
def test_everything_else_is_refused(raw):
    assert not vault_is_allowed(raw)


def test_absolute_path_is_allowed_only_inside_the_repo_corpus(tmp_path):
    root = tmp_path / "repo"
    (root / "data" / "eval_corpus" / "docs").mkdir(parents=True)
    (root / "data" / "vault").mkdir(parents=True)
    assert vault_is_allowed(str(root / "data" / "eval_corpus" / "docs"), root)
    assert not vault_is_allowed(str(root / "data" / "eval_corpus"), root)  # 폴더 자체는 안 됨
    assert not vault_is_allowed(str(root / "data" / "vault"), root)
    assert not vault_is_allowed(str(root / "data" / "eval_corpus" / ".." / "vault"), root)
    assert not vault_is_allowed(str(root / "data" / "eval_corpus" / "docs"))  # 레포를 모르면 거부


def test_absolute_corpus_path_passes_the_guard_with_root(tmp_path):
    root = tmp_path / "repo"
    docs = root / "data" / "eval_corpus" / "docs"
    docs.mkdir(parents=True)
    f = result(tmp_path, "abs", f"- 볼트: {docs}, 컬렉션: mala_eval_docs")
    check_external_judges([f], ["claude", "codex"], root)
    with pytest.raises(SystemExit):
        check_external_judges([f], ["claude"])  # root가 없으면 절대 경로를 확인할 수 없어 거부


def test_vaults_of_parses_the_line(tmp_path):
    assert vaults_of(result(tmp_path, "a", GOOD)) == ["data/eval_corpus/docs-20261028"]
    assert vaults_of(result(tmp_path, "b", "- 볼트: data/eval_corpus/a, b, 컬렉션: mala_eval_docs")) == ["data/eval_corpus/a, b"]
    assert vaults_of(result(tmp_path, "c", "- 볼트: C:/v")) == ["C:/v"]
    assert vaults_of(result(tmp_path, "d", "- 컬렉션: mala_eval_docs")) == []


def test_md_without_a_vault_line_is_still_judged_by_collection_only(tmp_path):
    """eval_synth가 만드는 짝 .md와 10-28 이전 형식은 볼트 줄이 없다. 이 경우는 지금처럼 컬렉션 이름만 본다."""
    f = result(tmp_path, "synth", "- 원래 결과: a.jsonl, 컬렉션: mala_eval_docs")
    check_external_judges([f], ["claude", "codex", "gemini"])
    g = result(tmp_path, "synth2", "- 원래 결과: a.jsonl, 컬렉션: mala_vault")
    with pytest.raises(SystemExit):
        check_external_judges([g], ["claude"])


def test_vault_dash_means_unknown_and_is_refused(tmp_path):
    f = result(tmp_path, "dash", "- 볼트: -, 컬렉션: mala_eval_docs")
    with pytest.raises(SystemExit):
        check_external_judges([f], ["claude"])


def test_refusal_reports_both_problems_per_file_and_names_only_bad_files(tmp_path):
    good = result(tmp_path, "ok-run", GOOD)
    bad = result(tmp_path, "bad-run", "- 볼트: D:/vault, 컬렉션: mala_vault")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([good, bad], ["claude"])
    msg = str(ei.value)
    assert "bad-run" in msg and "ok-run" not in msg and "컬렉션 mala_vault" in msg  # 컬렉션 이름은 그대로 보여 준다
    assert "볼트 경로가 data/eval_corpus/ 밖" in msg and "D:/vault" not in msg  # 볼트 경로 원문은 넣지 않는다


def test_committed_baseline_results_still_pass_for_every_judge():
    """레포에 올라가 있는 비교 기준 결과는 가드를 통과해야 한다 (볼트 규칙이 기준선을 막지 않는다)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    names = sorted((root / "eval" / "results").glob("*_rescored-v2.jsonl"))
    assert names
    for f in names:
        check_external_judges([str(f)], ["claude", "codex", "gemini"], root)

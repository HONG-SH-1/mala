"""사람 판정 합치기, 안전장치(컬렉션) 테스트."""

import json

import pytest

from src.eval.judge import JudgeSpec, execute
from src.eval.judge_guard import check_external_judges, collections_of
from src.eval.judge_human import HumanImportError, import_human, load_human
from tests.test_eval_judge import NO, NOW, OK, FakeJudge, make_items


def run(tmp_path, items):
    scripts = {"claude": [OK], "codex": [NO], "gemini": [OK]}
    specs = [JudgeSpec(n, [None], lambda m, n=n: FakeJudge(n, "m", scripts[n]), ping=False) for n in scripts]
    return execute(specs, items, tmp_path, seed=3, sleep=lambda s: None, now=NOW)


def export(tmp_path, folder, entries, name="export.json", run_name=None):
    p = tmp_path / name
    p.write_text(json.dumps({"run": run_name or folder.name, "items": entries}, ensure_ascii=False), encoding="utf-8")
    return p


def bids(folder):
    bm = json.loads((folder / "blind_map.json").read_text(encoding="utf-8"))
    return sorted(bm), bm


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "20261107-1000_t"
    f.mkdir()
    items = make_items(4)
    for it in items:
        it.correct = True
    run(f, items)
    return f


# ---- 합치기 ------------------------------------------------------------


def test_import_writes_human_jsonl_and_summary_shows_agreement(folder, tmp_path):
    ids, bm = bids(folder)
    p = export(tmp_path, folder, [
        {"bid": ids[0], "verdict": "합격", "reason": "맞음", "at": "2026-11-07T10:00:00Z", "blind": True},
        {"bid": ids[1], "verdict": "불합격", "reason": "틀림", "at": "2026-11-07T10:01:00Z", "blind": True},
        {"bid": ids[2], "verdict": "보류", "reason": "애매", "at": "2026-11-07T10:02:00Z", "blind": True},
    ])
    assert import_human(folder, p) == 3
    human = load_human(folder)
    assert len(human) == 3 and human[bm[ids[0]]["key"]]["human_verdict"] == "합격"
    # 요약은 finalize가 다시 쓴다 (판정 호출 없음)
    from src.eval.judge import finalize

    items = make_items(4)
    for it in items:
        it.correct = True
    state = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    text = finalize(folder, items, state, 3, 0)
    assert "## 사람 판정과의 일치율" in text and "블라인드 판정(면접관 판정이 가려진 상태에서 저장): 3건" in text and "보류 1건" in text
    assert "전체를 대표하지 않습니다" in text


def test_summary_has_no_human_section_without_human_file(folder):
    assert "사람 판정과의 일치율" not in (folder / "summary.md").read_text(encoding="utf-8")


def test_invalid_input_writes_nothing(folder, tmp_path):
    ids, _ = bids(folder)
    good = {"bid": ids[0], "verdict": "합격", "reason": "ok", "at": ""}
    cases = [
        [good, {"bid": ids[1], "verdict": "아마도", "reason": "x", "at": ""}],
        [good, {"bid": "B999", "verdict": "합격", "reason": "x", "at": ""}],
        [good, {"bid": ids[1], "verdict": "합격", "reason": "가" * 501, "at": ""}],
        [good, {"bid": ids[1], "verdict": "합격", "reason": 5, "at": ""}],
        [good, "문자열"],
    ]
    for entries in cases:
        with pytest.raises(HumanImportError):
            import_human(folder, export(tmp_path, folder, entries))
        assert not (folder / "human.jsonl").exists()  # 좋은 항목도 쓰지 않았다


def test_broken_json_wrong_run_and_big_file_are_rejected(folder, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(HumanImportError):
        import_human(folder, bad)
    with pytest.raises(HumanImportError):
        import_human(folder, export(tmp_path, folder, [], run_name="다른폴더"))
    big = tmp_path / "big.json"
    big.write_text(" " * 1_100_000, encoding="utf-8")
    with pytest.raises(HumanImportError):
        import_human(folder, big)
    assert not (folder / "human.jsonl").exists()


def test_importing_twice_is_idempotent_and_last_value_wins(folder, tmp_path):
    ids, _ = bids(folder)
    one = export(tmp_path, folder, [{"bid": ids[0], "verdict": "합격", "reason": "a", "at": "t1"}], "one.json")
    import_human(folder, one)
    first = (folder / "human.jsonl").read_text(encoding="utf-8")
    import_human(folder, one)
    assert (folder / "human.jsonl").read_text(encoding="utf-8") == first
    two = export(tmp_path, folder, [{"bid": ids[0], "verdict": "불합격", "reason": "b", "at": "t2"}], "two.json")
    import_human(folder, two)  # 다른 파일을 다시 합치면 마지막 값
    rows = load_human(folder)
    assert len(rows) == 1 and next(iter(rows.values()))["human_verdict"] == "불합격"


def test_same_number_twice_in_one_file_is_rejected(folder, tmp_path):
    ids, _ = bids(folder)
    dup = export(tmp_path, folder, [{"bid": ids[0], "verdict": "불합격", "reason": "b", "at": "t2"},
                                    {"bid": ids[0], "verdict": "보류", "reason": "c", "at": "t3"}], "dup.json")
    with pytest.raises(HumanImportError) as ei:
        import_human(folder, dup)
    assert "두 번" in str(ei.value) and ids[0] in str(ei.value)
    assert not (folder / "human.jsonl").exists()  # 아무것도 쓰지 않는다
    p = tmp_path / "dupc.json"
    p.write_text(json.dumps({"run": folder.name, "items": [], "criteria": [
        {"bid": ids[0], "odd": True, "note": "a", "at": "t"}, {"bid": ids[0], "odd": False, "note": "b", "at": "t"}]}), encoding="utf-8")
    with pytest.raises(HumanImportError):
        import_human(folder, p)
    assert not (folder / "criteria.jsonl").exists()


def test_human_labels_stay_out_of_review_html(folder, tmp_path):
    ids, _ = bids(folder)
    import_human(folder, export(tmp_path, folder, [{"bid": ids[0], "verdict": "합격", "reason": "비공개-이유-표식", "at": ""}]))
    items = make_items(4)
    from src.eval.judge import finalize

    state = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    finalize(folder, items, state, 3, 0)
    assert "비공개-이유-표식" not in (folder / "review.html").read_text(encoding="utf-8")


def test_old_style_numbers_can_be_imported(tmp_path):
    f = tmp_path / "run"
    f.mkdir()
    items = make_items(2)
    (f / "blind_map.json").write_text(json.dumps({"#01": {"key": items[0].key, "label": "A", "id": "q00", "repeat": 1}}), encoding="utf-8")
    p = export(tmp_path, f, [{"bid": "#01", "verdict": "합격", "reason": "x", "at": ""}])
    assert import_human(f, p) == 1


# ---- 안전장치: 볼트 컬렉션 -----------------------------------------------------


def write_result(d, stem, collection, rescored=True):
    md = d / f"{stem}.md"
    lines = ["# 평가 결과", "", "- 시각: x"]
    if collection:
        lines.append(f"- 볼트: data/x, 컬렉션: {collection}")
    md.write_text("\n".join(lines), encoding="utf-8")
    jsonl = d / (f"{stem}_rescored-v2.jsonl" if rescored else f"{stem}.jsonl")
    jsonl.write_text("{}\n", encoding="utf-8")
    return str(jsonl)


def test_guard_reads_collection_from_original_md(tmp_path):
    f = write_result(tmp_path, "20261030-2134_baseline-docs-prefix", "mala_eval_docs_prefix")
    assert collections_of(f) == ["mala_eval_docs_prefix"]
    check_external_judges([f], ["claude", "codex", "gemini"])  # 문서 컬렉션은 통과


def test_guard_refuses_non_docs_collection_for_codex_and_gemini(tmp_path):
    f = write_result(tmp_path, "run1", "mala_vault_prefix")
    for judges in (["codex"], ["gemini"], ["claude", "codex", "gemini"]):
        with pytest.raises(SystemExit) as ei:
            check_external_judges([f], judges)
        assert "run1" in str(ei.value) and "mala_vault_prefix" in str(ei.value)
    check_external_judges([f], ["claude"])  # claude만이면 막지 않는다


def test_guard_stops_when_collection_unknown(tmp_path):
    f = write_result(tmp_path, "old-run", None)
    with pytest.raises(SystemExit) as ei:
        check_external_judges([f], ["gemini"])
    assert "찾지 못함" in str(ei.value)
    lone = tmp_path / "lonely_rescored-v2.jsonl"
    lone.write_text("{}\n", encoding="utf-8")  # 짝 .md 자체가 없다
    with pytest.raises(SystemExit):
        check_external_judges([str(lone)], ["codex"])


def test_guard_allows_only_public_docs_collections(tmp_path):
    for name in ("mala_eval_docs", "mala_eval_docs_prefix"):
        check_external_judges([write_result(tmp_path, f"ok-{name}", name)], ["codex", "gemini"])
    for name in ("mala_vault", "mala_eval", "other_docs", "MALA_EVAL_DOCS", "xmala_eval_docs"):
        f = write_result(tmp_path, f"no-{name}", name)
        with pytest.raises(SystemExit):
            check_external_judges([f], ["gemini"])
        check_external_judges([f], ["claude"])


def test_guard_checks_every_file(tmp_path):
    good = write_result(tmp_path, "ok-run", "mala_eval_docs")
    bad = write_result(tmp_path, "bad-run", "MALA_VAULT")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([good, bad], ["codex"])
    assert "bad-run" in str(ei.value) and "ok-run" not in str(ei.value)


def test_guard_also_looks_in_data_eval(tmp_path):
    root = tmp_path / "root"
    (root / "data" / "eval").mkdir(parents=True)
    results = tmp_path / "results"
    results.mkdir()
    jsonl = results / "x_rescored-v2.jsonl"
    jsonl.write_text("{}\n", encoding="utf-8")
    (root / "data" / "eval" / "x.md").write_text("- 볼트: v, 컬렉션: mala_vault\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        check_external_judges([str(jsonl)], ["gemini"], root)


def make_repo(tmp_path):
    root = tmp_path / "root"
    res = root / "eval" / "results"
    res.mkdir(parents=True)
    return root, res


def write_override(res, stem, collection):
    body = f'{stem}:\n  collection: {collection}\n  confirmed: "사후 확인"\n  evidence: ["근거"]\n'
    (res / "source_overrides.yaml").write_text(body, encoding="utf-8")


def test_override_used_only_when_md_has_no_collection_line(tmp_path):
    root, res = make_repo(tmp_path)
    f = write_result(res, "old-run", None)
    with pytest.raises(SystemExit):
        check_external_judges([f], ["gemini"], root)  # 확인 파일이 없으면 거부
    write_override(res, "old-run", "mala_eval_docs")
    assert collections_of(f, root) == ["mala_eval_docs"]
    check_external_judges([f], ["codex", "gemini"], root)  # 이제 통과


def test_override_is_ignored_when_md_has_collection_line(tmp_path):
    root, res = make_repo(tmp_path)
    f = write_result(res, "run-v", "mala_vault")
    write_override(res, "run-v", "mala_eval_docs")  # .md가 우선: 덮어쓰지 못한다
    assert collections_of(f, root) == ["mala_vault"]
    with pytest.raises(SystemExit):
        check_external_judges([f], ["gemini"], root)


def test_override_gets_same_allow_list_rule(tmp_path):
    root, res = make_repo(tmp_path)
    for bad in ("mala_vault", "other_docs", "MALA_EVAL_DOCS"):
        f = write_result(res, f"r-{bad}", None)
        write_override(res, f"r-{bad}", bad)
        with pytest.raises(SystemExit):
            check_external_judges([f], ["codex"], root)
        check_external_judges([f], ["claude"], root)


def test_override_is_per_result_and_handles_bad_yaml(tmp_path):
    root, res = make_repo(tmp_path)
    a = write_result(res, "run-a", None)
    b = write_result(res, "run-b", None)
    write_override(res, "run-a", "mala_eval_docs")
    check_external_judges([a], ["gemini"], root)
    with pytest.raises(SystemExit):
        check_external_judges([b], ["gemini"], root)  # 다른 결과에는 적용되지 않는다
    (res / "source_overrides.yaml").write_text("{: 깨진", encoding="utf-8")
    with pytest.raises(SystemExit):
        check_external_judges([a], ["gemini"], root)  # 읽을 수 없으면 거부 (안전한 쪽)
    (res / "source_overrides.yaml").write_text("run-a: 문자열\nrun-b:\n  collection: 5\n", encoding="utf-8")
    for f in (a, b):
        with pytest.raises(SystemExit):
            check_external_judges([f], ["gemini"], root)


def test_override_found_under_repo_results_with_rescored_name(tmp_path):
    root, res = make_repo(tmp_path)
    write_override(res, "20261028-2205_baseline-docs", "mala_eval_docs")
    f = write_result(res, "20261028-2205_baseline-docs", None)
    check_external_judges([f], ["gemini"], root)


def test_override_is_read_only_from_repo_results_and_only_for_inputs_inside_it(tmp_path):
    root, res = make_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    f = write_result(other, "run-x", None)
    write_override(other, "run-x", "mala_eval_docs")  # 입력 파일 옆의 파일: 읽지 않는다
    assert collections_of(f, root) == []
    write_override(res, "run-x", "mala_eval_docs")  # 레포 파일에 있어도 입력이 eval/results 밖이면 적용하지 않는다
    assert collections_of(f, root) == []
    with pytest.raises(SystemExit):
        check_external_judges([f], ["codex"], root)
    (root / "data" / "eval").mkdir(parents=True)
    g = write_result(root / "data" / "eval", "run-x", None)  # data/eval 안도 마찬가지
    assert collections_of(g, root) == []
    # .. 로 eval/results를 빠져나가는 경로도 안 된다
    sneaky = str(res / ".." / ".." / "other" / "run-x_rescored-v2.jsonl")
    assert collections_of(sneaky, root) == []
    # root를 모르면 아무 파일도 읽지 않는다
    h = write_result(res, "run-h", None)
    write_override(res, "run-h", "mala_eval_docs")
    assert collections_of(h) == []
    assert collections_of(h, root) == ["mala_eval_docs"]


def test_override_with_duplicate_keys_is_rejected(tmp_path):
    root, res = make_repo(tmp_path)
    f = write_result(res, "run-d", None)
    top = "run-d:\n  collection: mala_vault\nrun-d:\n  collection: mala_eval_docs\n"  # 뒤의 값이 앞을 덮는 모양
    inner = "run-d:\n  collection: mala_eval_docs\n  collection: mala_vault\n"
    for body in (top, inner):
        (res / "source_overrides.yaml").write_text(body, encoding="utf-8")
        assert collections_of(f, root) == []
        with pytest.raises(SystemExit):
            check_external_judges([f], ["codex", "gemini"], root)
    (res / "source_overrides.yaml").write_text("run-d:\n  collection: mala_eval_docs\n", encoding="utf-8")
    check_external_judges([f], ["codex"], root)  # 겹침이 없으면 통과


def test_override_loader_is_a_safe_loader():
    import yaml

    from src.eval import judge_guard

    assert issubclass(judge_guard._UniqueKeyLoader, yaml.SafeLoader)
    with pytest.raises(yaml.YAMLError):
        yaml.load("a: !!python/object/apply:os.getcwd []", Loader=judge_guard._UniqueKeyLoader)  # 파이썬 객체는 만들지 않는다


def test_repo_override_file_covers_the_1028_baseline_and_passes_the_guard():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    f = root / "eval" / "results" / "20261028-2205_baseline-docs_rescored-v2.jsonl"
    assert collections_of(f, root) == ["mala_eval_docs"]
    check_external_judges([str(f)], ["codex", "gemini"], root)
    text = (root / "eval" / "results" / "source_overrides.yaml").read_text(encoding="utf-8")
    assert "evidence" in text and "사후 확인" in text
    assert not any(x in text for x in ("C:\\", "D:\\", "/Users/", "tmdgu"))  # 내 PC 경로 없음


def test_guard_error_has_no_note_content(tmp_path):
    f = write_result(tmp_path, "r", "mala_vault")
    with pytest.raises(SystemExit) as ei:
        check_external_judges([f], ["codex"])
    assert "공개 문서(docs) 기준" in str(ei.value)


def test_main_refuses_before_asking_for_a_key(tmp_path, monkeypatch, capsys):
    """main이 키를 꺼내거나 폴더를 만들기 전에 멈추는지."""
    import src.scripts.eval_judge as ej

    qfile = tmp_path / "q.yaml"
    qfile.write_text("- id: q00\n  question: 질문\n  type: in_notes\n  expected_sources: [a.md]\n  must_include: [kw]\n", encoding="utf-8")
    rec = tmp_path / "vault-run_rescored-v2.jsonl"
    rec.write_text(json.dumps({"label": "L", "id": "q00", "repeat": 1, "answer": "a", "auto_correct": True, "correct": True}) + "\n", encoding="utf-8")
    (tmp_path / "vault-run.md").write_text("- 볼트: v, 컬렉션: mala_vault\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("JUDGE_WORKDIR", str(work))
    monkeypatch.setattr(ej, "JUDGE_DIR", tmp_path / "judge")
    monkeypatch.setattr(ej, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(ej, "get_secret", lambda *a, **k: pytest.fail("금고를 열면 안 됨"))
    with pytest.raises(SystemExit):
        ej.main([str(rec), "--judges", "gemini", "--questions", str(qfile)])
    assert not (tmp_path / "judge").exists()  # 결과 폴더도 안 만들었다

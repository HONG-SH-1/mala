"""review.html의 칸 구성, 발췌, 최종 판정 출처, 판정 기준, 기준 의견(판정과 분리) 테스트."""

import json
import re

import pytest

from src.eval.judge import JudgeSpec, execute, finalize
from src.eval.judge_human import HumanImportError, import_human, load_criteria, load_human
from src.eval.judge_report import RUBRIC, TEMPLATE, build_excerpts, doc_excerpt
from tests.test_eval_judge import NO, NOW, OK, FakeJudge, make_items


def run(folder, items):
    scripts = {"claude": [OK], "codex": [NO], "gemini": [OK]}
    specs = [JudgeSpec(n, [None], lambda m, n=n: FakeJudge(n, "m", scripts[n]), ping=False) for n in scripts]
    return execute(specs, items, folder, seed=3, sleep=lambda s: None, now=NOW)


def data_of(folder):
    html = (folder / "review.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "20261107-1000_t"
    f.mkdir()
    return f


def tpl():
    return TEMPLATE.read_text(encoding="utf-8")


# ---- 한 건 화면의 칸 -----------------------------------------------------------


def test_item_sections_are_in_the_requested_order_with_plain_titles():
    t = tpl()
    body = t[t.index("function itemBody"):t.index("function finalSourceText")]
    titles = ["질문", "문항 유형", "정답 조건", "근거 문서", "MALA의 답 (평가 대상)", "MALA가 찾아온 출처"]
    pos = [body.index(f'section("{x}"') for x in titles]
    assert pos == sorted(pos)


def test_type_descriptions_and_empty_texts_are_in_template():
    t = tpl()
    assert "문서에 답이 있음. 아래 핵심어가 답에 들어가야 합격" in t
    assert "문서에 답이 없음. 없다고 말하고 지어내지 않아야 합격" in t
    assert "없음(위 유형 설명 참고)" in t and "기록 없음" in t
    assert "원문 보기" in t and "읽기 좋게 보기" in t


def test_chips_join_alternatives_with_or():
    assert '.join(" 또는 ")' in tpl()


def test_every_form_control_has_id_and_name():
    lines = tpl().splitlines()
    found = 0
    for i, ln in enumerate(lines):
        if re.search(r'createElement\("(input|select|textarea)"\)', ln):
            found += 1
            near = "\n".join(lines[i:i + 3])
            assert ".id =" in near and ".name =" in near, near
    assert found >= 7  # 숨김 체크, 라디오, 이유, 기준 체크, 기준 메모, 면접관 선택, 내보낸 내용


def test_no_dangerous_apis_still_absent():
    t = tpl()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in t


# ---- 데이터: 근거 문서, 찾아온 출처, 최종 판정 출처 ----------------------------------


def test_records_carry_sources_and_final_source(folder):
    items = make_items(3)
    items[0].expected_sources = ["a.md", "sub/b.md"]
    items[0].retrieved_sources = ["a.md", "z.md"]
    items[0].manual_correct = False
    items[0].correct = False
    items[1].manual_correct = None
    items[2].correct = None
    run(folder, items)
    recs = {r["qid"]: r for r in data_of(folder)["items"]}
    q0, q1, q2 = (recs[it.qid] for it in items)
    assert q0["expected_sources"] == ["a.md", "sub/b.md"] and q0["retrieved_sources"] == ["a.md", "z.md"]
    assert q0["final_source"] == "manual" and q1["final_source"] == "auto" and q2["final_source"] == "none"


def test_final_source_text_in_template():
    t = tpl()
    assert "사람이 고침 (manual.yaml)" in t and "키워드 자동 판정" in t and "출처: " in t


def test_doc_excerpt_around_first_keyword_and_fallback():
    text = "\n".join(f"줄{i}" for i in range(1, 41)) + "\n"
    ex = doc_excerpt(text, ["줄20"])
    assert ex["from"] == 18 and ex["to"] == 30 and ex["total"] == 40 and "줄20" in ex["text"]
    head = doc_excerpt(text, [])
    assert head["from"] == 1 and head["text"].startswith("줄1")
    miss = doc_excerpt(text, ["없는말"])
    assert miss["from"] == 1
    assert doc_excerpt("가" * 5000, ["가"], max_chars=100)["text"] == "가" * 100  # 한 줄이 너무 길어도 자른다
    assert doc_excerpt("a\nb\nc\nd", ["B"])["text"].startswith("a")  # 대소문자 무시


def test_excerpt_limit_in_characters():
    text = "\n".join("x" * 100 for _ in range(50))
    ex = doc_excerpt(text, [], max_chars=350)
    assert len(ex["text"]) <= 350 and ex["to"] == 3


def test_build_excerpts_reads_only_inside_corpus(tmp_path):
    corpus = tmp_path / "docs-copy"
    (corpus / "study").mkdir(parents=True)
    (corpus / "a.md").write_text("서론\nOllama를 쓴다\n끝\n", encoding="utf-8")
    (tmp_path / "secret.md").write_text("비밀", encoding="utf-8")
    recs = [{"qid": "q1", "must_include": ["Ollama"], "expected_sources": ["a.md", "none.md", "../secret.md", "study"]}]
    got = build_excerpts(recs, corpus)["q1"]
    assert "Ollama" in got["a.md"]["text"]
    assert got["none.md"] is None and got["../secret.md"] is None and got["study"] is None  # 없는 파일, 밖으로 나가는 경로, 폴더


def test_excerpts_in_html_have_no_pc_paths(folder, tmp_path):
    items = make_items(2)
    items[0].expected_sources = ["a.md"]
    run(folder, items)
    html = (folder / "review.html").read_text(encoding="utf-8")
    assert "docs-20261028" in html
    assert not re.search(r"[A-Za-z]:\\\\|/Users/|tmdgu", html)


# ---- 판정 기준 ------------------------------------------------------------------


def test_rubric_is_in_data_and_button_exists(folder):
    run(folder, make_items(2))
    d = data_of(folder)
    assert d["rubric"] == RUBRIC and len(RUBRIC) >= 5
    flat = " ".join(" ".join(sec["lines"]) + sec["title"] for sec in RUBRIC)
    for needle in ("eval/questions.yaml", "2026-10-29", "1단계 실험 중에는 바꾸지 않습니다", "만든 사람", "manual.yaml", "기준 의견"):
        assert needle in flat, needle
    assert '"판정 기준"' in tpl()


def test_rubric_matches_the_instruction_given_to_judges():
    from src.eval.judge import JUDGE_INSTRUCTION

    assert "정답 기준의 핵심을 맞게 답하면 합격" in JUDGE_INSTRUCTION
    flat = " ".join(" ".join(sec["lines"]) for sec in RUBRIC)
    assert "정답 기준의 핵심을 맞게 답하면 합격" in flat
    assert "재지 않은 값을 잰 것처럼 단정하면 불합격" in JUDGE_INSTRUCTION and "재지 않은 값을 잰 것처럼 단정하면 불합격" in flat


def test_readme_has_the_same_rubric_text():
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "eval" / "README.md").read_text(encoding="utf-8")
    assert "판정 기준" in readme
    for sec in RUBRIC:
        assert sec["title"] in readme, sec["title"]
        for line in sec["lines"]:
            assert line in readme, line


# ---- 기준 의견 ------------------------------------------------------------------


def make_export(tmp_path, folder, items=(), criteria=None, name="export.json"):
    body = {"run": folder.name, "items": list(items)}
    if criteria is not None:
        body["criteria"] = criteria
    p = tmp_path / name
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return p


def bids(folder):
    return sorted(json.loads((folder / "blind_map.json").read_text(encoding="utf-8")))


@pytest.fixture
def done(folder):
    items = make_items(4)
    for it in items:
        it.correct = True
    run(folder, items)
    return folder, items


def resummary(folder, items):
    state = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    return finalize(folder, items, state, 3, 0)


def test_criteria_import_is_separate_from_verdicts(done, tmp_path):
    folder, items = done
    ids = bids(folder)
    p = make_export(tmp_path, folder,
                    [{"bid": ids[0], "verdict": "합격", "reason": "맞음", "at": "t"}],
                    [{"bid": ids[0], "odd": True, "note": "핵심어가 너무 넓음", "at": "t"},
                     {"bid": ids[1], "odd": False, "note": "메모만 남김", "at": "t"}])
    assert import_human(folder, p) == 1
    assert len(load_human(folder)) == 1 and len(load_criteria(folder)) == 2
    human_text = (folder / "human.jsonl").read_text(encoding="utf-8")
    assert "핵심어가 너무 넓음" not in human_text and "odd" not in human_text
    summary = resummary(folder, items)
    assert "## 기준 의견(v3 후보)" in summary and "핵심어가 너무 넓음" in summary and "메모만 남김" in summary
    assert "이상함 체크" in summary and "메모만" in summary
    human_part = summary.split("## 사람 판정과의 일치율")[1].split("## 기준 의견")[0]
    assert "핵심어가 너무 넓음" not in human_part  # 일치율 절에 섞이지 않는다


def test_criteria_only_export_and_old_format_without_criteria(done, tmp_path):
    folder, items = done
    ids = bids(folder)
    assert import_human(folder, make_export(tmp_path, folder, [], [{"bid": ids[0], "odd": True, "note": "", "at": ""}])) == 0
    assert not (folder / "human.jsonl").exists() and len(load_criteria(folder)) == 1
    assert import_human(folder, make_export(tmp_path, folder, [{"bid": ids[1], "verdict": "불합격", "reason": "x", "at": ""}], None, "old.json")) == 1
    assert len(load_criteria(folder)) == 1  # 예전 형식 파일이 기존 기준 의견을 지우지 않는다


def test_clearing_a_criteria_entry_removes_it(done, tmp_path):
    folder, items = done
    ids = bids(folder)
    import_human(folder, make_export(tmp_path, folder, [], [{"bid": ids[0], "odd": True, "note": "n", "at": ""}]))
    import_human(folder, make_export(tmp_path, folder, [], [{"bid": ids[0], "odd": False, "note": "", "at": ""}], "clear.json"))
    assert load_criteria(folder) == {}
    assert "기준 의견(v3 후보)" not in resummary(folder, items)


def test_bad_criteria_rejects_everything(done, tmp_path):
    folder, _ = done
    ids = bids(folder)
    good_item = {"bid": ids[0], "verdict": "합격", "reason": "ok", "at": ""}
    cases = [
        [{"bid": ids[0], "odd": "예", "note": "", "at": ""}],
        [{"bid": "B999", "odd": True, "note": "", "at": ""}],
        [{"bid": ids[0], "odd": True, "note": "가" * 501, "at": ""}],
        [{"bid": ids[0], "odd": True, "note": 5, "at": ""}],
        ["문자열"],
    ]
    for crit in cases:
        with pytest.raises(HumanImportError):
            import_human(folder, make_export(tmp_path, folder, [good_item], crit))
        assert not (folder / "human.jsonl").exists() and not (folder / "criteria.jsonl").exists()
    with pytest.raises(HumanImportError):
        import_human(folder, make_export(tmp_path, folder, [good_item], {"bid": ids[0]}))


def test_criteria_import_is_idempotent_and_note_is_one_line(done, tmp_path):
    folder, _ = done
    ids = bids(folder)
    p = make_export(tmp_path, folder, [], [{"bid": ids[0], "odd": True, "note": "줄1\n줄2   끝", "at": "t"}])
    import_human(folder, p)
    first = (folder / "criteria.jsonl").read_text(encoding="utf-8")
    import_human(folder, p)
    assert (folder / "criteria.jsonl").read_text(encoding="utf-8") == first
    assert next(iter(load_criteria(folder).values()))["note"] == "줄1 줄2 끝"


def test_criteria_never_reach_html_or_judge_prompts(done, tmp_path):
    folder, items = done
    ids = bids(folder)
    import_human(folder, make_export(tmp_path, folder, [], [{"bid": ids[0], "odd": True, "note": "비공개-메모-표식", "at": ""}]))
    resummary(folder, items)
    assert "비공개-메모-표식" not in (folder / "review.html").read_text(encoding="utf-8")
    assert all("비공개-메모-표식" not in it.prompt for it in items)


def test_export_in_template_includes_criteria_and_keeps_verdicts_separate():
    t = tpl()
    assert "criteria: criteria" in t and "items: items" in t
    assert "기준 의견 (판정과 따로, 선택)" in t and "이 기준이 이상함" in t and "한 줄 메모" in t
    assert "S.crit[bid]" in t and "S.mine[bid]" in t  # 따로 저장

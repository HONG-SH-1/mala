"""내 판정을 저장하는 순간 면접관 판정이 가려져 있었는지(blind)를 기록하고, 일치율은 blind=true만으로 계산한다."""

import json
import re
import shutil
import subprocess

import pytest

from src.eval.judge import JudgeSpec, execute, finalize
from src.eval.judge_human import HumanImportError, import_human, load_human, next_blind
from src.eval.judge_report import TEMPLATE
from tests.test_eval_judge import NO, NOW, OK, FakeJudge, make_items


@pytest.fixture
def done(tmp_path):
    folder = tmp_path / "20261107-1000_t"
    folder.mkdir()
    items = make_items(4)
    for it in items:
        it.correct = True
    scripts = {"claude": [OK], "codex": [NO], "gemini": [OK]}  # 다수결은 늘 합격
    specs = [JudgeSpec(n, [None], lambda m, n=n: FakeJudge(n, "m", scripts[n]), ping=False) for n in scripts]
    execute(specs, items, folder, seed=3, sleep=lambda s: None, now=NOW)
    return folder, items


def ids_by_qid(folder):
    bm = json.loads((folder / "blind_map.json").read_text(encoding="utf-8"))
    return {v["id"]: bid for bid, v in bm.items()}


def export(tmp_path, folder, entries, name="export.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"run": folder.name, "items": entries}, ensure_ascii=False), encoding="utf-8")
    return p


def entry(bid, verdict, blind=None, reason="이유"):
    e = {"bid": bid, "verdict": verdict, "reason": reason, "at": "t"}
    if blind is not None:
        e["blind"] = blind
    return e


def summary_of(folder, items):
    state = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    return finalize(folder, items, state, 3, 0)


# ---- 가져오기 ----------------------------------------------------------------


def test_blind_flag_is_stored_per_verdict(done, tmp_path):
    folder, _ = done
    b = ids_by_qid(folder)
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], "합격", True), entry(b["q01"], "합격", False)]))
    rows = {r["id"]: r for r in load_human(folder).values()}
    assert rows["q00"]["blind"] is True and rows["q01"]["blind"] is False


def test_missing_blind_means_not_blind(done, tmp_path):
    folder, _ = done
    b = ids_by_qid(folder)
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], "합격")]))  # 예전 형식 파일
    assert next(iter(load_human(folder).values()))["blind"] is False


def test_non_boolean_blind_rejects_everything(done, tmp_path):
    folder, _ = done
    b = ids_by_qid(folder)
    for bad in ("true", 1, None, "예"):
        e = entry(b["q01"], "합격")
        e["blind"] = bad
        with pytest.raises(HumanImportError):
            import_human(folder, export(tmp_path, folder, [entry(b["q00"], "합격", True), e]))
        assert not (folder / "human.jsonl").exists()


def test_reimport_last_value_wins_for_blind_too(done, tmp_path):
    folder, _ = done
    b = ids_by_qid(folder)
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], "합격", True)], "a.json"))
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], "합격", False)], "b.json"))
    assert next(iter(load_human(folder).values()))["blind"] is False


# ---- 요약 -----------------------------------------------------------------------


def test_agreement_uses_only_blind_verdicts_and_lists_the_rest(done, tmp_path):
    folder, items = done
    b = ids_by_qid(folder)
    import_human(folder, export(tmp_path, folder, [
        entry(b["q00"], "합격", True),    # 다수결(합격)과 같음
        entry(b["q01"], "불합격", True),  # 다르다
        entry(b["q02"], "불합격", False),  # 임원 판정: 계산에서 빠져야 한다
        entry(b["q03"], "합격", False),    # 임원 판정
    ]))
    text = summary_of(folder, items)
    section = text.split("## 사람 판정과의 일치율")[1].split(chr(10) + "## ")[0]
    assert "블라인드 판정(면접관 판정이 가려진 상태에서 저장): 2건" in section
    assert "임원 판정(면접관 판정을 본 상태에서 저장): 2건" in section
    assert "| 다수결 | 1/2 (50%) | 1/1 (100%) | 0/1 (0%) |" in section  # 임원 판정까지 넣었다면 2/4가 된다
    listing = section.split("### 임원 판정 목록")[1]
    assert b["q02"] in listing and b["q03"] in listing
    assert b["q00"] not in listing and b["q01"] not in listing
    assert "q02 · 1회차" in listing and "불합격" in listing


def test_executive_list_shows_only_counts_and_list_not_agreement(done, tmp_path):
    folder, items = done
    b = ids_by_qid(folder)
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], "합격", False, reason="비공개-이유-표식")]))
    text = summary_of(folder, items)
    section = text.split("## 사람 판정과의 일치율")[1].split(chr(10) + "## ")[0]
    assert "블라인드 판정(면접관 판정이 가려진 상태에서 저장): 0건" in section
    assert "| 다수결 | - | - | - |" in section  # 블라인드 판정이 없으면 일치율은 비어 있다
    assert "비공개-이유-표식" not in section  # 목록은 번호, 질문, 회차, 판정만


def test_no_executive_section_when_all_blind(done, tmp_path):
    folder, items = done
    b = ids_by_qid(folder)
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], "합격", True)]))
    section = summary_of(folder, items).split("## 사람 판정과의 일치율")[1].split(chr(10) + "## ")[0]
    assert "임원 판정(면접관 판정을 본 상태에서 저장): 0건" in section and "임원 판정 목록" not in section


def test_old_rows_without_blind_field_count_as_executive(done):
    folder, items = done
    b = ids_by_qid(folder)
    bm = json.loads((folder / "blind_map.json").read_text(encoding="utf-8"))
    info = bm[b["q00"]]
    row = {"key": info["key"], "label": info["label"], "id": info["id"], "repeat": info["repeat"], "bid": b["q00"],
           "human_verdict": "합격", "human_reason": "x", "at": "t"}  # blind 필드가 없는 예전 행
    (folder / "human.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    section = summary_of(folder, items).split("## 사람 판정과의 일치율")[1].split(chr(10) + "## ")[0]
    assert "블라인드 판정(면접관 판정이 가려진 상태에서 저장): 0건" in section and "임원 판정(면접관 판정을 본 상태에서 저장): 1건" in section


# ---- 화면 코드 ------------------------------------------------------------------


def test_template_records_blind_on_save_and_exports_it():
    t = TEMPLATE.read_text(encoding="utf-8")
    assert "blind: decideBlind(S.mine[bid], chosen, revealed(it))" in t  # 저장하는 순간 보이는 상태였는지 + 재저장 규칙
    assert "blind: m.blind === true" in t and "blind: m.blind === true };" in t  # 불러오기와 내보내기
    assert "일치율에서 빠져" in t and "임원 판정" in t  # 보이는 상태에서 저장할 때의 안내
    assert "블라인드 판정" in t and "면접관 판정을 본 뒤 판정" in t


# ---- 다시 저장할 때의 규칙 ------------------------------------------------------------


def test_next_blind_rules():
    blind_saved = {"verdict": "합격", "reason": "a", "blind": True}
    seen_saved = {"verdict": "합격", "reason": "a", "blind": False}
    # 처음 저장: 가려져 있었으면 true, 보였으면 false
    assert next_blind(None, "합격", visible_now=False) is True
    assert next_blind(None, "합격", visible_now=True) is False
    # 블라인드로 저장한 건: 판정이 그대로면(이유 글만 고침) true 유지. 이미 보이는 상태여도 마찬가지
    assert next_blind(blind_saved, "합격", visible_now=True) is True
    # 판정이 바뀌면 false
    for new in ("불합격", "보류"):
        assert next_blind(blind_saved, new, visible_now=True) is False
    # 이미 블라인드가 아니던 건은 판정이 그대로여도 false 그대로
    assert next_blind(seen_saved, "합격", visible_now=True) is False
    # 필드가 없는 예전 저장분도 false
    assert next_blind({"verdict": "합격", "reason": "a"}, "합격", visible_now=True) is False


def test_next_blind_changing_back_does_not_restore_blind():
    first = {"verdict": "합격", "reason": "a", "blind": True}
    changed = {"verdict": "불합격", "reason": "a", "blind": next_blind(first, "불합격", True)}
    assert changed["blind"] is False
    assert next_blind(changed, "합격", True) is False  # 한 번 임원 판정이 된 건은 되돌려도 블라인드가 아니다


def test_reason_only_edit_stays_blind_end_to_end(done, tmp_path):
    """블라인드로 저장한 판정의 이유만 고쳐 다시 내보내면 일치율에 그대로 들어간다."""
    folder, items = done
    b = ids_by_qid(folder)
    first = {"verdict": "합격", "reason": "처음 이유", "blind": True}
    edited = {"verdict": "합격", "reason": "고친 이유", "blind": next_blind(first, "합격", True)}
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], edited["verdict"], edited["blind"], edited["reason"])]))
    section = summary_of(folder, items).split("## 사람 판정과의 일치율")[1].split(chr(10) + "## ")[0]
    assert "블라인드 판정(면접관 판정이 가려진 상태에서 저장): 1건" in section
    assert "임원 판정(면접관 판정을 본 상태에서 저장): 0건" in section


def test_verdict_change_moves_it_to_executive_list(done, tmp_path):
    folder, items = done
    b = ids_by_qid(folder)
    first = {"verdict": "합격", "reason": "a", "blind": True}
    now = next_blind(first, "불합격", True)
    import_human(folder, export(tmp_path, folder, [entry(b["q00"], "불합격", now)]))
    section = summary_of(folder, items).split("## 사람 판정과의 일치율")[1].split(chr(10) + "## ")[0]
    assert "블라인드 판정(면접관 판정이 가려진 상태에서 저장): 0건" in section and b["q00"] in section.split("### 임원 판정 목록")[1]


def js_blind_source() -> str:
    t = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"/\* BLIND-BEGIN \*/(.*?)/\* BLIND-END \*/", t, re.S)
    assert m, "템플릿에 BLIND-BEGIN / BLIND-END 표시가 없다"
    return m.group(1)


def test_js_decide_blind_block_is_pure():
    src = js_blind_source()
    for bad in ("document", "window", "S.", "localStorage"):
        assert bad not in src, bad


@pytest.mark.skipif(shutil.which("node") is None, reason="node가 없으면 JS 쪽 비교는 건너뜀 (브라우저 수동 확인 목록 참고)")
def test_js_decide_blind_matches_python_reference():
    prevs = [None, {"verdict": "합격", "blind": True}, {"verdict": "합격", "blind": False}, {"verdict": "불합격", "blind": True}, {"verdict": "합격"}]
    cases = [(p, v, vis) for p in prevs for v in ("합격", "불합격", "보류") for vis in (False, True)]
    runner = js_blind_source() + "\nvar cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" \
        "process.stdout.write(JSON.stringify(cases.map(function (c) { return decideBlind(c[0], c[1], c[2]); })));\n"
    res = subprocess.run([shutil.which("node"), "-e", runner], input=json.dumps(cases), capture_output=True,
                         text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == [next_blind(p, v, vis) for p, v, vis in cases]

"""review.html, 번호 부여, 회차별 표 테스트."""

import json
import re

import pytest

from src.eval.judge import JudgeSpec, ensure_blind_map, execute
from src.eval.judge_report import TEMPLATE, build_data, csp_hash, render_html, safe_json
from tests.test_eval_judge import NO, NOW, OK, FakeJudge, make_items

LABELS = ("라벨-표식-A", "라벨-표식-B", "라벨-표식-C")


def run(tmp_path, items, scripts=None, seed=3):
    scripts = scripts or {"claude": [OK], "codex": [NO], "gemini": [OK]}
    specs = [JudgeSpec(n, [None], lambda m, n=n: FakeJudge(n, "m", scripts[n]), ping=False) for n in scripts]
    return execute(specs, items, tmp_path, seed=seed, sleep=lambda s: None, now=NOW)


def html_of(tmp_path):
    return (tmp_path / "review.html").read_text(encoding="utf-8")


def data_of(html):
    block = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    return json.loads(block)


# ---- 번호 ----------------------------------------------------------------


def test_new_run_numbers_every_item_from_b001(tmp_path):
    items = make_items(4, labels=("A", "B"))
    ids = ensure_blind_map(tmp_path, items)
    assert sorted(ids.values()) == [f"B{n:03d}" for n in range(1, 9)]
    bm = json.loads((tmp_path / "blind_map.json").read_text(encoding="utf-8"))
    assert len(bm) == 8


def test_existing_numbers_never_change_and_new_ones_continue(tmp_path):
    items = make_items(4)
    (tmp_path / "blind_map.json").write_text(json.dumps({
        "#02": {"key": items[0].key, "label": "A", "id": items[0].qid, "repeat": 1},
        "#01": {"key": items[1].key, "label": "A", "id": items[1].qid, "repeat": 1},
    }), encoding="utf-8")
    ids = ensure_blind_map(tmp_path, items)
    assert ids[items[0].key] == "#02" and ids[items[1].key] == "#01"
    assert {ids[items[2].key], ids[items[3].key]} == {"#03", "#04"}
    assert ensure_blind_map(tmp_path, items) == ids  # 두 번 불러도 같다


def test_numbers_survive_resume(tmp_path):
    items = make_items(3)
    run(tmp_path, items)
    before = (tmp_path / "blind_map.json").read_text(encoding="utf-8")
    execute([JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "m", [OK]), ping=False)], items, tmp_path,
            seed=3, resume=True, sleep=lambda s: None, now=NOW)
    assert (tmp_path / "blind_map.json").read_text(encoding="utf-8") == before


# ---- 회차별 일치율 ----------------------------------------------------------


def test_repeat_table_counts(tmp_path):
    items = make_items(4)
    for it in items:
        it.repeat = 1 if int(it.qid[1:]) < 2 else 2
        it.key = f"A|{it.qid}|{it.repeat}"
        it.correct = True
    items[3].correct = False  # 2회차에 최종 불합격 한 건
    summary = run(tmp_path, items, {"claude": [OK], "codex": [NO]})
    assert "## 회차별 일치율" in summary
    assert "| 1회차 | 2/2 (100%) (2/2 (100%) / -) | 0/2 (0%) (0/2 (0%) / -) |" in summary
    # 2회차: claude는 합격만 주므로 최종 합격 1건 맞고 불합격 1건 틀림
    assert "| 2회차 | 1/2 (50%) (1/1 (100%) / 0/1 (0%)) |" in summary


def test_repeat_table_with_single_repeat(tmp_path):
    summary = run(tmp_path, make_items(2), {"claude": [OK]})
    assert "| 1회차 |" in summary and "2회차" not in summary


# ---- review.html ---------------------------------------------------------


def test_csp_meta_and_hashes_match_inline_content(tmp_path):
    run(tmp_path, make_items(3))
    html = html_of(tmp_path)
    assert "default-src 'none'" in html
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert f"script-src 'sha256-{csp_hash(script)}'" in html
    assert f"style-src 'sha256-{csp_hash(style)}'" in html
    assert "unsafe-inline" not in html and "unsafe-eval" not in html
    assert "__DATA__" not in html and "_HASH__" not in html


def test_no_external_requests_in_html(tmp_path):
    run(tmp_path, make_items(3))
    html = html_of(tmp_path)
    assert not re.search(r"https?://", html)
    assert not re.search(r"""\s(src|href|action)\s*=\s*["']""", html)
    assert "@import" not in html and "url(" not in html
    assert not re.search(r"<(link|iframe|img|form|object|embed)\b", html)
    assert "fetch(" not in html and "XMLHttpRequest" not in html and "WebSocket" not in html


def test_template_has_no_dangerous_dom_apis():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", ".setAttribute("):
        assert bad not in tpl, bad
    assert "textContent" in tpl


def test_label_key_filenames_and_blind_map_are_not_in_html(tmp_path):
    items = []
    for lab in LABELS:
        items += make_items(3, labels=(lab,))
    run(tmp_path, items)
    html = html_of(tmp_path)
    for lab in LABELS:
        assert lab not in html
    assert "blind_map" not in html and "|q0" not in html  # key 모양(라벨|id|회차)이 없다
    d = data_of(html)
    for rec in d["items"]:
        assert set(rec) == {"bid", "qid", "repeat", "qtype", "question", "must_include", "expected_sources", "retrieved_sources", "answer", "judges",
                            "majority", "note", "auto_correct", "correct", "final_source", "review", "reasons"}


def test_hostile_answer_cannot_break_out_of_data_block(tmp_path):
    items = make_items(2)
    evil = '</script><img src=x onerror=alert(1)><!--   & "quote" \\'
    items[0].answer = evil
    run(tmp_path, items)
    html = html_of(tmp_path)
    block = html.split('id="data">')[1].split("</script>")[0]
    assert "</script><img" not in html and "<" not in block and ">" not in block  # 글자 그대로의 태그는 없다
    assert html.count("</script>") == 2  # 데이터 블록 하나, 코드 블록 하나
    d = data_of(html)
    assert any(rec["answer"] == evil for rec in d["items"])


def test_data_shape_groups_and_queue(tmp_path):
    items = make_items(4, labels=LABELS)
    run(tmp_path, items)
    d = data_of(html_of(tmp_path))
    assert len(d["items"]) == 12 and d["judges"] == ["claude", "codex", "gemini"]
    assert all(len(g["bids"]) == 3 for g in d["groups"]) and len(d["groups"]) == 4
    assert sorted(b for g in d["groups"] for b in g["bids"]) == sorted(r["bid"] for r in d["items"])
    by_bid = {r["bid"]: r for r in d["items"]}
    assert set(d["queue"]) == {b for b, r in by_bid.items() if r["review"]}
    assert all(by_bid[b]["judges"]["codex"]["verdict"] == "불합격" for b in by_bid)


def test_orders_are_fixed_by_seed_and_differ_between_groups():
    recs = [{"bid": f"B{i:03d}", "qid": f"q{i // 3:02d}", "repeat": 1, "review": i % 2 == 0} for i in range(30)]
    a = build_data("run", 5, recs, ["claude"])
    assert a == build_data("run", 5, recs, ["claude"])  # 같은 시드면 같다
    assert build_data("run", 6, recs, ["claude"])["queue"] != a["queue"]
    orders = [tuple(b[-2:] for b in g["bids"]) for g in a["groups"]]
    # 묶음마다 세 번호의 상대 순서가 한 가지로 고정되지 않는다 (순서로 결과를 짐작할 수 없게)
    shapes = {tuple(sorted(range(3), key=lambda k, o=o: int(o[k]) % 3)) for o in orders}
    assert len(shapes) > 1


def test_safe_json_escapes_script_breakers():
    s = safe_json({"a": "</script>&  "})
    assert "<" not in s and ">" not in s and "&" not in s and " " not in s and " " not in s
    assert json.loads(s) == {"a": "</script>&  "}


def test_render_requires_blocks(tmp_path, monkeypatch):
    bad = tmp_path / "t.html"
    bad.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("src.eval.judge_report.TEMPLATE", bad)
    with pytest.raises(ValueError):
        render_html({})


def test_interrupted_run_still_writes_html(tmp_path):
    import threading

    stop = threading.Event()
    stop.set()
    execute([JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "m", [OK]), ping=False)], make_items(2), tmp_path,
            seed=1, sleep=lambda s: None, now=NOW, stop=stop)
    assert (tmp_path / "review.html").exists()

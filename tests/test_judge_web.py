"""progress.html — 생성, 원자적 쓰기, blind 숨김, 답 본문 없음, 끝난 상태에는 새로 고침 없음, 마지막 갱신 시각, 정리."""

import json
import re
import threading
from datetime import datetime, timedelta

import pytest

import src.scripts.eval_judge as ej
from src.eval import judge_human, judge_web
from src.eval.judge import JudgeSpec, build_items, ensure_blind_map, execute
from src.eval.judge_progress import Progress
from src.eval.judge_report import csp_hash
from src.eval.judge_web import PROGRESS_PAGE_SECONDS, ProgressPage, write_static
from src.eval.runner import Question
from tests.test_eval_judge import NO, NOW, OK, FakeJudge, make_items

REFRESH = 'http-equiv="refresh"'
VERDICT_WORDS = ("합격", "불합격", "보류", "갈림")


def page_of(folder):
    return (folder / "progress.html").read_text(encoding="utf-8")


def specs(scripts=None):
    scripts = scripts or {"claude": [OK], "codex": [NO], "gemini": [OK]}
    return [JudgeSpec(n, [None], lambda m, n=n: FakeJudge(n, "m", scripts[n]), ping=False) for n in scripts]


def run(folder, items, **kw):
    return execute(specs(), items, folder, seed=3, sleep=lambda s: None, now=NOW, **kw)


# ---- 생성, 끝난 화면 ---------------------------------------------------------------------


def test_page_is_created_and_a_finished_run_has_no_refresh(tmp_path):
    items = make_items(12)
    run(tmp_path, items)
    html = page_of(tmp_path)
    assert "끝남" in html and REFRESH not in html
    assert '<progress value="12" max="12">' in html and "12/12 (100%)" in html
    assert 'href="review.html"' in html and 'href="summary.html"' in html and 'href="summary.md"' not in html
    assert "새로 고침을 멈췄습니다" in html
    for name in ("claude", "codex", "gemini"):
        assert f"<td>{name}</td>" in html
    assert html.count("<tr><td>B") == 10  # 최근 10건만
    assert re.search(r"재시도 \d+회", html)


def test_recent_rows_come_from_progress_in_finishing_order_newest_first(tmp_path):
    items = make_items(4)
    ids = ensure_blind_map(tmp_path, items)
    prog = Progress(items, ids, ["claude"], out=lambda s: None)
    execute(specs({"claude": [OK]}), items, tmp_path, seed=3, sleep=lambda s: None, now=NOW, progress=prog)
    order = [ids[k] for k in prog.completed_order()]
    shown = re.findall(r"<tr><td>(B\d+)</td>", page_of(tmp_path))
    assert shown == list(reversed(order))


def test_judge_table_shows_counts_average_and_state(tmp_path):
    items = make_items(3)
    run(tmp_path, items)
    html = page_of(tmp_path)
    assert "3/3" in html and "끝남" in html and "건당 평균" in html


def test_stopped_judge_state_and_daily_limit_status(tmp_path):
    info = {"claude": {"status": "stopped", "stopped": "하루 한도, --resume으로 이어 하기"}, "codex": {"status": "active"},
            "gemini": {"status": "skipped", "reason": "금고 실패"}}
    items = make_items(2)
    state = {"judges": info, "ended": True, "blind": False}
    write_static(tmp_path, items, ensure_blind_map(tmp_path, items), state, now=NOW)
    html = page_of(tmp_path)
    assert "멈춤 (하루 한도)" in html and "건너뜀: 금고 실패" in html and REFRESH not in html


# ---- 마지막 갱신 시각 ------------------------------------------------------------------------


def test_last_update_time_is_big_and_first(tmp_path):
    items = make_items(2)
    t0 = datetime(2026, 11, 8, 3, 4, 5)
    page = ProgressPage(tmp_path, items, ensure_blind_map(tmp_path, items), ["claude"], blind=True, infos=dict, retries=lambda: 0,
                        started="2026-11-08T03:00:00", now=lambda: t0)
    page.write("running")
    html = page_of(tmp_path)
    assert 'class="stamp"' in html and "마지막 갱신" in html and "2026-11-08 03:04:05" in html
    assert html.index('class="stamp"') < html.index("class=\"card\"") < html.index("면접관별")  # 맨 위
    assert re.search(r"\.stamp \{ font-size: (2\d|3\d)px", html)  # 크게
    assert "강제로 끝난 실행일 수 있습니다" in html  # 실행 중 화면에는 알아채는 방법이 적혀 있다
    page.now = lambda: t0 + timedelta(seconds=5)
    page.write("running")
    assert "2026-11-08 03:04:10" in page_of(tmp_path)  # 쓸 때마다 시각이 바뀐다


def test_finished_page_also_shows_last_update_time(tmp_path):
    run(tmp_path, make_items(2))
    assert "2026-11-07 12:00:00" in page_of(tmp_path)  # NOW


# ---- 실행 중 화면과 간격 ----------------------------------------------------------------------


def test_running_page_has_refresh_and_no_links_and_writes_every_five_seconds(tmp_path):
    assert PROGRESS_PAGE_SECONDS == 5.0
    items = make_items(3)
    clock = {"t": 100.0}
    page = ProgressPage(tmp_path, items, ensure_blind_map(tmp_path, items), ["claude"], blind=False, infos=dict,
                        retries=lambda: 2, started="x", now=NOW, clock=lambda: clock["t"])
    page.tick()  # 처음엔 바로 쓴다
    first = page_of(tmp_path)
    assert f'<meta http-equiv="refresh" content="{int(PROGRESS_PAGE_SECONDS)}">' in first
    assert "실행 중" in first and 'href="review.html"' not in first and "재시도 2회" in first
    (tmp_path / "progress.html").write_text("MARK", encoding="utf-8")
    clock["t"] += 4.9
    page.tick()
    assert page_of(tmp_path) == "MARK"  # 5초 전에는 다시 쓰지 않는다
    clock["t"] += 0.2
    page.tick()
    assert page_of(tmp_path) != "MARK"


def test_page_is_written_at_start_so_it_exists_while_running(tmp_path):
    seen = {}
    items = make_items(2)

    class Peek(FakeJudge):
        def call(self, prompt):
            if "html" not in seen and (tmp_path / "progress.html").exists():
                seen["html"] = page_of(tmp_path)
            return super().call(prompt)

    execute([JudgeSpec("claude", [None], lambda m: Peek("claude", "m", [OK]), ping=False)], items, tmp_path, seed=1,
            sleep=lambda s: None, now=NOW)
    assert REFRESH in seen["html"] and "실행 중" in seen["html"]


# ---- 원자적 쓰기 ------------------------------------------------------------------------------


def test_atomic_write_keeps_the_old_page_if_replace_fails(tmp_path, monkeypatch):
    items = make_items(2)
    page = ProgressPage(tmp_path, items, ensure_blind_map(tmp_path, items), ["claude"], blind=True, infos=dict,
                        retries=lambda: 0, started="x", now=NOW)
    page.write("running")
    before = page_of(tmp_path)

    def boom(a, b):
        raise OSError("replace failed")

    monkeypatch.setattr(judge_human.os, "replace", boom)
    page.write("ended")  # 쓰기 실패가 실행을 멈추지 않는다
    assert page_of(tmp_path) == before  # 반쯤 쓴 파일이 보이지 않는다


def test_no_tmp_file_is_left_and_page_is_written_via_replace(tmp_path, monkeypatch):
    calls = []
    real = judge_human.os.replace
    monkeypatch.setattr(judge_human.os, "replace", lambda a, b: (calls.append((str(a), str(b))), real(a, b))[1])
    run(tmp_path, make_items(2))
    assert any(b.endswith("progress.html") and a.endswith("progress.html.tmp") for a, b in calls)
    assert not list(tmp_path.glob("*.tmp"))


# ---- blind ----------------------------------------------------------------------------------------


def test_blind_page_has_no_verdicts_or_split_marks(tmp_path):
    items = make_items(6)
    ids = ensure_blind_map(tmp_path, items)
    prog = Progress(items, ids, ["claude", "codex", "gemini"], blind=True, out=lambda s: None)
    execute(specs(), items, tmp_path, seed=3, sleep=lambda s: None, now=NOW, progress=prog)  # 코덱스만 불합격 → 갈림이 생긴다
    html = page_of(tmp_path)
    for w in VERDICT_WORDS:
        assert w not in html, w
    assert "<td>B" in html  # 번호, 질문, 회차는 보인다
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["blind"] is True


def test_non_blind_page_shows_verdicts_and_split(tmp_path):
    items = make_items(3)
    ids = ensure_blind_map(tmp_path, items)
    prog = Progress(items, ids, ["claude", "codex", "gemini"], blind=False, out=lambda s: None)
    execute(specs(), items, tmp_path, seed=3, sleep=lambda s: None, now=NOW, progress=prog)
    html = page_of(tmp_path)
    assert "합격" in html and "불합격" in html and "<th>갈림</th>" in html and "<td>갈림</td>" in html
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["blind"] is False


def test_old_run_without_blind_record_is_treated_as_blind(tmp_path):
    items = make_items(3)
    run(tmp_path, items)
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    state.pop("blind")  # 예전 실행
    write_static(tmp_path, items, ensure_blind_map(tmp_path, items), state, now=NOW)
    html = page_of(tmp_path)
    assert not any(w in html for w in VERDICT_WORDS)


# ---- 답 본문, 이유, 질문 본문은 없다 ---------------------------------------------------------------------


def test_no_answer_reason_or_question_text_and_everything_is_escaped(tmp_path):
    qs = [Question("q<script>x", "질문-본문-표식", "in_notes", ["a.md"], ["kw"])]
    recs = [{"label": "라벨-표식", "id": "q<script>x", "repeat": 1, "answer": "답-본문-표식 <b>x</b>", "auto_correct": True, "correct": True}]
    items = build_items(recs, qs)
    reason = '{"verdict":"합격","reason":"이유-글-표식","cause":"없음"}'
    execute([JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "m", [reason]), ping=False)], items, tmp_path, seed=1,
            sleep=lambda s: None, now=NOW, progress=Progress(items, ensure_blind_map(tmp_path, items), ["claude"], out=lambda s: None))
    html = page_of(tmp_path)
    for marker in ("답-본문-표식", "이유-글-표식", "질문-본문-표식", "라벨-표식"):
        assert marker not in html, marker
    assert "<script" not in html and "q&lt;script&gt;x" in html  # 질문 id도 이스케이프


def test_judge_notes_are_escaped(tmp_path):
    items = make_items(1)
    state = {"judges": {"claude": {"status": "skipped", "reason": "<img src=x onerror=1>"}}, "ended": True, "blind": True}
    write_static(tmp_path, items, ensure_blind_map(tmp_path, items), state, now=NOW)
    html = page_of(tmp_path)
    assert "<img" not in html and "&lt;img" in html


# ---- CSP -------------------------------------------------------------------------------------------------


def test_csp_hash_matches_style_and_nothing_external(tmp_path):
    run(tmp_path, make_items(2))
    html = page_of(tmp_path)
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    assert "default-src 'none'" in html and f"style-src 'sha256-{csp_hash(style)}'" in html
    assert "unsafe-inline" not in html and "unsafe-eval" not in html
    assert "<script" not in html and "http://" not in html and "https://" not in html and "src=" not in html
    assert "style=" not in html  # 인라인 style 속성은 CSP가 막는다 → 클래스로만 꾸민다
    assert "_HASH__" not in html and "__BODY__" not in html and "__REFRESH__" not in html


# ---- Ctrl+C, 멈춤 ------------------------------------------------------------------------------------------


def test_ctrl_c_leaves_a_stopped_page_without_refresh(tmp_path, monkeypatch):
    from src.eval import judge as J

    gate = threading.Event()
    monkeypatch.setattr(J, "terminate_children", lambda *a, **k: gate.set())

    class Slow:
        name, model = "claude", "haiku"

        def call(self, prompt):
            gate.wait(10)
            raise J.CallError("transient", "exit1")

    class Prog:
        blind = True

        def judge_ready(self, *a):
            pass

        def on_row(self, *a):
            pass

        def judge_out(self, *a):
            pass

        def eta_text(self):
            return "계산 중"

        def completed_order(self):
            return []

        def tick(self):
            raise KeyboardInterrupt

    execute([JudgeSpec("claude", [None], lambda m: Slow(), ping=False)], make_items(2), tmp_path, seed=1, sleep=lambda s: None,
            now=NOW, progress=Prog())
    html = page_of(tmp_path)
    assert "멈춤 (Ctrl+C)" in html and REFRESH not in html and 'href="summary.html"' in html


def test_run_json_is_written_at_start_with_ended_false(tmp_path):
    seen = {}

    class Peek(FakeJudge):
        def call(self, prompt):
            if "state" not in seen:
                seen["state"] = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
            return super().call(prompt)

    items = make_items(2)
    execute([JudgeSpec("claude", [None], lambda m: Peek("claude", "m", [OK]), ping=False)], items, tmp_path, seed=1,
            sleep=lambda s: None, now=NOW)
    assert seen["state"]["ended"] is False and len(seen["state"]["items"]) == 2  # 강제 종료돼도 이어하기, 다시 만들기가 가능하다
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["ended"] is True


# ---- --rebuild, --resume 이 남은 '실행 중' 화면을 정리한다 ------------------------------------------------------------


@pytest.fixture
def real_folder(tmp_path):
    qfile = tmp_path / "q.yaml"
    qfile.write_text("- id: q00\n  question: 질문0\n  type: in_notes\n  expected_sources: [a.md]\n  must_include: [kw]\n"
                     "- id: q01\n  question: 질문1\n  type: not_in_notes\n  expected_sources: []\n  must_include: []\n", encoding="utf-8")
    rec = tmp_path / "docs-run_rescored-v2.jsonl"
    rec.write_text("".join(json.dumps({"label": "L", "id": f"q0{i}", "repeat": 1, "answer": f"답{i}", "auto_correct": True,
                                       "correct": True}) + "\n" for i in range(2)), encoding="utf-8")
    folder = tmp_path / "judge" / "20261107-1000_t"
    folder.mkdir(parents=True)
    (folder / "inputs.json").write_text(json.dumps({"files": [str(rec)], "judges": ["claude"], "seed": 3, "limit": None,
                                                    "questions": str(qfile)}), encoding="utf-8")
    items = ej.build_items([r for r in ej.load_records(str(rec))], ej.load_questions(str(qfile)))
    items = ej.shuffle_items(items, 3)
    execute([JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "m", [OK]), ping=False)], items, folder, seed=3,
            sleep=lambda s: None, now=NOW)
    return folder, items, tmp_path


def plant_stale_running_page(folder, items):
    stale = judge_web.build_data(folder, items, ensure_blind_map(folder, items), ["claude"], {}, phase="running", interrupted=False,
                                 killed=False, blind=True, retries=0, started="x", stamp=datetime(2020, 1, 1))
    judge_web.write_page(folder, stale)
    assert REFRESH in page_of(folder) and "2020-01-01" in page_of(folder)


def test_rebuild_rewrites_a_stale_running_page(real_folder):
    folder, items, _ = real_folder
    plant_stale_running_page(folder, items)
    ej.rebuild(folder)
    html = page_of(folder)
    assert REFRESH not in html and "끝남" in html and "2020-01-01" not in html and 'href="review.html"' in html


def test_rebuild_of_a_force_closed_run_cleans_only_the_page(real_folder):
    folder, items, _ = real_folder
    state = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    state["ended"] = False  # 창을 닫아 강제로 끝난 실행
    (folder / "run.json").write_text(json.dumps(state), encoding="utf-8")
    for name in ("summary.md", "summary.html", "review.html"):
        (folder / name).unlink()
    plant_stale_running_page(folder, items)
    assert ej.rebuild(folder) == ""  # 결과 파일은 만들지 않는다
    html = page_of(folder)
    assert REFRESH not in html and "멈춤 (강제 종료로 보임)" in html
    assert 'href="summary.html"' not in html and 'href="review.html"' not in html  # 없는 파일로 가는 링크는 보여 주지 않는다
    assert not (folder / "summary.md").exists()


def test_resume_cleans_the_page_before_waiting_for_a_key(real_folder, monkeypatch, capsys):
    folder, items, tmp_path = real_folder
    plant_stale_running_page(folder, items)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("JUDGE_WORKDIR", str(work))
    monkeypatch.setattr(ej, "JUDGE_DIR", tmp_path / "judge")
    monkeypatch.setattr(ej, "load_dotenv", lambda *a, **k: None)
    captured = {}

    def fake_build(names, workdir, rpm):
        captured["html"] = page_of(folder)  # 키를 묻는 자리: 아직 실행 전
        return [JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "m", [OK]), ping=False)], []

    monkeypatch.setattr(ej, "_build_specs", fake_build)
    assert ej.main(["--resume", str(folder)]) == 0
    assert REFRESH not in captured["html"] and "2020-01-01" not in captured["html"] and "끝남" in captured["html"]
    assert REFRESH not in page_of(folder)  # 이어하기가 끝난 뒤에도 끝난 상태


# ---- --open --------------------------------------------------------------------------------------------------------


def test_open_is_called_once_after_the_first_page_and_only_with_the_option(tmp_path):
    items = make_items(2)
    seen = []
    run(tmp_path, items, on_page=lambda: seen.append((tmp_path / "progress.html").exists()))
    assert seen == [True]


def test_open_page_uses_default_browser_and_survives_failure(tmp_path, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    ej._open_page(tmp_path / "progress.html")
    assert opened and opened[0].startswith("file:///")

    def boom(url):
        raise RuntimeError("no browser")

    monkeypatch.setattr("webbrowser.open", boom)
    ej._open_page(tmp_path / "progress.html")  # 실패해도 예외가 나가지 않는다
    assert "브라우저를 열지 못했습니다" in capsys.readouterr().out


# ---- 시험 실행에서 나온 버그: Ctrl+C로 멈춘 실행 -----------------------------------------------------------------------


def ctrl_c_run(folder, monkeypatch, *, hang=False, n_items=10, stop_after=2):
    """claude, codex가 stop_after건을 끝낸 뒤 Ctrl+C. 이어서 도는 건은 자식이 끝나서 실패로 돌아온다.
    hang이면 claude의 호출이 grace 안에 안 끝난다 (윈도우에서 .cmd 껍데기만 죽고 손자가 남는 경우)."""
    from src.eval import judge as J

    gate = threading.Event()
    monkeypatch.setattr(J, "terminate_children", lambda *a, **k: None if hang else gate.set())
    monkeypatch.setattr(J, "STOP_GRACE_SECONDS", 0.3)

    class Stopper(FakeJudge):
        def call(self, prompt):
            if len(self.calls) >= stop_after:
                gate.wait(5)
                if self.name == "claude" and hang:
                    hung.wait(10)
                raise J.CallError("transient", "exit1")  # 자식이 죽어서 나는 실패
            return super().call(prompt)

    hung = threading.Event()
    items = make_items(n_items)
    ids = ensure_blind_map(folder, items)

    class CtrlC(Progress):
        def tick(self):
            if len(self.completed) >= stop_after:
                raise KeyboardInterrupt

    prog = CtrlC(items, ids, ["claude", "codex"], blind=False, out=lambda s: None)
    scripts = {"claude": [OK], "codex": [NO]}
    sp = [JudgeSpec(n, [None], lambda m, n=n: Stopper(n, "m", scripts[n]), ping=False) for n in scripts]
    summary = execute(sp, items, folder, seed=3, sleep=lambda s: None, now=NOW, progress=prog)
    hung.set()
    return items, summary


def test_bug1_page_after_ctrl_c_counts_finished_items_and_lists_them(tmp_path, monkeypatch):
    ctrl_c_run(tmp_path, monkeypatch)
    html = page_of(tmp_path)
    assert "2/10 (20%)" in html and '<progress value="2" max="10">' in html
    assert "아직 없음" not in html and html.count("<tr><td>B") == 2  # 최근 목록에도 끝난 두 건
    assert "멈춤 (Ctrl+C)" in html and REFRESH not in html


def test_bug2_a_judge_that_started_stays_stopped_never_skipped(tmp_path, monkeypatch):
    ctrl_c_run(tmp_path, monkeypatch, hang=True)  # claude 스레드가 grace 안에 안 끝난다
    state = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert state["judges"]["claude"]["status"] == "stopped"
    assert "건너뜀" not in page_of(tmp_path) and "멈춤: 사용자가 중단(Ctrl+C)" in page_of(tmp_path)


def test_bug2_rebuild_of_an_old_folder_that_recorded_skipped_shows_stopped(tmp_path):
    items = make_items(4)
    ids = ensure_blind_map(tmp_path, items)
    (tmp_path / "judge_claude.jsonl").write_text(
        "".join(json.dumps({"key": it.key, "verdict": "합격", "sec": 1.0}) + "\n" for it in items[:2]), encoding="utf-8")
    state = {"judges": {"claude": {"status": "skipped", "model": None, "reason": "사용자가 중단(Ctrl+C), --resume으로 이어 하기"},
                        "codex": {"status": "skipped", "model": None, "reason": "시작 못 함"}},
             "interrupted": True, "ended": True, "blind": True}
    write_static(tmp_path, items, ids, state, now=NOW)
    html = page_of(tmp_path)
    assert "멈춤: 사용자가 중단(Ctrl+C)" in html and "<td>2/4</td>" in html  # 판정을 낸 면접관은 멈춤, 끝난 건도 센다
    assert "건너뜀: 시작 못 함" in html  # 시작도 못 한 면접관만 건너뜀
    assert "2/4 (50%)" in html


def test_bug3_interrupted_call_is_not_counted_as_a_retry(tmp_path, monkeypatch):
    ctrl_c_run(tmp_path, monkeypatch)
    log = tmp_path / "retries.log"
    assert not log.exists() or log.read_text(encoding="utf-8").strip() == ""
    assert "재시도 0회" in page_of(tmp_path)


def test_bug4_unrun_items_are_remaining_not_unavailable_and_not_for_humans(tmp_path, monkeypatch):
    _items, summary = ctrl_c_run(tmp_path, monkeypatch)
    assert "남은 건 8 (--resume으로 이어 하기)" in summary
    assert "| claude | 1/2 (50%) |" in summary or "판정 불가" in summary  # 표는 그대로 있다
    row = next(ln for ln in summary.splitlines() if ln.startswith("| claude | ") and "%" in ln)
    assert row.rstrip().endswith("| 0 | 0 |")  # 보류 0, 판정 불가 0 (안 돌린 건을 판정 불가로 세지 않는다)
    review = (tmp_path / "review.md").read_text(encoding="utf-8")
    assert review.count("\n## B") + review.startswith("## B") == 2  # 끝난 두 건(갈림)만
    maj = [json.loads(ln) for ln in (tmp_path / "majority.jsonl").read_text(encoding="utf-8").splitlines()]
    remaining = [m for m in maj if m["note"] == "남은 건"]
    assert len(remaining) == 8 and not any(m["review"] for m in remaining)
    assert f"사람이 볼 건수: 2" in summary
    data = json.loads(re.search(r'id="data">(.*?)</script>', (tmp_path / "review.html").read_text(encoding="utf-8"), re.S).group(1))
    assert len(data["queue"]) == 2  # 내 판정 차례에도 안 들어간다


# ---- 이동 줄, summary.html -----------------------------------------------------------------------------------------------


def nav_links(html):
    m = re.search(r'<nav class="nav">(.*?)</nav>', html, re.S)
    assert m, "이동 줄이 없다"
    return m.group(1)


def test_all_three_pages_have_the_same_nav_line_at_the_top(tmp_path):
    summary = run(tmp_path, make_items(3))
    for fname, here, others in (("progress.html", "진행 화면", ("review.html", "summary.html")),
                                ("review.html", "결과 보기", ("progress.html", "summary.html")),
                                ("summary.html", "요약", ("progress.html", "review.html"))):
        html = (tmp_path / fname).read_text(encoding="utf-8")
        nav = nav_links(html)
        assert f"<b>{here}</b>" in nav  # 지금 화면은 굵게
        for o in others:
            assert f'href="{o}"' in nav  # 같은 폴더 상대 링크
        assert html.index("<nav") < html.index("마지막 갱신" if fname == "progress.html" else "<h1")
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == summary  # md는 그대로


def test_summary_html_has_same_content_same_csp_and_no_script(tmp_path):
    run(tmp_path, make_items(3))
    html = (tmp_path / "summary.html").read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    assert "default-src 'none'" in html and f"style-src 'sha256-{csp_hash(style)}'" in html
    assert "<script" not in html and "unsafe-inline" not in html and REFRESH not in html and "style=" not in html
    assert not re.search(r"https?://", html) and not re.search(r"\s(src|action)\s*=", html)
    assert "<h1>면접관 요약</h1>" in html and "<h2>면접관 상태</h2>" in html and "<table>" in html
    assert "대상 건수: 3" in html


def test_markdown_to_html_escapes_everything():
    out = judge_web.markdown_to_html("<script>alert(1)</script> **굵게** [글](http://u/x?a=1&b=2)\n\n| a<b | c |\n|---|---|\n| <i>x</i> | `<y>` |")
    assert "<script" not in out and "<i>" not in out and "<y>" not in out
    assert "&lt;script&gt;" in out and "<strong>굵게</strong>" in out and "a&lt;b" in out and "&amp;b=2" in out


def test_rebuild_regenerates_summary_html_and_keeps_md_untouched(real_folder):
    folder, items, _ = real_folder
    (folder / "summary.html").unlink()
    before = (folder / "summary.md").read_text(encoding="utf-8")
    ej.rebuild(folder)
    assert "<h1>면접관 요약</h1>" in (folder / "summary.html").read_text(encoding="utf-8")
    assert (folder / "summary.md").read_text(encoding="utf-8") == before


def test_progress_page_final_links_go_to_summary_html_not_md(tmp_path):
    run(tmp_path, make_items(2))
    html = page_of(tmp_path)
    assert 'href="summary.html"' in html and "summary.md" not in html


# ---- 없는 폴더, 잘못된 경로 ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["--rebuild", "--resume"])
def test_missing_folder_gives_a_short_message(flag, tmp_path, capsys):
    bad = str(tmp_path / "없는폴더")
    assert ej.main([flag, bad]) == 1
    err = capsys.readouterr().err
    assert err.strip() == f"폴더가 없습니다: {bad}"
    assert "Error" not in err and "Traceback" not in err


def test_import_human_missing_folder_or_file(tmp_path, capsys, real_folder):
    folder, _items, _ = real_folder
    bad = str(tmp_path / "없는폴더")
    assert ej.main(["--import-human", bad, "x.json"]) == 1
    assert capsys.readouterr().err.strip() == f"폴더가 없습니다: {bad}"
    assert ej.main(["--import-human", str(folder), str(tmp_path / "없는.json")]) == 1
    assert capsys.readouterr().err.strip() == f"파일이 없습니다: {tmp_path / '없는.json'}"


def test_a_file_path_or_a_non_run_folder_is_rejected_with_a_short_message(tmp_path, capsys):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert ej.main(["--rebuild", str(f)]) == 1
    assert capsys.readouterr().err.strip() == f"폴더가 없습니다: {f}"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ej.main(["--resume", str(empty)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("실행 폴더가 아닙니다") and "inputs.json" in err and "run.json" in err and "Traceback" not in err


# ---- 창을 닫아 강제로 끝난 폴더: run.json에 면접관 기록이 없어도 판정 파일을 읽는다 ------------------------------------------------


def force_closed(folder, keep_rows=1):
    """창을 닫은 폴더 모양: run.json은 시작할 때 쓴 것(judges 비어 있음, ended false), 판정 줄은 파일에 남아 있다."""
    state = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    state["judges"] = {}
    state["ended"] = False
    (folder / "run.json").write_text(json.dumps(state), encoding="utf-8")
    lines = (folder / "judge_claude.jsonl").read_text(encoding="utf-8").splitlines()[:keep_rows]
    (folder / "judge_claude.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in ("summary.md", "summary.html", "review.html", "review.md", "majority.jsonl"):
        (folder / name).unlink(missing_ok=True)
    (folder / "retries.log").write_text("2026-11-07T23:21:17\tclaude\thaiku\texit3221225786\ttry1\twait2\n", encoding="utf-8")


def test_force_closed_folder_page_reads_the_judge_files(real_folder):
    folder, items, _ = real_folder
    force_closed(folder)
    assert ej.rebuild(folder) == ""
    html = page_of(folder)
    assert "멈춤 (강제 종료로 보임)" in html and REFRESH not in html
    assert "1/2 (50%)" in html and '<progress value="1" max="2">' in html  # 끝난 건
    assert "<td>claude</td>" in html and "<td>1/2</td>" in html  # 면접관 표가 채워진다
    assert "아직 없음" not in html and html.count("<tr><td>B") == 1  # 최근 목록
    assert "재시도 1회" in html


def test_force_closed_folder_does_not_wait_for_judges_that_never_started(real_folder):
    folder, items, _ = real_folder
    force_closed(folder, keep_rows=2)
    inputs = json.loads((folder / "inputs.json").read_text(encoding="utf-8"))
    inputs["judges"] = ["claude", "codex", "gemini"]  # 셋을 시켰지만 claude만 판정 줄을 남겼다
    (folder / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    ej.rebuild(folder)
    html = page_of(folder)
    assert "2/2 (100%)" in html  # claude가 낸 판정으로 센다
    assert "<td>codex</td>" in html and "시작 기록 없음" in html  # 표에는 보이되 시작 기록이 없다고
    assert "<td>claude</td>" in html and "멈춤 (강제 종료)" in html

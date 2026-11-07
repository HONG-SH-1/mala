"""진행 표시 테스트 (가짜 시계, 가짜 출력)."""

import json

from src.eval.judge import (
    JudgeSpec,
    CallError,
    CallResult,
    ensure_blind_map,
    execute,
    pending_counts,
)
from src.eval.judge_progress import Progress, format_duration, load_history

from tests.test_eval_judge import NOW, NO, OK, FakeJudge, make_items


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_progress(items, tmp_path, judges=("claude", "codex", "gemini"), **kw):
    ids = ensure_blind_map(tmp_path, items)
    lines: list[str] = []
    clock = kw.pop("clock", Clock())
    p = Progress(items, ids, list(judges), out=lines.append, clock=clock, **kw)
    return p, lines, ids


def row(it, verdict, sec=5.0):
    return {"key": it.key, "verdict": verdict, "sec": sec}


def ready_all(p, names=("claude", "codex", "gemini")):
    for n in names:
        p.judge_ready(n)


def test_line_only_after_all_active_judges_finish(tmp_path):
    items = make_items(2)
    p, lines, ids = make_progress(items, tmp_path)
    ready_all(p)
    p.on_row("claude", row(items[0], "합격"))
    p.on_row("codex", row(items[0], "합격"))
    assert lines == []  # gemini가 아직
    p.on_row("gemini", row(items[0], "불합격"))
    assert len(lines) == 1
    q = items[0].qid
    assert lines[0] == f"[1/2] {ids[items[0].key]} {q} 1회차 — claude 합격, codex 합격, gemini 불합격 (갈림)"
    p.on_row("gemini", row(items[1], "합격"))
    p.on_row("claude", row(items[1], "합격"))
    p.on_row("codex", row(items[1], "합격"))
    assert lines[1].startswith("[2/2]") and "(갈림)" not in lines[1]


def test_each_item_printed_once_and_counts_in_order(tmp_path):
    items = make_items(3)
    p, lines, _ = make_progress(items, tmp_path, judges=("claude",))
    p.judge_ready("claude")
    for it in items:
        p.on_row("claude", row(it, "합격"))
    p.on_row("claude", row(items[0], "합격"))  # 같은 건이 또 와도 다시 안 찍는다
    assert [l.split("]")[0] for l in lines] == ["[1/3", "[2/3", "[3/3"]


def test_waits_for_pending_judges_then_flushes(tmp_path):
    items = make_items(1)
    p, lines, _ = make_progress(items, tmp_path, judges=("claude", "codex"))
    p.judge_ready("claude")
    p.on_row("claude", row(items[0], "합격"))
    assert lines == []  # codex가 시작 확인 중이면 누가 켜질지 모른다
    p.judge_ready("codex")
    p.on_row("codex", row(items[0], "합격"))
    assert len(lines) == 1


def test_skipped_or_stopped_judge_is_left_out(tmp_path):
    items = make_items(2)
    p, lines, _ = make_progress(items, tmp_path, judges=("claude", "codex", "gemini"))
    p.judge_ready("claude")
    p.judge_out("codex")  # 건너뜀
    p.judge_ready("gemini")
    p.on_row("claude", row(items[0], "합격"))
    p.on_row("gemini", row(items[0], "합격"))
    assert len(lines) == 1 and "codex" not in lines[0]
    p.on_row("claude", row(items[1], "합격"))
    assert len(lines) == 1
    p.judge_out("gemini")  # 멈추면 나머지만으로 센다
    assert len(lines) == 2 and lines[1].startswith("[2/2]")


def test_resume_counts_done_items_without_printing_them(tmp_path):
    items = make_items(3)
    p, lines, _ = make_progress(items, tmp_path, judges=("claude",))
    p.judge_ready("claude", {items[0].key: "합격", items[1].key: "합격"})
    assert lines == []
    p.on_row("claude", row(items[2], "합격"))
    assert lines[0].startswith("[3/3]")


def test_blind_hides_verdicts_and_split(tmp_path):
    items = make_items(1)
    p, lines, ids = make_progress(items, tmp_path, blind=True)
    ready_all(p)
    p.on_row("claude", row(items[0], "합격"))
    p.on_row("codex", row(items[0], "불합격"))
    p.on_row("gemini", row(items[0], "합격"))
    assert lines == [f"[1/1] {ids[items[0].key]} {items[0].qid} 1회차 — 끝남"]
    assert "합격" not in lines[0] and "갈림" not in lines[0]


def test_output_never_has_answer_reason_or_label(tmp_path):
    items = make_items(2, labels=("접두어-라벨",))
    items[0].answer = "비밀답변-표식"
    p, lines, _ = make_progress(items, tmp_path)
    ready_all(p)
    for it in items:
        for n in ("claude", "codex", "gemini"):
            r = row(it, "합격")
            r["reason"] = "이유-표식"
            p.on_row(n, r)
    p.clock.t = 100
    p.tick()
    text = "\n".join(lines + [p.start_line()])
    for needle in ("비밀답변-표식", "이유-표식", "접두어-라벨", "baseline"):
        assert needle not in text


def test_tick_every_30_seconds_with_average_and_eta(tmp_path):
    items = make_items(10)
    clock = Clock()
    p, lines, _ = make_progress(items, tmp_path, judges=("claude", "codex"), clock=clock)
    ready_all(p, ("claude", "codex"))
    for it in items[:4]:
        p.on_row("claude", row(it, "합격", sec=5.0))
    for it in items[:3]:
        p.on_row("codex", row(it, "합격", sec=10.0))
    clock.t = 29
    p.tick()
    assert not [l for l in lines if l.startswith("진행")]
    clock.t = 31
    p.tick()
    line = lines[-1]
    assert "claude 4/10" in line and "codex 3/10" in line
    assert "claude 5.0초" in line and "codex 10.0초" in line
    assert "약 70초" in line  # codex: 남은 7건 x 10초가 가장 느림
    clock.t = 40
    p.tick()
    assert lines[-1] == line or sum(1 for l in lines if l.startswith("진행")) == 1  # 간격 안에서는 다시 안 찍음


def test_eta_is_pending_when_too_few_samples(tmp_path):
    items = make_items(5)
    p, _, _ = make_progress(items, tmp_path, judges=("claude",))
    p.judge_ready("claude")
    p.on_row("claude", row(items[0], "합격"))
    assert "계산 중" in p.summary_line()


def test_gemini_minimum_interval_is_used(tmp_path):
    items = make_items(10)
    p, _, _ = make_progress(items, tmp_path, judges=("gemini",), min_sec={"gemini": 15.0})
    p.judge_ready("gemini")
    for it in items[:5]:
        p.on_row("gemini", row(it, "합격", sec=2.0))
    assert "약 75초" in p.summary_line()  # 남은 5건 x max(2.0, 15.0)


def test_start_line_uses_previous_run_times(tmp_path):
    items = make_items(10)
    p, _, _ = make_progress(items, tmp_path, judges=("claude", "codex"), expect={"claude": 5.0, "codex": 12.0})
    assert "약 2분" in p.start_line() and "claude 5.0초" in p.start_line()
    assert "이전 기록 없음" in make_progress(items, tmp_path, judges=("claude",))[0].start_line()
    only_codex, _, _ = make_progress(items, tmp_path, judges=("claude", "codex"), expect={"codex": 12.0})
    assert "이전 기록 없음 (claude)" in only_codex.start_line()
    # 이어하기: 남은 건 수로 계산
    assert "약 24초" in p.start_line({"claude": 2, "codex": 2})


def test_load_history_uses_latest_other_run_with_enough_rows(tmp_path):
    def write(name, judge, n, sec):
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        with (d / f"judge_{judge}.jsonl").open("a", encoding="utf-8") as f:
            for i in range(n):
                f.write(json.dumps({"key": f"k{i}", "verdict": "합격", "sec": sec}) + "\n")

    write("20261101-1000", "claude", 10, 4.0)
    write("20261102-1000", "claude", 3, 99.0)  # 5건 미만이라 안 씀
    write("20261103-1000", "claude", 10, 8.0)  # 자기 자신(제외)
    write("20261101-1000", "codex", 6, 12.0)
    got = load_history(tmp_path, tmp_path / "20261103-1000", ["claude", "codex", "gemini"])
    assert got == {"claude": 4.0, "codex": 12.0}
    assert load_history(tmp_path / "없는폴더", None, ["claude"]) == {}


def test_format_duration():
    assert format_duration(30) == "약 30초" and format_duration(600) == "약 10분"


def test_execute_prints_lines_end_to_end(tmp_path):
    items = make_items(3)
    ids = ensure_blind_map(tmp_path, items)
    lines: list[str] = []
    names = ["claude", "codex"]
    p = Progress(items, ids, names, out=lines.append)
    specs = [
        JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "haiku", [OK]), ping=False),
        JudgeSpec("codex", ["c1"], lambda m: FakeJudge("codex", "c1", [NO]), ping=False),
    ]
    execute(specs, items, tmp_path, seed=1, sleep=lambda s: None, now=NOW, progress=p)
    item_lines = [l for l in lines if l.startswith("[")]
    assert len(item_lines) == 3 and all("(갈림)" in l for l in item_lines)
    assert item_lines[-1].startswith("[3/3]")


def test_execute_skipped_judge_does_not_block_lines(tmp_path):
    items = make_items(2)
    ids = ensure_blind_map(tmp_path, items)
    lines: list[str] = []
    p = Progress(items, ids, ["claude", "codex"], out=lines.append)
    specs = [
        JudgeSpec("claude", [None], lambda m: FakeJudge("claude", "haiku", [OK]), ping=False),
        JudgeSpec("codex", ["c1"], lambda m: FakeJudge("codex", "c1", [CallError("auth", 401)])),
    ]
    execute(specs, items, tmp_path, seed=1, sleep=lambda s: None, now=NOW, progress=p)
    assert len([l for l in lines if l.startswith("[")]) == 2


def test_pending_counts(tmp_path):
    items = make_items(3)
    (tmp_path / "judge_claude.jsonl").write_text(
        json.dumps({"key": items[0].key, "verdict": "합격"}) + "\n" + json.dumps({"key": items[1].key, "verdict": "판정불가"}) + "\n",
        encoding="utf-8",
    )
    assert pending_counts(tmp_path, items, ["claude", "codex"]) == {"claude": 2, "codex": 3}

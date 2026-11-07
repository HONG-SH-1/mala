"""실행 중 진행 표시.

- 켜진 면접관이 모두 마친 건마다 한 줄. 답 본문, 이유, 결과 라벨은 찍지 않는다.
- 30초마다 면접관별 진행, 건당 평균 초, 남은 예상 시간 한 줄.
- 시작할 때 이전 실행의 건당 시간으로 먼저 예상한다.
- blind면 판정과 (갈림)을 숨긴다.

judge.py를 가져오지 않는다 (순환 방지). 면접관 스레드가 동시에 부르므로 잠금을 쓴다.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

UNAVAILABLE = "판정불가"
MIN_SAMPLES = 3  # 이 실행에서 이만큼 끝나야 평균을 믿는다
HISTORY_MIN_ROWS = 5


def format_duration(seconds: float) -> str:
    if seconds < 90:
        return f"약 {int(round(seconds))}초"
    return f"약 {int(round(seconds / 60))}분"


def load_history(judge_dir: Path, exclude: Path | None, names: list[str], min_rows: int = HISTORY_MIN_ROWS) -> dict[str, float]:
    """면접관마다, 기록이 min_rows건 이상 있는 가장 최근 다른 실행의 건당 평균 초."""
    result: dict[str, float] = {}
    if not judge_dir.is_dir():
        return result
    skip = exclude.resolve() if exclude else None
    dirs = sorted((d for d in judge_dir.iterdir() if d.is_dir() and d.resolve() != skip), key=lambda d: d.name, reverse=True)
    for name in names:
        for d in dirs:
            path = d / f"judge_{name}.jsonl"
            if not path.is_file():
                continue
            secs: list[float] = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                s = r.get("sec") if isinstance(r, dict) else None
                if isinstance(s, (int, float)) and r.get("verdict") != UNAVAILABLE:
                    secs.append(float(s))
            if len(secs) >= min_rows:
                result[name] = sum(secs) / len(secs)
                break
    return result


class Progress:
    def __init__(
        self,
        items,
        ids: dict[str, str],
        judges: list[str],
        *,
        blind: bool = False,
        out: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        interval: float = 30.0,
        expect: dict[str, float] | None = None,
        min_sec: dict[str, float] | None = None,
    ) -> None:
        self.keys = [it.key for it in items]
        self.info = {it.key: (ids[it.key], it.qid, it.repeat) for it in items}
        self.total = len(self.keys)
        self.judges = list(judges)
        self.blind = blind
        self.out = out or (lambda s: print(s, flush=True))
        self.clock = clock
        self.interval = interval
        self.expect = dict(expect or {})
        self.min_sec = dict(min_sec or {})
        self.verdicts: dict[str, dict[str, str]] = {j: {} for j in self.judges}
        self.secs: dict[str, list[float]] = {j: [] for j in self.judges}
        self.state = {j: "pending" for j in self.judges}  # pending | ready | out
        self.completed: set[str] = set()
        self.fresh: set[str] = set()  # 이 실행에서 새로 판정이 나온 건
        self._last = clock()
        self._lock = threading.RLock()

    # ---- 면접관 상태 ----
    def judge_ready(self, name: str, done: dict[str, str] | None = None) -> None:
        """시작 확인을 마치고 판정을 시작한다. done은 이어하기 때 이미 끝난 건 {key: 판정}."""
        with self._lock:
            self.verdicts[name].update(done or {})
            self.state[name] = "ready"
            self._check()

    def judge_out(self, name: str) -> None:
        """건너뛰었거나 멈춘 면접관. 이 면접관은 빼고 건 완료를 센다."""
        with self._lock:
            self.state[name] = "out"
            self._check()

    def on_row(self, name: str, row: dict) -> None:
        with self._lock:
            key = row["key"]
            self.verdicts[name][key] = row["verdict"]
            if isinstance(row.get("sec"), (int, float)) and row["verdict"] != UNAVAILABLE:
                self.secs[name].append(float(row["sec"]))
            self.fresh.add(key)
            self._check(only=key)

    # ---- 건 완료 줄 ----
    def _check(self, only: str | None = None) -> None:
        if any(s == "pending" for s in self.state.values()):
            return
        active = [j for j in self.judges if self.state[j] == "ready"]
        if not active:
            return
        for key in [only] if only else self.keys:
            if key in self.completed or key not in self.info:
                continue
            if all(key in self.verdicts[j] for j in active):
                self.completed.add(key)
                if key in self.fresh:
                    self.out(self._item_line(key, active))

    def _item_line(self, key: str, active: list[str]) -> str:
        bid, qid, repeat = self.info[key]
        head = f"[{len(self.completed)}/{self.total}] {bid} {qid} {repeat}회차 — "
        if self.blind:
            return head + "끝남"
        vs = [self.verdicts[j][key] for j in active]
        split = "합격" in vs and "불합격" in vs
        return head + ", ".join(f"{j} {self.verdicts[j][key]}" for j in active) + (" (갈림)" if split else "")

    # ---- 시간 ----
    def _avg(self, name: str) -> float | None:
        s = self.secs[name]
        if len(s) >= MIN_SAMPLES:
            return sum(s) / len(s)
        return self.expect.get(name)

    def _eta(self, remaining: dict[str, int], avgs: dict[str, float | None]) -> str:
        parts = []
        for j, left in remaining.items():
            if left == 0:
                parts.append(0.0)
                continue
            a = avgs.get(j)
            if a is None:
                return "계산 중"
            parts.append(left * max(a, self.min_sec.get(j, 0.0)))
        return format_duration(max(parts)) if parts else "계산 중"

    def start_line(self, todo: dict[str, int] | None = None) -> str:
        todo = todo or {j: self.total for j in self.judges}
        known = {j: self.expect.get(j) for j in self.judges}
        if any(v is None for v in known.values()):
            missing = ", ".join(j for j, v in known.items() if v is None)
            return f"예상 시간: 이전 기록 없음 ({missing})"
        eta = self._eta(todo, known)
        per = " · ".join(f"{j} {known[j]:.1f}초" for j in self.judges)
        return f"예상 시간: {eta} (이전 실행 건당 평균 {per}, 가장 느린 면접관 기준)"

    def summary_line(self) -> str:
        with self._lock:
            parts, avg_parts = [], []
            remaining, avgs = {}, {}
            for j in self.judges:
                done = len(self.verdicts[j])
                mark = " (멈춤)" if self.state[j] == "out" else ""
                parts.append(f"{j} {done}/{self.total}{mark}")
                a = self._avg(j)
                avgs[j] = a
                avg_parts.append(f"{j} {a:.1f}초" if a is not None else f"{j} -")
                if self.state[j] == "ready":
                    remaining[j] = self.total - done
            return f"진행 {' · '.join(parts)} | 건당 평균 {' · '.join(avg_parts)} | 남은 예상 {self._eta(remaining, avgs)}"

    def tick(self) -> None:
        """메인 대기 루프에서 자주 부른다. 간격이 지났을 때만 한 줄 찍는다."""
        now = self.clock()
        if now - self._last < self.interval:
            return
        self._last = now
        self.out(self.summary_line())

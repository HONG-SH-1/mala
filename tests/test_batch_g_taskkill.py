"""배치 G (정확성 7): 시간 초과 때 프로세스 정리.

- `proc.kill()`은 codex.cmd 껍데기(cmd.exe)만 끝낼 수 있고 그 아래 node가 파이프를 쥔 채 남을 수 있다 → 윈도우에서는 `taskkill /T /F /PID`.
- 바로 뒤의 `proc.communicate()`에 시간 제한이 없으면 그 node가 남을 때 그 자리에서 멈춘다 → 두 번째 communicate에 제한.
가짜 `run`/`Popen`으로 명령과 인자를 확인하고, 파이프를 쥔 손자 프로세스(파이썬)로 실제 동작을 확인한다. 실제 claude, codex, gemini 호출은 없다.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.eval import judge
from src.eval.judge import (
    DRAIN_TIMEOUT,
    KILL_TREE_TIMEOUT,
    kill_process_tree,
    terminate_children,
    tracked_run,
)


class FakeProc:
    def __init__(self, pid=4321, kill_raises=None):
        self.pid, self.killed, self.terminated, self.kill_raises = pid, 0, 0, kill_raises

    def kill(self):
        self.killed += 1
        if self.kill_raises:
            raise self.kill_raises

    def terminate(self):
        self.terminated += 1

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


class RunSpy:
    def __init__(self, raises=None):
        self.calls, self.raises = [], raises

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(cmd, 0)


def windows(monkeypatch, value=True):
    monkeypatch.setattr(judge, "_is_windows", lambda: value)


# ---- kill_process_tree ------------------------------------------------------------------------------------------------


def test_windows_kills_the_whole_tree_with_taskkill(monkeypatch):
    windows(monkeypatch)
    proc, run = FakeProc(pid=4321), RunSpy()
    kill_process_tree(proc, run=run)
    (cmd, kw), = run.calls
    assert cmd == ["taskkill", "/T", "/F", "/PID", "4321"]
    assert kw["timeout"] == KILL_TREE_TIMEOUT and kw["check"] is False
    assert proc.killed == 1  # 껍데기도 kill()로 한 번 더 (이미 끝났어도 안전)


def test_taskkill_command_never_goes_through_a_shell_string(monkeypatch):
    windows(monkeypatch)
    run = RunSpy()
    kill_process_tree(FakeProc(pid=7), run=run)
    assert isinstance(run.calls[0][0], list) and not run.calls[0][1].get("shell")


def test_other_platforms_only_kill_the_process(monkeypatch):
    windows(monkeypatch, False)
    proc, run = FakeProc(), RunSpy()
    kill_process_tree(proc, run=run)
    assert run.calls == [] and proc.killed == 1


@pytest.mark.parametrize("error", [OSError("no taskkill"), subprocess.TimeoutExpired("taskkill", 10), subprocess.SubprocessError("x")])
def test_when_taskkill_fails_the_shell_is_still_killed(monkeypatch, error):
    windows(monkeypatch)
    proc = FakeProc()
    kill_process_tree(proc, run=RunSpy(raises=error))
    assert proc.killed == 1


def test_kill_errors_on_an_already_finished_process_are_ignored(monkeypatch):
    windows(monkeypatch)
    kill_process_tree(FakeProc(kill_raises=PermissionError("already gone")), run=RunSpy())


@pytest.mark.parametrize("pid", [None, "12", 1.5])
def test_without_a_usable_pid_taskkill_is_not_called(monkeypatch, pid):
    windows(monkeypatch)
    proc, run = FakeProc(pid=pid), RunSpy()
    kill_process_tree(proc, run=run)
    assert run.calls == [] and proc.killed == 1


def test_limits_are_set():
    assert 0 < DRAIN_TIMEOUT <= 10 and 0 < KILL_TREE_TIMEOUT <= 30


# ---- tracked_run: 시간 초과 처리 -------------------------------------------------------------------------------------------


class TimingOutPopen:
    """communicate가 첫 호출에서 시간 초과, 두 번째 호출은 second에 따라 끝나거나 또 시간 초과."""

    instances = []

    def __init__(self, cmd, **kw):
        self.pid, self.cmd, self.calls, self.returncode = 999, cmd, [], None
        self.second = TimingOutPopen.second
        TimingOutPopen.instances.append(self)

    def communicate(self, input=None, timeout=None):
        self.calls.append((input, timeout))
        if len(self.calls) == 1 or self.second == "hang":
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        return "o", "e"

    def kill(self):
        pass


@pytest.fixture
def fake_popen(monkeypatch):
    TimingOutPopen.instances = []
    TimingOutPopen.second = "ok"
    monkeypatch.setattr(judge.subprocess, "Popen", TimingOutPopen)
    spy = []
    monkeypatch.setattr(judge, "kill_process_tree", lambda proc, **kw: spy.append(proc))
    return spy


def test_timeout_kills_the_tree_then_drains_with_a_time_limit(fake_popen):
    with pytest.raises(subprocess.TimeoutExpired):
        tracked_run(["x"], input="p", capture_output=True, text=True, timeout=7)
    (proc,) = TimingOutPopen.instances
    assert fake_popen == [proc]  # 나무 전체 종료를 불렀다
    assert proc.calls == [("p", 7), (None, DRAIN_TIMEOUT)]  # 두 번째 communicate에 시간 제한
    assert not judge._CHILDREN


def test_if_the_pipe_never_closes_the_second_communicate_gives_up_and_the_timeout_is_raised(fake_popen):
    TimingOutPopen.second = "hang"
    with pytest.raises(subprocess.TimeoutExpired) as ei:
        tracked_run(["x"], input="p", capture_output=True, text=True, timeout=7)
    assert ei.value.timeout == 7  # 처음의 시간 초과가 그대로 올라간다 (호출한 쪽은 CallError timeout으로 바꾼다)
    assert len(TimingOutPopen.instances[0].calls) == 2 and not judge._CHILDREN


def test_the_judges_turn_that_timeout_into_call_error_timeout(fake_popen, tmp_path):
    TimingOutPopen.second = "hang"
    j = judge.CodexJudge(tmp_path, "gpt-x", "low", timeout=1)
    with pytest.raises(judge.CallError) as ei:
        j.call("p")
    assert ei.value.kind == "transient" and ei.value.status == "timeout"


# ---- terminate_children (Ctrl+C) ----------------------------------------------------------------------------------------


def test_ctrl_c_kills_the_tree_first_on_windows_because_terminate_only_ends_the_shell(monkeypatch):
    windows(monkeypatch)
    order, procs = [], [FakeProc(1), FakeProc(2)]
    monkeypatch.setattr(judge, "kill_process_tree", lambda proc, **kw: order.append(("tree", proc.pid)))
    for p in procs:
        judge._CHILDREN.add(p)
    try:
        assert terminate_children(grace=0.1) == 2
    finally:
        for p in procs:
            judge._CHILDREN.discard(p)
    assert sorted(order) == [("tree", 1), ("tree", 2)] and all(p.terminated == 1 for p in procs)


def test_ctrl_c_on_other_platforms_only_terminates(monkeypatch):
    windows(monkeypatch, False)
    trees, p = [], FakeProc(5)
    monkeypatch.setattr(judge, "kill_process_tree", lambda proc, **kw: trees.append(proc))
    judge._CHILDREN.add(p)
    try:
        terminate_children(grace=0.1)
    finally:
        judge._CHILDREN.discard(p)
    assert trees == [] and p.terminated == 1


def test_a_child_that_ignores_terminate_is_tree_killed_after_the_grace(monkeypatch):
    windows(monkeypatch, False)

    class Stubborn(FakeProc):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("x", timeout)

    trees, st = [], Stubborn(9)
    monkeypatch.setattr(judge, "kill_process_tree", lambda proc, **kw: trees.append(proc))
    judge._CHILDREN.add(st)
    try:
        terminate_children(grace=0.05)
    finally:
        judge._CHILDREN.discard(st)
    assert trees == [st] and st.terminated == 1


# ---- 실제 프로세스: 파이프를 쥔 손자가 남는 경우 -------------------------------------------------------------------------------

PARENT = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])  # 부모의 stdout, stderr 파이프를 그대로 물려받는다
open(sys.argv[1], "w").write(str(child.pid))
time.sleep(120)
"""


def alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, timeout=20).stdout
    return str(pid).encode() in out


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill은 윈도우에서만 쓴다")
def test_real_grandchild_holding_the_pipes_does_not_hang_the_timeout_and_is_killed(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        tracked_run([sys.executable, "-c", PARENT, str(pidfile)], input="x", capture_output=True, text=True, timeout=2)
    elapsed = time.monotonic() - t0
    pid = int(Path(pidfile).read_text())
    try:
        assert elapsed < 20, f"시간 초과 처리가 {elapsed:.0f}초 걸렸다 (파이프를 쥔 프로세스를 기다리며 멈춤)"
        deadline = time.monotonic() + 5
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not alive(pid), "손자 프로세스가 남아 있다"
    finally:
        if alive(pid):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=20)
    assert not judge._CHILDREN

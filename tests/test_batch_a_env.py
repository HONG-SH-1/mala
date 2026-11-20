"""배치 A: Redis 기본 주소와 subprocess 인코딩.

- Redis: 윈도우에서 localhost는 IPv6(::1)을 먼저 시도해 연결마다 약 2초를 버린다. 기본값은 127.0.0.1.
- 인코딩: text=True만 쓰면 한국어 윈도우에서 cp949로 풀려 UnicodeDecodeError가 난다.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from src import config
from src.eval import judge

ROOT = Path(__file__).resolve().parents[1]


def test_redis_host_default_is_ipv4_literal(monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)  # config import 때 .env가 채운 값을 지운다
    assert config.get_settings().redis_host == "127.0.0.1"


def test_redis_host_env_still_wins(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "10.1.2.3")
    assert config.get_settings().redis_host == "10.1.2.3"


def test_env_example_uses_ipv4_literal():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "REDIS_HOST=127.0.0.1" in lines


_SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _text_calls_without_encoding(path: Path) -> list[int]:
    """subprocess.<함수>(..., text=True) 인데 encoding이 없는 호출의 줄 번호."""
    bad: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        base = node.func.value
        if not (isinstance(base, ast.Name) and base.id == "subprocess" and node.func.attr in _SUBPROCESS_FUNCS):
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg}
        texty = any(isinstance(kws.get(n), ast.Constant) and kws[n].value is True for n in ("text", "universal_newlines"))
        if texty and ("encoding" not in kws or "errors" not in kws):
            bad.append(node.lineno)
    return bad


def test_every_text_mode_subprocess_call_in_src_sets_encoding_and_errors():
    problems = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        bad = _text_calls_without_encoding(path)
        if bad:
            problems[str(path.relative_to(ROOT))] = bad
    assert not problems, f"encoding/errors 없는 text 모드 subprocess 호출: {problems}"


def test_the_scan_itself_catches_a_missing_encoding(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import subprocess\nsubprocess.run(['a'], text=True)\n"
                 "subprocess.run(['a'], text=True, encoding='utf-8', errors='replace')\n", encoding="utf-8")
    assert _text_calls_without_encoding(f) == [2]


def test_tracked_run_fills_utf8_defaults_in_text_mode(monkeypatch):
    seen = {}

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, **kw):
            seen.update(kw)

        def communicate(self, input=None, timeout=None):
            return "o", "e"

    monkeypatch.setattr(judge.subprocess, "Popen", FakeProc)
    judge.tracked_run(["x"], input="p", capture_output=True, text=True)
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


def test_tracked_run_keeps_the_callers_encoding(monkeypatch):
    seen = {}

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, **kw):
            seen.update(kw)

        def communicate(self, input=None, timeout=None):
            return "o", "e"

    monkeypatch.setattr(judge.subprocess, "Popen", FakeProc)
    judge.tracked_run(["x"], capture_output=True, text=True, encoding="latin-1", errors="strict")
    assert seen["encoding"] == "latin-1" and seen["errors"] == "strict"


def test_tracked_run_leaves_binary_mode_alone(monkeypatch):
    seen = {}

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, **kw):
            seen.update(kw)

        def communicate(self, input=None, timeout=None):
            return b"o", b"e"

    monkeypatch.setattr(judge.subprocess, "Popen", FakeProc)
    judge.tracked_run(["x"], capture_output=True)
    assert "encoding" not in seen and "errors" not in seen

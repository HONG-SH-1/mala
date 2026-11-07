"""keystore — 가짜 러너로 확인한다. 실제 KeePassXC와 금고는 건드리지 않는다."""

import subprocess

import pytest

from src.keystore import KeystoreError, Secret, check_gemini_key_shape, get_secret, redact

FAKE_KEY = "AQ." + "k" * 50  # 53자, 진짜 키 아님
ENV = {"KEEPASSXC_CLI": r"C:\fake\keepassxc-cli.exe", "MALA_KDBX_PATH": r"D:\fake\mala.kdbx"}


class FakeRunner:
    def __init__(self, stdout=FAKE_KEY + "\n", returncode=0, exc=None):
        self.stdout, self.returncode, self.exc = stdout, returncode, exc
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="")


def test_command_shape_and_stdin_is_inherited():
    r = FakeRunner()
    secret = get_secret("mala-gemini", runner=r, environ=ENV)
    cmd, kw = r.calls[0]
    assert cmd == [ENV["KEEPASSXC_CLI"], "show", "-s", "-a", "password", ENV["MALA_KDBX_PATH"], "mala-gemini"]
    # 금고 암호는 사용자가 터미널에 직접 친다 → stdin/stderr를 가로채면 안 된다
    assert "stdin" not in kw and "stderr" not in kw and "input" not in kw
    assert kw["stdout"] == subprocess.PIPE
    assert secret.reveal() == FAKE_KEY


def test_secret_hides_itself():
    s = Secret(FAKE_KEY)
    for text in (repr(s), str(s), f"{s}", f"{[s]}", f"{{'k': {s!r}}}"):
        assert FAKE_KEY not in text
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(s)


def test_failure_messages_have_no_secret():
    for runner in (FakeRunner(returncode=1, stdout=FAKE_KEY), FakeRunner(stdout=""), FakeRunner(exc=FileNotFoundError(FAKE_KEY))):
        with pytest.raises(KeystoreError) as ei:
            get_secret("mala-gemini", runner=runner, environ=ENV)
        assert FAKE_KEY not in str(ei.value) and FAKE_KEY not in repr(ei.value)


def test_missing_env_names_only():
    with pytest.raises(KeystoreError) as ei:
        get_secret("mala-gemini", runner=FakeRunner(), environ={})
    assert "KEEPASSXC_CLI" in str(ei.value)


def test_key_shape_error_has_no_key_fragment():
    with pytest.raises(KeystoreError) as ei:
        check_gemini_key_shape(Secret("AQ.short" + "z" * 5))
    assert "short" not in str(ei.value) and "zzzzz" not in str(ei.value)
    check_gemini_key_shape(Secret(FAKE_KEY))  # 정상 모양은 통과
    with pytest.raises(KeystoreError):
        check_gemini_key_shape(Secret("XX." + "k" * 50))


def test_redact():
    assert FAKE_KEY not in redact(f"boom {FAKE_KEY} boom", Secret(FAKE_KEY))
    assert redact("plain", None) == "plain"

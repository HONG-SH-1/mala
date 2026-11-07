"""KeePassXC 금고에서 비밀값을 메모리로만 꺼낸다.

- 금고 암호는 사용자가 터미널에 직접 친다. 이 모듈은 stdin/stderr를 가로채지 않고
  자식 프로세스(keepassxc-cli)에 그대로 물려준다. stdout(키)만 받는다.
- 키는 `Secret`에만 담긴다. print/repr/f-string에 실수로 찍혀도 `***`로 보인다.
  꺼낼 때는 `.reveal()`을 명시적으로 불러야 한다 (HTTP 헤더를 만들 때만 쓴다).
- 오류 메시지에는 종료 코드와 항목 이름만 넣는다. 키나 CLI 출력은 넣지 않는다.
- 모듈 이름을 secrets로 하지 않은 이유: 표준 라이브러리 `secrets`와 겹친다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]

GEMINI_ENTRY = "mala-gemini"
GEMINI_KEY_PREFIX = "AQ."
GEMINI_KEY_LENGTH = 53


class KeystoreError(RuntimeError):
    """금고 조회 실패. 메시지에 비밀값이 들어가지 않는다."""


class Secret:
    """문자열 하나를 감싸 우연한 출력에서 가린다."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__

    def __len__(self) -> int:
        return len(self._value)

    def __reduce__(self):  # pickle/copy로 값이 새지 않게
        raise TypeError("Secret은 직렬화할 수 없습니다.")


def redact(text: object, *secrets: "Secret | str | None") -> str:
    """문자열에서 비밀값이 있으면 지운다. 마지막 안전망이다."""
    out = str(text)
    for s in secrets:
        if s is None:
            continue
        raw = s.reveal() if isinstance(s, Secret) else str(s)
        if raw:
            out = out.replace(raw, "***")
    return out


def get_secret(
    entry: str,
    *,
    runner: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    environ: dict[str, str] | None = None,
) -> Secret:
    """금고 항목의 password를 `Secret`으로 돌려준다.

    실행하는 명령: `<CLI> show -s -a password <금고> <항목>`
    CLI 경로와 금고 경로는 비밀이 아니라서 .env의 KEEPASSXC_CLI, MALA_KDBX_PATH에서 읽는다.
    """
    if environ is None:
        load_dotenv(_ROOT / ".env")
    env = os.environ if environ is None else environ
    cli = (env.get("KEEPASSXC_CLI") or "").strip()
    kdbx = (env.get("MALA_KDBX_PATH") or "").strip()
    if not cli or not kdbx:
        raise KeystoreError(".env에 KEEPASSXC_CLI와 MALA_KDBX_PATH가 필요합니다.")
    if not entry:
        raise KeystoreError("항목 이름이 비어 있습니다.")

    cmd = [cli, "show", "-s", "-a", "password", kdbx, entry]
    try:
        # stdin/stderr는 일부러 지정하지 않는다 → 터미널을 그대로 쓰므로 암호는 사용자가 직접 친다.
        proc = runner(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise KeystoreError(f"KeePassXC CLI를 실행하지 못했습니다 ({type(exc).__name__}).") from None
    if proc.returncode != 0:
        raise KeystoreError(f"KeePassXC가 실패했습니다 (종료 코드 {proc.returncode}, 항목 '{entry}').")
    value = (proc.stdout or "").strip("\r\n")
    if not value:
        raise KeystoreError(f"항목 '{entry}'의 password가 비어 있습니다.")
    return Secret(value)


def check_gemini_key_shape(secret: Secret) -> None:
    """Gemini 키 모양만 본다 ('AQ.'로 시작, 53자). 틀려도 키 조각은 메시지에 넣지 않는다."""
    raw = secret.reveal()
    if not raw.startswith(GEMINI_KEY_PREFIX) or len(raw) != GEMINI_KEY_LENGTH:
        raise KeystoreError(f"Gemini 키 형식이 맞지 않습니다 (길이 {len(raw)}, 'AQ.' 시작 여부 확인).")

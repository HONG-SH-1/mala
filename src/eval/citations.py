"""인용 확인 — 면접관이 인용한 문장이 docs 사본의 그 줄에 실제로 있는지 코드로 본다.

원칙: **글자는 그대로, 겉모양만 무시.** 의미가 같다는 이유로 통과시키지 않는다.
비교 전에 줄과 인용문 양쪽에 똑같은 정리(normalize)를 하고, 정리한 인용문이 정리한 그 줄의 연속된 부분 문자열이어야 통과한다.

무효 사유(status):
- ok: 확인됨
- wrong_line: 줄 번호만 틀림 (같은 파일의 다른 줄에는 그 문장이 있음. 그 줄 번호는 matched_line). 무효로 센다.
  엄격함이 문제인지 나중에 보려고 따로 적는다.
- not_found: 그 줄에도, 같은 파일의 다른 줄에도 없음
- file_not_provided: 보여 주지 않은 문서
- out_of_range: 보여 주지 않은 줄 (또는 문서 밖의 줄 번호)
- too_short: 정리 후 6글자 미만
- ellipsis: 줄임표(… 또는 ...)가 들어 있음
- bad_format: 형식이 틀림 (file, line, quote 아님 / 여러 줄 / 300자 초과)

문서는 사본 폴더 안에서만 읽는다 (밖으로 나가는 경로는 거부).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

MIN_NORMALIZED_CHARS = 6
MAX_QUOTE_CHARS = 300

STATUS_TEXT = {
    "ok": "확인됨",
    "wrong_line": "줄 번호만 틀림",
    "not_found": "문서에 없는 문장",
    "file_not_provided": "보여 주지 않은 문서",
    "out_of_range": "보여 주지 않은 줄",
    "too_short": "너무 짧음",
    "ellipsis": "줄임표 사용",
    "bad_format": "형식 오류",
}

_ZERO_WIDTH = re.compile("[​-‍⁠﻿]")
_LEAD_QUOTE = re.compile(r"^\s*(?:>\s*)+")
_LEAD_HEAD = re.compile(r"^\s*#{1,6}\s+")
_LEAD_LIST = re.compile(r"^\s*(?:[-*+]|[0-9]+[.)])\s+")
_LEAD_TASK = re.compile(r"^\s*\[[ xX]\]\s*")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
_SPACE = re.compile(r"\s+")
_QUOTE_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def normalize(text: str) -> str:
    """줄 하나(또는 인용문 하나)를 비교용으로 정리한다. 줄과 인용문에 똑같이 쓴다."""
    s = unicodedata.normalize("NFKC", text)
    s = _ZERO_WIDTH.sub("", s)
    s = _LEAD_QUOTE.sub("", s)
    s = _LEAD_HEAD.sub("", s)
    s = _LEAD_LIST.sub("", s)
    s = _LEAD_TASK.sub("", s)
    s = _IMAGE.sub(r"\1", s)
    s = _LINK.sub(r"\1", s)
    s = _HTML_TAG.sub("", s)
    s = s.replace("|", " ")
    for mark in ("**", "__", "~~", "`"):
        s = s.replace(mark, "")
    s = _ESCAPED.sub(r"\1", s)
    s = s.translate(_QUOTE_MAP).casefold()
    return _SPACE.sub("", s)


_cache: dict[tuple, list[str]] = {}


def read_doc_lines(corpus_dir: Path, rel: str) -> list[str] | None:
    """사본 안의 문서를 줄 목록으로. 사본 밖으로 나가거나 없으면 None."""
    base = corpus_dir.resolve()
    path = (base / rel).resolve()
    if base not in path.parents or not path.is_file():
        return None
    st = path.stat()
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _cache:
        _cache[key] = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return _cache[key]


def _in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= line <= b for a, b in ranges)


def verify_citation(cit: object, shown: dict[str, list[tuple[int, int]]], corpus_dir: Path) -> dict:
    """인용 하나를 확인한다. shown은 면접관에게 보여 준 {문서: [(시작줄, 끝줄), ...]}.

    돌려주는 값: {file, line, quote, status, valid, matched_line}. 모델이 쓴 글이라 길이를 자르고, 형식이 틀려도 예외 없이 기록한다."""
    def out(file, line, quote, status, matched=None) -> dict:
        return {"file": str(file)[:200], "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
                "quote": str(quote)[:MAX_QUOTE_CHARS], "status": status, "valid": status == "ok", "matched_line": matched}

    if not isinstance(cit, dict) or set(cit) != {"file", "line", "quote"}:
        return out("", None, "", "bad_format")
    file, line, quote = cit["file"], cit["line"], cit["quote"]
    if not isinstance(file, str) or not isinstance(quote, str) or isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return out(file if isinstance(file, str) else "", line, quote if isinstance(quote, str) else "", "bad_format")
    if "\n" in quote or "\r" in quote or len(quote) > MAX_QUOTE_CHARS:
        return out(file, line, quote, "bad_format")
    if "…" in quote or "..." in quote:
        return out(file, line, quote, "ellipsis")
    if file not in shown:
        return out(file, line, quote, "file_not_provided")
    lines = read_doc_lines(corpus_dir, file)
    if lines is None or line > len(lines) or not _in_ranges(line, shown[file]):
        return out(file, line, quote, "out_of_range")
    nq = normalize(quote)
    if len(nq) < MIN_NORMALIZED_CHARS:
        return out(file, line, quote, "too_short")
    if nq in normalize(lines[line - 1]):
        return out(file, line, quote, "ok")
    others = [i for i, ln in enumerate(lines, 1) if i != line and nq in normalize(ln)]
    if others:
        return out(file, line, quote, "wrong_line", min(others, key=lambda i: abs(i - line)))
    return out(file, line, quote, "not_found")


def verify_all(cits: list, shown: dict[str, list[tuple[int, int]]], corpus_dir: Path) -> list[dict]:
    return [verify_citation(c, shown, corpus_dir) for c in cits]

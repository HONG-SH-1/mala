"""아주 작은 마크다운 변환기 (기준 구현).

review.html의 JS 변환기(`/* MD-BEGIN */ ... /* MD-END */`)와 규칙이 같아야 한다. 같은 입력에 같은 결과가 나오는지
tests/test_md_mini.py가 본다 (node가 있으면 JS도 직접 돌려 비교).

지원하는 것: **굵게**, `코드`, 목록(-, *, +, 1. 1)), 들여쓰기(2칸 = 1단계, 최대 3단계), 줄바꿈, ``` 코드 블록.
지원하지 않는 문법(제목 #, 인용 >, 기울임 *x*, 표, 링크 등)은 글자 그대로 둔다.
출력은 HTML이 아니라 구조(목록)이고, 화면에서는 createElement와 textContent로만 만든다.

JS와 같게 하려고 정규식은 ASCII만 쓴다: \\d 대신 [0-9], . 대신 [^\\n].
"""

from __future__ import annotations

import re

_INLINE = re.compile(r"\*\*([^*]+)\*\*|`([^`]+)`")
_LI = re.compile(r"^( *)([-*+]|[0-9]+[.)]) +([^\n]*)$")
_PLAIN = re.compile(r"^( *)([^\n]*)$")
_FENCE_OPEN = re.compile(r"^[ \t]*```")
_FENCE_CLOSE = re.compile(r"^[ \t]*```[ \t]*$")
_BLANK = re.compile(r"^[ \t]*$")
_TRAIL = re.compile(r"[ \t]+$")
_NEWLINES = re.compile(r"\r\n|\r|\n")
MAX_DEPTH = 3


def parse_inline(s: str) -> list[list[str]]:
    """한 줄을 [["t", 글], ["b", 굵게], ["c", 코드]] 조각으로 나눈다."""
    out: list[list[str]] = []
    pos = 0
    for m in _INLINE.finditer(s):
        if m.start() > pos:
            out.append(["t", s[pos:m.start()]])
        out.append(["b", m.group(1)] if m.group(1) is not None else ["c", m.group(2)])
        pos = m.end()
    if pos < len(s):
        out.append(["t", s[pos:]])
    return out


def parse_markdown(text: str) -> list[dict]:
    """블록 목록: {"t":"p","d":깊이,"c":조각} | {"t":"li","d":..,"m":표시,"c":..} | {"t":"code","x":글} | {"t":"gap"}."""
    lines = _NEWLINES.split(text)
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        if _FENCE_OPEN.match(raw):
            i += 1
            code: list[str] = []
            while i < len(lines) and not _FENCE_CLOSE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # 닫는 줄 (없으면 끝까지가 코드)
            blocks.append({"t": "code", "x": "\n".join(code)})
            continue
        i += 1
        if _BLANK.match(raw):
            if blocks and blocks[-1]["t"] != "gap":
                blocks.append({"t": "gap"})
            continue
        line = _TRAIL.sub("", raw.replace("\t", "    "))
        m = _LI.match(line)
        if m:
            marker = m.group(2)
            blocks.append({"t": "li", "d": min(MAX_DEPTH, len(m.group(1)) // 2),
                           "m": "•" if len(marker) == 1 else marker, "c": parse_inline(m.group(3))})
            continue
        p = _PLAIN.match(line)
        assert p is not None  # 정규식이 줄바꿈 아닌 글자 전부를 받으므로 항상 맞는다
        blocks.append({"t": "p", "d": min(MAX_DEPTH, len(p.group(1)) // 2), "c": parse_inline(p.group(2))})
    while blocks and blocks[-1]["t"] == "gap":
        blocks.pop()
    return blocks

"""아주 작은 마크다운 변환기 (기준 구현).

review.html의 JS 변환기(`/* MD-BEGIN */ ... /* MD-END */`)와 규칙이 같아야 한다. 같은 입력에 같은 결과가 나오는지
tests/test_md_mini.py가 본다 (node가 있으면 JS도 직접 돌려 비교).

지원하는 것
- 인라인: **굵게**, `코드`, [글](주소) (화면에서는 글만 보이고 주소는 흐리게)
- 블록: 제목(#, ##, ###), 표(머리줄 + 구분줄 + 행), 인용(>), 구분선(---), 목록(-, *, +, 1. 1)),
  체크 목록(- [x] 는 ✓, - [ ] 는 ☐), 들여쓰기(2칸 = 1단계, 최대 3단계), 줄바꿈, ``` 코드 블록
- 표의 머리줄이나 구분줄이 없으면(발췌가 표 중간에서 잘린 경우) 그 줄들은 표로 만들지 않고 글자 그대로 둔다.
지원하지 않는 문법(기울임 *x*, #### 이상 제목, 이미지, 중첩 인용 등)은 글자 그대로 둔다.
출력은 HTML이 아니라 구조이고, 화면에서는 createElement와 textContent로만 만든다.

JS와 같게 하려고 정규식은 ASCII만 쓴다: \\d 대신 [0-9], . 대신 [^\\n].

split_highlight: 핵심어가 나오는 자리를 표시하는 기준 구현 (JS의 hlSplit과 같아야 한다).
"""

from __future__ import annotations

import re

_INLINE = re.compile(r"\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)")
_LI = re.compile(r"^( *)([-*+]|[0-9]+[.)]) +([^\n]*)$")
_PLAIN = re.compile(r"^( *)([^\n]*)$")
_FENCE_OPEN = re.compile(r"^[ \t]*```")
_FENCE_CLOSE = re.compile(r"^[ \t]*```[ \t]*$")
_BLANK = re.compile(r"^[ \t]*$")
_TRAIL = re.compile(r"[ \t]+$")
_TRIM = re.compile(r"^[ \t]+|[ \t]+$")
_NEWLINES = re.compile(r"\r\n|\r|\n")
_HEAD = re.compile(r"^(#{1,3}) +([^\n]+)$")
_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_QUOTE = re.compile(r"^> ?([^\n]*)$")
_ROW = re.compile(r"^ {0,3}\|")
_SEP = re.compile(r"^ {0,3}\|?[ ]*:?-+:?[ ]*(\|[ ]*:?-+:?[ ]*)*\|?$")
_TASK = re.compile(r"^\[([ xX])\] +([^\n]*)$")
MAX_DEPTH = 3


def parse_inline(s: str) -> list[list[str]]:
    """한 줄을 [["t", 글], ["b", 굵게], ["c", 코드], ["l", 글, 주소]] 조각으로 나눈다."""
    out: list[list[str]] = []
    pos = 0
    for m in _INLINE.finditer(s):
        if m.start() > pos:
            out.append(["t", s[pos:m.start()]])
        if m.group(1) is not None:
            out.append(["b", m.group(1)])
        elif m.group(2) is not None:
            out.append(["c", m.group(2)])
        else:
            out.append(["l", m.group(3), m.group(4)])
        pos = m.end()
    if pos < len(s):
        out.append(["t", s[pos:]])
    return out


def _norm(raw: str) -> str:
    return _TRAIL.sub("", raw.replace("\t", "    "))


def _cells(line: str) -> list[str]:
    s = line.lstrip(" ")
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [_TRIM.sub("", c) for c in s.split("|")]


def parse_markdown(text: str) -> list[dict]:
    """블록 목록.

    {"t":"p","d":깊이,"c":조각} | {"t":"li","d":..,"m":표시,"c":..} | {"t":"code","x":글} | {"t":"gap"}
    | {"t":"h","l":1~3,"c":..} | {"t":"hr"} | {"t":"quote","c":[줄마다 조각,...]}
    | {"t":"table","h":[칸마다 조각,...],"r":[[칸마다 조각,...],...]}
    """
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
        line = _norm(raw)
        m = _HEAD.match(line)
        if m:
            blocks.append({"t": "h", "l": len(m.group(1)), "c": parse_inline(m.group(2))})
            continue
        if _HR.match(line):
            blocks.append({"t": "hr"})
            continue
        m = _QUOTE.match(line)
        if m:
            qs = [parse_inline(m.group(1))]
            while i < len(lines):
                mq = _QUOTE.match(_norm(lines[i]))
                if not mq:
                    break
                qs.append(parse_inline(mq.group(1)))
                i += 1
            blocks.append({"t": "quote", "c": qs})
            continue
        if _ROW.match(line) and i < len(lines):
            nxt = _norm(lines[i])
            if "|" in nxt and _SEP.match(nxt) and len(_cells(line)) == len(_cells(nxt)):
                head = _cells(line)
                n = len(head)
                i += 1
                rows: list[list[list[list[str]]]] = []
                while i < len(lines):
                    row = _norm(lines[i])
                    if not _ROW.match(row):
                        break
                    cs = _cells(row)[:n]
                    cs += [""] * (n - len(cs))
                    rows.append([parse_inline(c) for c in cs])
                    i += 1
                blocks.append({"t": "table", "h": [parse_inline(c) for c in head], "r": rows})
                continue
        m = _LI.match(line)
        if m:
            marker = "•" if len(m.group(2)) == 1 else m.group(2)
            body = m.group(3)
            task = _TASK.match(body)
            if task and len(m.group(2)) == 1:
                marker = "☐" if task.group(1) == " " else "✓"
                body = task.group(2)
            blocks.append({"t": "li", "d": min(MAX_DEPTH, len(m.group(1)) // 2), "m": marker, "c": parse_inline(body)})
            continue
        p = _PLAIN.match(line)
        assert p is not None  # 정규식이 줄바꿈 아닌 글자 전부를 받으므로 항상 맞는다
        blocks.append({"t": "p", "d": min(MAX_DEPTH, len(p.group(1)) // 2), "c": parse_inline(p.group(2))})
    while blocks and blocks[-1]["t"] == "gap":
        blocks.pop()
    return blocks


def split_highlight(text: str, keywords: list[str]) -> list[list]:
    """text를 [[조각, 핵심어인가], ...]로 나눈다. 대소문자는 구분하지 않고, 겹치면 왼쪽 것, 같은 자리면 긴 것."""
    if not text:
        return []
    kws = sorted({k.strip().lower() for k in keywords if k and k.strip()})
    low = text.lower()
    if not kws or len(low) != len(text):
        return [[text, False]]
    out: list[list] = []
    pos = 0
    while True:
        best: tuple[int, str] | None = None
        for k in kws:
            idx = low.find(k, pos)
            if idx >= 0 and (best is None or idx < best[0] or (idx == best[0] and len(k) > len(best[1]))):
                best = (idx, k)
        if best is None:
            break
        idx, k = best
        if idx > pos:
            out.append([text[pos:idx], False])
        out.append([text[idx:idx + len(k)], True])
        pos = idx + len(k)
    if pos < len(text):
        out.append([text[pos:], False])
    return out

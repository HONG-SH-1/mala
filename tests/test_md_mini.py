"""작은 마크다운 변환기: 파이썬 기준 구현 테스트 + (node가 있으면) review.html의 JS와 결과 비교."""

import json
import re
import shutil
import subprocess

import pytest

from src.eval.judge_report import TEMPLATE
from src.eval.md_mini import parse_inline, parse_markdown


def P(text, d=0):
    return {"t": "p", "d": d, "c": [["t", text]]}


# ---- 규칙 -----------------------------------------------------------------


def test_inline_bold_and_code():
    assert parse_inline("a **굵게** b `코드` c") == [["t", "a "], ["b", "굵게"], ["t", " b "], ["c", "코드"], ["t", " c"]]
    assert parse_inline("**a**`b`") == [["b", "a"], ["c", "b"]]


def test_inline_unsupported_stays_literal():
    for s in ("*기울임*", "**짝 없음", "`짝 없음", "[링크](http://x)", "~~취소~~", "****", "** **x"):
        out = parse_inline(s)
        assert "".join(seg[1] for seg in out if seg[0] == "t") != "" or s == "****"
    assert parse_inline("*기울임*") == [["t", "*기울임*"]]
    assert parse_inline("**짝 없음") == [["t", "**짝 없음"]]
    assert parse_inline("[링크](http://x)") == [["t", "[링크](http://x)"]]


def test_lists_and_indent_depth():
    got = parse_markdown("- 하나\n  - 둘\n    * 셋\n      + 넷\n          - 다섯")
    assert [(b["t"], b["d"], b["m"]) for b in got] == [("li", 0, "•"), ("li", 1, "•"), ("li", 2, "•"), ("li", 3, "•"), ("li", 3, "•")]
    got = parse_markdown("1. 가\n2) 나")
    assert [(b["m"], b["c"]) for b in got] == [("1.", [["t", "가"]]), ("2)", [["t", "나"]])]


def test_plain_indent_and_line_breaks():
    assert parse_markdown("첫 줄\n  들여쓴 줄\n끝") == [P("첫 줄"), P("들여쓴 줄", 1), P("끝")]
    assert parse_markdown("a\r\nb\rc") == [P("a"), P("b"), P("c")]


def test_blank_lines_become_one_gap_and_edges_are_dropped():
    assert parse_markdown("a\n\n\n\nb") == [P("a"), {"t": "gap"}, P("b")]
    assert parse_markdown("\n\na\n\n") == [P("a")]
    assert parse_markdown("") == [] and parse_markdown("  \n\t\n") == []


def test_code_block_is_verbatim_and_unclosed_runs_to_end():
    got = parse_markdown("앞\n```py\n- 목록 아님\n**굵게 아님**\n\n  들여쓰기\n```\n뒤")
    assert got == [P("앞"), {"t": "code", "x": "- 목록 아님\n**굵게 아님**\n\n  들여쓰기"}, P("뒤")]
    assert parse_markdown("```\nx\ny") == [{"t": "code", "x": "x\ny"}]


def test_unsupported_syntax_is_literal_text():
    for line in ("# 제목", "> 인용", "---", "| a | b |", "<b>태그</b>", "- ", "-없는공백", "1.없는공백"):
        assert parse_markdown(line) == [{"t": "p", "d": 0, "c": [["t", line.rstrip()]]}], line


def test_tabs_and_trailing_spaces():
    assert parse_markdown("\t- 탭 목록   ") == [{"t": "li", "d": 2, "m": "•", "c": [["t", "탭 목록"]]}]


def test_no_html_is_produced():
    got = parse_markdown("<script>alert(1)</script> **x**")
    assert got[0]["c"][0] == ["t", "<script>alert(1)</script> "]  # 글자 그대로. 화면에서는 textContent로만 넣는다


# ---- JS와 같은 결과인지 ---------------------------------------------------------

CASES = [
    "", "a", "a\n\nb", "- 가\n  - 나\n    - 다\n      - 라\n        - 마", "1. a\n2) b\n10. c", "**굵게** 와 `코드` 와 *기울임*",
    "# 제목\n> 인용\n---\n| a | b |", "```\n- x\n**y**\n```\n뒤", "```py\nunclosed\n\nstill", "\t- 탭\n\t\t- 탭2", "줄 끝 공백   \n  들여쓰기",
    "a\r\nb\rc\nd", "**짝 없음 `짝 없음", "****", "** x **", "`a` `b` **c** **d**", "- \n-x\n1.x\n1. ", "١. 아라비아 숫자\n٢) x",
    "줄 구분자 뒤 끝", "  \n\n  \na\n  \n", "* 별 목록\n+ 더하기\n- 빼기", "**a*b**", "``", "`**x**`", "**`x`**",
    "설명:\n\n```\n코드\n```\n\n- 목록\n\n마지막 **줄**",
]


def js_source() -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"/\* MD-BEGIN \*/(.*?)/\* MD-END \*/", tpl, re.S)
    assert m, "템플릿에 MD-BEGIN / MD-END 표시가 없다"
    return m.group(1)


def test_js_block_has_no_dom_or_html_apis():
    src = js_source()
    for bad in ("document", "innerHTML", "createElement", "eval", "Function"):
        assert bad not in src, bad


@pytest.mark.skipif(shutil.which("node") is None, reason="node가 없으면 JS 쪽 비교는 건너뜀 (브라우저 수동 확인 목록 참고)")
def test_js_converter_matches_python_reference():
    runner = js_source() + "\nvar cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" \
        "process.stdout.write(JSON.stringify(cases.map(mdParse)));\n"
    res = subprocess.run([shutil.which("node"), "-e", runner], input=json.dumps(CASES), capture_output=True,
                         text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == [parse_markdown(c) for c in CASES]

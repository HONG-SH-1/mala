"""작은 마크다운 변환기: 파이썬 기준 구현 테스트 + (node가 있으면) review.html의 JS와 결과 비교."""

import json
import re
import shutil
import subprocess

import pytest

from src.eval.judge_report import TEMPLATE
from src.eval.md_mini import parse_inline, parse_markdown, split_highlight


def P(text, d=0):
    return {"t": "p", "d": d, "c": [["t", text]]}


# ---- 규칙 -----------------------------------------------------------------


def test_inline_bold_and_code():
    assert parse_inline("a **굵게** b `코드` c") == [["t", "a "], ["b", "굵게"], ["t", " b "], ["c", "코드"], ["t", " c"]]
    assert parse_inline("**a**`b`") == [["b", "a"], ["c", "b"]]


def test_inline_unsupported_stays_literal():
    for s in ("*기울임*", "**짝 없음", "`짝 없음", "~~취소~~", "[주소 없음]", "[글](공 백)", "[글](", "![그림](x.png)"[:2]):
        assert "".join(seg[1] for seg in parse_inline(s) if seg[0] in "t") != "", s
    assert parse_inline("*기울임*") == [["t", "*기울임*"]]
    assert parse_inline("**짝 없음") == [["t", "**짝 없음"]]
    assert parse_inline("[글](공 백)") == [["t", "[글](공 백)"]]
    assert parse_inline("[주소 없음]") == [["t", "[주소 없음]"]]


def test_inline_link_keeps_text_and_url_separately():
    assert parse_inline("앞 [글](http://x/y?a=1) 뒤") == [["t", "앞 "], ["l", "글", "http://x/y?a=1"], ["t", " 뒤"]]
    assert parse_inline("[**굵게 아님**](u)") == [["l", "**굵게 아님**", "u"]]  # 링크 글 안의 문법은 풀지 않는다


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
    for line in ("#### 네 단계 제목", "#태그", "<b>태그</b>", "- ", "-없는공백", "1.없는공백", "--", "| a | b |", "|---|---|"):
        assert parse_markdown(line) == [{"t": "p", "d": 0, "c": [["t", line.rstrip()]]}], line


def test_headings():
    assert parse_markdown("# 하나\n## 둘 **굵게**\n### 셋") == [
        {"t": "h", "l": 1, "c": [["t", "하나"]]}, {"t": "h", "l": 2, "c": [["t", "둘 "], ["b", "굵게"]]},
        {"t": "h", "l": 3, "c": [["t", "셋"]]}]
    assert parse_markdown("  # 들여쓴 제목")[0]["t"] == "p"  # 맨 앞 칸에서만 제목


def test_horizontal_rule():
    for hr in ("---", "-----", "***", "___"):
        assert parse_markdown(hr) == [{"t": "hr"}], hr
    assert parse_markdown("- - -")[0]["t"] == "p" or parse_markdown("- - -")[0]["t"] == "li"  # 구분선이 아니다
    assert parse_markdown("--") == [P("--")]


def test_quote_groups_consecutive_lines():
    got = parse_markdown("> 첫 줄\n> **둘째** 줄\n>\n본문\n> 따로")
    assert got[0] == {"t": "quote", "c": [[["t", "첫 줄"]], [["b", "둘째"], ["t", " 줄"]], []]}
    assert got[1] == P("본문") and got[2] == {"t": "quote", "c": [[["t", "따로"]]]}


def test_table_with_header_and_alignment_row():
    got = parse_markdown("| 항목 | 값 |\n|:--|--:|\n| a | **b** |\n| c |\n\n뒤")
    assert got[0] == {"t": "table", "h": [[["t", "항목"]], [["t", "값"]]],
                      "r": [[[["t", "a"]], [["b", "b"]]], [[["t", "c"]], []]]}  # 모자란 칸은 빈 칸
    assert got[1] == {"t": "gap"} and got[2] == P("뒤")
    assert parse_markdown("항목 | 값\n--- | ---")[0]["t"] == "p"  # 바깥 | 없는 표는 지원하지 않는다


def test_table_cut_in_the_middle_stays_literal():
    cut = "| c | d |\n| e | f |"  # 머리줄과 구분줄이 잘려 나감
    assert parse_markdown(cut) == [P("| c | d |"), P("| e | f |")]
    assert parse_markdown("|---|---|\n| a | b |") == [P("|---|---|"), P("| a | b |")]
    assert parse_markdown("| a | b |\n|---|") == [P("| a | b |"), P("|---|")]  # 칸 수가 다르면 표가 아니다
    assert parse_markdown("| a | b |\n---")[0] == P("| a | b |")  # 구분줄에 |가 없다


def test_task_list_markers():
    got = parse_markdown("- [x] 끝\n- [ ] 안 끝\n* [X] 대문자\n1. [x] 번호는 그대로\n- [x]\n- [y] 아님")
    assert [(b["m"], b["c"]) for b in got] == [
        ("✓", [["t", "끝"]]), ("☐", [["t", "안 끝"]]), ("✓", [["t", "대문자"]]), ("1.", [["t", "[x] 번호는 그대로"]]),
        ("•", [["t", "[x]"]]), ("•", [["t", "[y] 아님"]])]


def test_structures_do_not_leak_into_code_blocks():
    got = parse_markdown("```\n# 제목\n> 인용\n| a | b |\n|---|---|\n```")
    assert got == [{"t": "code", "x": "# 제목\n> 인용\n| a | b |\n|---|---|"}]


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
    "# 하나\n## 둘\n### 셋\n#### 넷\n#태그\n  # 들여씀", "---\n***\n___\n--\n- - -", "> 인용\n> 둘째\n>\n본문\n>붙여씀",
    "| 항목 | 값 |\n|:--|--:|\n| a | **b** |\n| c |\n| d | e | f |\n\n뒤", "| c | d |\n| e | f |", "|---|---|\n| a | b |",
    "| a | b |\n|---|", "| a |\n|---|\n| b |", "||\n|-|\n||", "항목 | 값\n--- | ---", "| 마지막 줄만 |",
    "- [x] 끝\n- [ ] 안 끝\n* [X] 대문자\n1. [x] 번호\n- [x]\n- [y] 아님\n  - [x] 안쪽",
    "[글](http://a.b/c) 와 [x](y) [빈 주소]() [글](공 백) [**b**](u)", "```\n# 제목\n| a | b |\n|---|---|\n```\n| 표 |\n|---|\n| 행 |",
    "# 제목 **굵게** [링크](u)\n> 인용 `코드`\n| **머리** | [글](u) |\n|---|---|\n| `c` | d |",
    "\t| 탭 | 표 |\n\t|---|---|", "   | 셋칸 | 들여씀 |\n   |---|---|\n   | a | b |",
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


# ---- 핵심어 표시 -----------------------------------------------------------------------


def test_split_highlight_rules():
    assert split_highlight("", ["a"]) == []
    assert split_highlight("abc", []) == [["abc", False]] and split_highlight("abc", ["", "  "]) == [["abc", False]]
    assert split_highlight("Redis 5.x 와 redis", ["redis"]) == [["Redis", True], [" 5.x 와 ", False], ["redis", True]]
    assert split_highlight("포트 6379 사용", ["6379", "포트"]) == [["포트", True], [" ", False], ["6379", True], [" 사용", False]]
    assert split_highlight("abcd", ["ab", "abc"]) == [["abc", True], ["d", False]]  # 같은 자리면 긴 것
    assert split_highlight("abcd", ["bc", "ab"]) == [["ab", True], ["cd", False]]  # 겹치면 왼쪽 것
    assert "".join(t for t, _ in split_highlight("가나다 라마 가나", ["가나", "마"])) == "가나다 라마 가나"  # 글자는 하나도 안 변한다


HL_CASES = [
    ("", ["a"]), ("abc", []), ("Redis 5.x 와 redis", ["redis"]), ("포트 6379 사용", ["6379", "포트"]), ("abcd", ["ab", "abc"]),
    ("abcd", ["bc", "ab"]), ("가나다 라마 가나", ["가나", "마"]), ("AbC aBc", ["abc", "ABC"]), ("같은 같은", ["같은"]), ("a", ["a", "a"]),
    ("공백 포함 키워드 입니다", ["포함 키워드", " 입니다 "]), ("😀 abc 😀", ["abc"]), ("한 글", [" "]), ("x", ["", "y"]),
]


def js_hl_source() -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"/\* HL-BEGIN \*/(.*?)/\* HL-END \*/", tpl, re.S)
    assert m, "템플릿에 HL-BEGIN / HL-END 표시가 없다"
    return m.group(1)


def test_js_highlight_block_has_no_dom_or_html_apis():
    src = js_hl_source()
    for bad in ("document", "innerHTML", "createElement", "eval", "Function"):
        assert bad not in src, bad


@pytest.mark.skipif(shutil.which("node") is None, reason="node가 없으면 JS 쪽 비교는 건너뜀 (브라우저 수동 확인 목록 참고)")
def test_js_highlight_matches_python_reference():
    runner = js_hl_source() + "\nvar cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" \
        "process.stdout.write(JSON.stringify(cases.map(function (c) { return hlSplit(c[0], c[1]); })));\n"
    res = subprocess.run([shutil.which("node"), "-e", runner], input=json.dumps(HL_CASES), capture_output=True,
                         text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == [split_highlight(t, k) for t, k in HL_CASES]

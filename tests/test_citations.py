"""인용 확인 규칙: 글자는 그대로, 겉모양만 무시. 가짜 인용은 항상 무효."""

import pytest

from src.eval.citations import STATUS_TEXT, normalize, verify_citation

DOC = [
    "# 제목",                                           # 1
    "- **Redis** 는 [큐](http://x/y) 용도로 쓴다.",      # 2
    "| 항목 | 값 |",                                     # 3
    "| 포트 | 6379 |",                                   # 4
    "> 인용 줄: “둥근 따옴표”와 – 대시",                  # 5
    "같은 문장입니다 입니다 입니다.",                      # 6
    "나중에 다시 나오는 문장입니다 입니다 입니다.",         # 7
    "짧다",                                              # 8
    "개발 PC의 CPU는 AMD Ryzen 5 5600X 이다.",           # 9
]


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.md").write_text("\n".join(DOC) + "\n", encoding="utf-8")
    (d / "b.md").write_text("다른 문서의 문장입니다 여기\n", encoding="utf-8")
    (tmp_path / "secret.md").write_text("사본 밖의 비밀 문장입니다 여기\n", encoding="utf-8")
    return d


SHOWN = {"a.md": [(1, 9)]}


def check(corpus, line, quote, file="a.md", shown=SHOWN):
    return verify_citation({"file": file, "line": line, "quote": quote}, shown, corpus)


# ---- 정리 규칙 ---------------------------------------------------------------------


@pytest.mark.parametrize("a,b", [
    ("## 제목", "제목"), ("- 항목 하나", "항목 하나"), ("1. 항목 하나", "항목 하나"), ("2) 항목 하나", "항목 하나"), ("> 인용", "인용"),
    ("- [x] 끝낸 일", "끝낸 일"), ("**굵게** 와 `코드`", "굵게 와 코드"), ("[링크 글](http://a/b)", "링크 글"), ("![대체](x.png)", "대체"),
    ("| a | b |", "a b"), ("<b>태그</b> 글", "태그 글"), ("A  B\tC", "a b c"), ("ＡＢＣ １２", "abc 12"), ("“따옴표” ‘작은’", '"따옴표" \'작은\''),
    ("a – b — c", "a - b - c"), ("a b", "a b"), ("a​b", "ab"), (r"\*별\* \_밑줄\_", "*별* _밑줄_"),
])
def test_normalize_rules_ignore_only_decoration(a, b):
    assert normalize(a) == normalize(b).replace(" ", "")  # 공백은 모두 없앤다


def test_normalize_keeps_what_matters():
    assert normalize("mala_eval_docs") == "mala_eval_docs"  # 단어 안의 _ 는 그대로
    assert normalize("2 * 3") == "2*3"  # 곱셈의 * 도 그대로
    assert normalize("3,000") != normalize("3000")  # 숫자 표기는 다른 문장
    assert normalize("가 나") == normalize("가나")  # 공백 차이는 같은 문장


# ---- 통과 ----------------------------------------------------------------------------


@pytest.mark.parametrize("line,quote", [
    (2, "Redis 는 큐 용도로 쓴다."), (2, "**Redis** 는 [큐](http://x/y) 용도로 쓴다."), (2, "redis는큐용도로쓴다"),
    (4, "포트 6379"), (4, "| 포트 | 6379 |"), (5, '인용 줄: "둥근 따옴표"와 - 대시'), (9, "AMD Ryzen 5 5600X"), (9, "amd ryzen 5 5600x 이다"),
    (9, "개발 PC의 CPU"),
])
def test_same_sentence_passes(corpus, line, quote):
    r = check(corpus, line, quote)
    assert r["status"] == "ok" and r["valid"] is True and r["matched_line"] is None, r


# ---- 무효 ----------------------------------------------------------------------------


def test_reordered_dropped_or_reformatted_is_not_the_same_sentence(corpus):
    assert check(corpus, 2, "큐 용도로 Redis 는 쓴다.")["status"] == "not_found"  # 순서 바꿈
    assert check(corpus, 2, "Redis 는 용도로 쓴다.")["status"] == "not_found"  # 단어 빼기
    assert check(corpus, 4, "포트 6,379")["status"] == "not_found"  # 숫자 표기
    assert check(corpus, 9, "AMD Ryzen 7 5600X")["status"] == "not_found"


def test_wrong_line_is_its_own_reason_and_reports_the_real_line(corpus):
    r = check(corpus, 6, "나중에 다시 나오는 문장입니다")  # 7줄에 있음
    assert r["status"] == "wrong_line" and r["matched_line"] == 7 and r["valid"] is False
    assert STATUS_TEXT["wrong_line"] == "줄 번호만 틀림"
    near = check(corpus, 7, "같은 문장입니다 입니다")  # 6줄에 있음
    assert near["status"] == "wrong_line" and near["matched_line"] == 6


def test_ellipsis_multiline_and_length_limits(corpus):
    assert check(corpus, 2, "Redis 는 … 쓴다.")["status"] == "ellipsis"
    assert check(corpus, 2, "Redis 는 ... 쓴다.")["status"] == "ellipsis"
    assert check(corpus, 2, "Redis 는\n큐 용도로")["status"] == "bad_format"
    assert check(corpus, 2, "가" * 301)["status"] == "bad_format"
    assert check(corpus, 8, "짧다")["status"] == "too_short"  # 정리 후 6글자 미만
    assert check(corpus, 2, "Redis")["status"] == "too_short"


def test_file_and_line_must_be_what_the_judge_was_shown(corpus):
    assert check(corpus, 1, "다른 문서의 문장입니다 여기", file="b.md")["status"] == "file_not_provided"  # b.md는 안 보여 줬다
    assert check(corpus, 2, "Redis 는 큐 용도로 쓴다.", shown={"a.md": [(3, 9)]})["status"] == "out_of_range"  # 보여 준 줄 밖
    assert check(corpus, 99, "아무 문장이나 입니다 여기")["status"] == "out_of_range"  # 문서 밖의 줄 번호
    assert check(corpus, 1, "x" * 10, file="../secret.md", shown={"../secret.md": [(1, 1)]})["status"] == "out_of_range"  # 사본 밖 경로는 읽지 않는다
    assert check(corpus, 1, "사본 밖의 비밀 문장입니다", file="../secret.md", shown={"../secret.md": [(1, 1)]})["valid"] is False


@pytest.mark.parametrize("cit", [
    None, "문장", [], {}, {"file": "a.md", "line": 2}, {"file": "a.md", "line": 2, "quote": "Redis 는 큐", "extra": 1},
    {"file": "a.md", "line": "2", "quote": "Redis 는 큐 용도로"}, {"file": "a.md", "line": True, "quote": "Redis 는 큐 용도로"},
    {"file": "a.md", "line": 0, "quote": "Redis 는 큐 용도로"}, {"file": 3, "line": 2, "quote": "Redis 는 큐 용도로"},
    {"file": "a.md", "line": 2, "quote": 7},
])
def test_bad_shapes_are_recorded_not_raised(corpus, cit):
    r = verify_citation(cit, SHOWN, corpus)
    assert r["status"] == "bad_format" and r["valid"] is False


def test_fake_quote_is_never_valid_and_long_input_is_trimmed(corpus):
    r = check(corpus, 2, "존재하지 않는 문장을 지어냈습니다 정말로")
    assert r["status"] == "not_found" and not r["valid"]
    long = verify_citation({"file": "a" * 500, "line": 2, "quote": "q" * 400}, SHOWN, corpus)
    assert len(long["file"]) <= 200 and len(long["quote"]) <= 300

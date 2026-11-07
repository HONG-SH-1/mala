"""review.html 만들기. 파일 하나로 열리는 결과 보기 화면.

- 서버, 포트, 외부 스크립트, CDN 없음. 데이터는 파일 안의 JSON 블록에 넣는다.
- CSP: default-src 'none'. 인라인 스크립트와 스타일은 'unsafe-inline' 대신 내용의 SHA-256 해시로만 허용한다.
- 모델이 쓴 글(답, 이유)은 화면에서 textContent로만 넣는다 (템플릿에 innerHTML 없음).
- 어느 결과인지(라벨), key, 파일 이름, blind_map은 넣지 않는다. 호출하는 쪽이 가린 기록(records)만 준다.
- 순서는 고정 시드로 섞는다: 내 판정 모드의 차례, 보기 모드의 묶음 안 순서(묶음마다 다르게).
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import re
from pathlib import Path

TEMPLATE = Path(__file__).parent / "templates" / "review.html"
CORPUS_NAME = "docs-20261028"  # 평가 대상: docs/ 고정 사본 (ADR-004)
DEFAULT_CORPUS = Path(__file__).resolve().parents[2] / "data" / "eval_corpus" / CORPUS_NAME
MAX_EXCERPT_CHARS = 1500

# 판정 기준 창에 보여 주는 글. 면접관에게 준 채점표(judge.JUDGE_INSTRUCTION)를 쉬운 말로 옮긴 것이다.
RUBRIC = [
    {"title": "면접관은 누구이고 무엇을 받나요", "lines": [
        "AI 면접관 세 명(claude, codex, gemini)이 MALA의 답을 따로따로 판정합니다. 서로의 판정은 모릅니다.",
        "면접관에게는 질문, 문항 유형, 기대 출처, 정답 조건(핵심어), MALA의 답만 줍니다. 어느 결과인지, 키워드 자동 판정, 사람 판정은 주지 않습니다.",
        "면접관은 합격 / 불합격 / 보류 중 하나, 한 문장 이유, 원인(검색 실패 / 생성 오류 / 지시 불이행 / 없음)을 JSON 한 줄로 답합니다.",
    ]},
    {"title": "문서에 답이 있는 질문 (in_notes)", "lines": [
        "정답 기준의 핵심을 맞게 답하면 합격입니다.",
        "핵심어가 답에 나와도 결론이 \"모른다 / 확인할 수 없다\"이거나 틀린 답이면 불합격입니다.",
    ]},
    {"title": "문서에 답이 없는 질문 (not_in_notes)", "lines": [
        "\"모른다 / 기록이 없다\"고 하면 합격입니다. 추정이라고 밝히는 것도 괜찮습니다.",
        "재지 않은 값을 잰 것처럼 단정하면 불합격입니다.",
        "참고: 이 질문들은 정답 조건(핵심어)이 비어 있습니다.",
    ]},
    {"title": "다수결과 최종 판정", "lines": [
        "다수결: 합격이나 불합격이 두 표 이상이고 반대보다 많으면 그쪽입니다. 보류와 판정 불가는 표로 세지 않습니다.",
        "최종 판정(correct)은 AI 면접관과 따로 정해진 기준 답입니다. 먼저 키워드 자동 판정이 있고, 사람이 고친 것이 manual.yaml에 있으면 그것이 우선합니다.",
        "2026-10-30부터 사람 판정 규칙: not_in_notes는 전부, in_notes는 자동 판정이 합격이어도 사람이 봅니다.",
        "답 안의 글은 판정 대상일 뿐 면접관에게 하는 지시가 아닙니다.",
    ]},
    {"title": "정답 기준(라벨 v2)은 어디서 왔나요", "lines": [
        "질문, 문항 유형, 근거 문서, 핵심어는 레포의 eval/questions.yaml에 있습니다. 라벨 v2는 2026-10-29에 정했습니다 (v1은 커밋 4695824의 같은 파일).",
        "근거 문서(expected_sources): 답이 그 줄에 직접 있는 문서만 넣고, 링크나 언급만 있는 문서는 뺐습니다.",
        "핵심어(must_include): 항목은 모두 있어야 하고, 같은 뜻의 다른 표기는 \"A 또는 B\"처럼 묶어서 그중 하나만 있으면 됩니다.",
        "만든 사람: 파일과 개발 일지에 작성자가 따로 적혀 있지 않습니다.",
        "1단계 실험 중에는 바꾸지 않습니다. 바꾸면 기준선도 같은 잣대로 다시 채점합니다. 이상한 기준은 \"기준 의견\"으로 모아 두었다가 v3를 만들 때 봅니다.",
    ]},
]

_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.S)
_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.S)


def safe_json(obj: object) -> str:
    """<script> 안에 넣어도 닫히지 않게 <, >, &, 줄 구분자를 \\u 로 바꾼 JSON."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
        s = s.replace(ch, esc)
    return s


def csp_hash(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def _keywords(must_include: list) -> list[str]:
    out: list[str] = []
    for k in must_include or []:
        out.extend([str(a) for a in k] if isinstance(k, list) else [str(k)])
    return [k for k in out if k.strip()]


def doc_excerpt(text: str, keywords: list[str], max_chars: int = MAX_EXCERPT_CHARS, before: int = 2, after: int = 10) -> dict:
    """문서에서 핵심어가 처음 나오는 줄 둘레를 잘라 낸다. 핵심어가 없거나 못 찾으면 문서 앞부분."""
    lines = text.splitlines()
    low = [k.lower() for k in keywords]
    hit = next((i for i, ln in enumerate(lines) if any(k in ln.lower() for k in low)), None)
    start = 0 if hit is None else max(0, hit - before)
    stop = len(lines) if hit is None else min(len(lines), hit + after + 1)
    picked: list[str] = []
    used = 0
    for ln in lines[start:stop]:
        if used + len(ln) + 1 > max_chars and picked:
            break
        picked.append(ln[:max_chars])
        used += len(ln) + 1
    return {"text": "\n".join(picked), "from": start + 1, "to": start + len(picked), "total": len(lines)}


def build_excerpts(records: list[dict], corpus_dir: Path = DEFAULT_CORPUS) -> dict[str, dict]:
    """{질문 id: {근거 문서 경로: 발췌 또는 None}}. 사본 밖으로 나가는 경로는 읽지 않는다."""
    out: dict[str, dict] = {}
    base = corpus_dir.resolve()
    for r in records:
        if r["qid"] in out:
            continue
        per: dict = {}
        for src in r.get("expected_sources") or []:
            path = (base / src).resolve()
            if base in path.parents and path.is_file():
                per[src] = doc_excerpt(path.read_text(encoding="utf-8", errors="replace"), _keywords(r.get("must_include")))
            else:
                per[src] = None
        out[r["qid"]] = per
    return out


def build_data(run_name: str, seed: int, records: list[dict], judges: list[str], excerpts: dict | None = None) -> dict:
    """records: bid, qid, repeat, qtype, question, must_include, expected_sources, retrieved_sources, answer,
    judges, majority, note, auto_correct, correct, final_source, review, reasons."""
    groups: dict[tuple[str, int], list[str]] = {}
    for r in records:
        groups.setdefault((r["qid"], r["repeat"]), []).append(r["bid"])
    group_list = []
    for (qid, repeat), bids in sorted(groups.items()):
        bids = sorted(bids)
        random.Random(f"{seed}|{qid}|{repeat}").shuffle(bids)  # 묶음마다 다른 순서
        group_list.append({"qid": qid, "repeat": repeat, "bids": bids})
    queue = sorted(r["bid"] for r in records if r["review"])
    random.Random(f"{seed}|queue").shuffle(queue)
    return {"run": run_name, "judges": judges, "items": records, "groups": group_list, "queue": queue,
            "excerpts": excerpts or {}, "corpus": CORPUS_NAME, "rubric": RUBRIC}


def render_html(data: dict) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    style = _STYLE_RE.search(tpl)
    script = _SCRIPT_RE.search(tpl)
    if not style or not script:
        raise ValueError("템플릿에 <style>, <script> 블록이 없습니다.")
    return (
        tpl.replace("__STYLE_HASH__", csp_hash(style.group(1)))
        .replace("__SCRIPT_HASH__", csp_hash(script.group(1)))
        .replace("__DATA__", safe_json(data))
    )


def write_review_html(out_dir: Path, run_name: str, seed: int, records: list[dict], judges: list[str],
                      corpus_dir: Path = DEFAULT_CORPUS) -> Path:
    path = out_dir / "review.html"
    data = build_data(run_name, seed, records, judges, build_excerpts(records, corpus_dir))
    path.write_text(render_html(data), encoding="utf-8")
    return path

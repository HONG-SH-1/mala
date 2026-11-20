"""정답을 아는 교란 답(합성) 만들기 — 토론 측정 표본을 늘리려는 것이다 (ADR-006). 공식 평가와 섞지 않는다.

만드는 방법은 기계적이다. 사람이 판단할 일이 없다:
1. 원래 결과에서 최종 판정이 합격(correct=True)인 in_notes 답을 고른다.
2. 그 질문의 must_include 항목(필수 사실) 하나를 골라, 답 안의 그 값을 정해진 틀린 값으로 **전부** 바꾼다
   (고정 치환표, 숫자는 첫 자리 바꾸기).
3. 정답이 확실해야 하므로 아래를 모두 만족할 때만 쓴다. 하나라도 어기면 그 답은 버린다.
   - 바꾼 뒤 원래 값(같은 뜻의 다른 표기 포함)이 답에 하나도 남지 않는다.
   - 틀린 값이 그 질문의 근거 문서에 없다 (우연히 맞는 값이 되지 않게).
   - 그래서 필수 사실이 틀린 값으로 바뀐 답이므로 불합격이 정답이다 (correct=False).
통제용으로 바꾸지 않은 답도 넣는다: 원래 결과의 최종 판정이 합격이고 사람 블라인드 판정도 합격인 것만 (correct=True).

레코드의 label은 synthetic-perturbed / synthetic-control 이고, synthetic 필드에 원본 키와 바꾼 값이 남는다.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from src.eval.citations import read_doc_lines

PERTURBED = "synthetic-perturbed"
CONTROL = "synthetic-control"

# 소문자 -> 틀린 값. 틀린 값은 그 질문의 근거 문서에 없을 때만 쓴다.
SWAPS = {
    "ollama": "vLLM", "bios": "Windows 업데이트", "hermes": "Mistral", "chroma": "FAISS", "키워드 폴백": "BM25 폴백",
    "5600x": "7800X3D", "총 파라미터": "활성 파라미터", "전체 파라미터": "활성 파라미터", "total param": "active param",
    "retrieve": "summarize", "validate": "translate", "redis": "RabbitMQ", "이중화": "단일화", "cursor": "Windsurf", "claude": "Gemini",
}
# 날짜, 형식처럼 예시나 다른 표기로 같은 사실을 또 말할 수 있는 항목(2026-05-19, YYYY-MM-DD)은 치환표에서 뺐다:
# 한 곳만 바꾸면 답 안에 맞는 사실이 남아 정답이 불확실해지기 때문이다.
_NUMBER = re.compile(r"[0-9][0-9.,]*")


def wrong_value(alt: str) -> str | None:
    """같은 뜻의 표기 하나에 대한 틀린 값. 치환표에 없고 숫자도 아니면 None(그 답은 버린다)."""
    low = alt.lower()
    if low in SWAPS:
        return SWAPS[low]
    if _NUMBER.fullmatch(alt):
        first = alt[0]
        new_first = str((int(first) + 2) % 9 + 1)  # 1~9 중 원래와 다른 수
        return new_first + alt[1:]
    return None


def _alts(group) -> list[str]:
    return [str(x) for x in group] if isinstance(group, list) else [str(group)]


def _replace_all(text: str, old: str, new: str) -> str:
    return re.sub(re.escape(old), lambda m: new, text, flags=re.IGNORECASE)


def perturb(answer: str, must_include: list, doc_text_lower: str, rng: random.Random) -> tuple[str, list[list[str]]] | None:
    """답에서 필수 사실 하나를 틀린 값으로 바꾼다. 조건을 못 맞추면 None."""
    present = [g for g in must_include if any(a.lower() in answer.lower() for a in _alts(g))]
    if not present:
        return None
    group = rng.choice(present)
    alts = _alts(group)
    new_answer = answer
    replaced: list[list[str]] = []
    for a in alts:
        if a.lower() not in answer.lower():
            continue
        w = wrong_value(a)
        if w is None or w.lower() in doc_text_lower or w.lower() == a.lower():
            return None
        new_answer = _replace_all(new_answer, a, w)
        replaced.append([a, w])
    if not replaced or new_answer == answer:
        return None
    # 같은 뜻의 다른 표기까지 포함해 원래 값이 하나도 남으면 안 된다
    if any(a.lower() in new_answer.lower() for a in alts):
        return None
    return new_answer, replaced


def build_synthetic(records: list[dict], questions: list, corpus_dir: Path, *, human_blind_pass: set[str] | None = None,
                    n_perturbed: int = 20, n_controls: int = 6, seed: int = 11) -> list[dict]:
    """records: 원래 결과 줄들(label, id, repeat, answer, correct, retrieved_sources ...). human_blind_pass: 사람 블라인드 판정이 합격인 원본 키."""
    rng = random.Random(seed)
    by_q = {q.id: q for q in questions}
    docs_cache: dict[str, str] = {}

    def doc_text(q) -> str:
        if q.id not in docs_cache:
            docs_cache[q.id] = "\n".join("\n".join(read_doc_lines(corpus_dir, s) or []) for s in q.expected_sources).lower()
        return docs_cache[q.id]

    pool: dict[str, list[dict]] = {}
    for r in records:
        q = by_q.get(r.get("id"))
        if q and q.type == "in_notes" and r.get("correct") is True and r.get("answer"):
            pool.setdefault(q.id, []).append(r)
    for rs in pool.values():
        rng.shuffle(rs)
    qids = sorted(pool)
    rng.shuffle(qids)

    out: list[dict] = []
    counters: dict[tuple[str, str], int] = {}

    def add(label: str, r: dict, answer: str, truth: bool, extra: dict) -> None:
        n = counters[(label, r["id"])] = counters.get((label, r["id"]), 0) + 1
        out.append({"label": label, "repeat": n, "id": r["id"], "type": "in_notes", "question": r.get("question"), "answer": answer,
                    "auto_correct": truth, "correct": truth, "retrieved_sources": list(r.get("retrieved_sources") or []),
                    "synthetic": {"origin": f"{r.get('label')}|{r.get('id')}|{r.get('repeat')}", **extra}})

    taken = 0
    progressed = True
    used: set[tuple] = set()
    while taken < n_perturbed and progressed:  # 질문을 돌아가며 하나씩 (한 질문에 몰리지 않게)
        progressed = False
        for qid in qids:
            if taken >= n_perturbed:
                break
            for r in pool[qid]:
                key = (r["label"], r["repeat"], qid)
                if key in used:
                    continue
                res = perturb(r["answer"], by_q[qid].must_include, doc_text(by_q[qid]), rng)
                used.add(key)
                if res is None:
                    continue
                add(PERTURBED, r, res[0], False, {"kind": "perturbed", "replaced": res[1]})
                taken += 1
                progressed = True
                break
    controls = 0
    for r in records:
        if controls >= n_controls:
            break
        key = f"{r.get('label')}|{r.get('id')}|{r.get('repeat')}"
        if human_blind_pass and key in human_blind_pass and r.get("correct") is True and by_q.get(r.get("id")) and r.get("answer"):
            add(CONTROL, r, r["answer"], True, {"kind": "control"})
            controls += 1
    return out

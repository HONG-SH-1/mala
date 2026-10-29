"""평가 재채점 — 모델을 다시 돌리지 않고, 저장된 결과 jsonl을 다시 판정한다.

질문 파일(expected_sources, must_include)이나 수동 판정이 바뀌었을 때 쓴다.
원래 jsonl은 그대로 두고, 같은 폴더에 <이름>_rescored.jsonl과 .md를 새로 쓴다 (--suffix로 바꿈).

    python -m src.scripts.eval_rescore eval/results/20261028-2205_baseline-docs.jsonl \
        --questions eval/questions.yaml \
        --manual eval/results/20261028-2205_baseline-docs.manual.yaml

수동 판정 파일 형식 (id: 전 회차 공통, 또는 회차별 목록):

    q08: true
    q18: [true, false]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

from src.eval.runner import (
    Question,
    _pct,
    _rate,
    auto_verdict,
    file_sha8,
    load_questions,
    source_hit,
    summarize,
    write_jsonl,
)


def load_records(path: str | Path) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_manual(path: str | Path) -> dict[str, list[bool]]:
    """수동 판정 파일을 읽어 {id: [회차별 판정]}으로 만든다. 값 하나면 전 회차에 쓴다."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("수동 판정 파일은 'id: true/false' 형식이어야 합니다.")
    manual: dict[str, list[bool]] = {}
    for qid, value in raw.items():
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(v, bool) for v in values):
            raise ValueError(f"{qid}: 판정은 true/false 또는 그 목록이어야 합니다.")
        manual[str(qid)] = values
    return manual


def _manual_for(manual: dict[str, list[bool]], qid: str, repeat: int) -> bool | None:
    values = manual.get(qid)
    if values is None:
        return None
    if len(values) == 1:
        return values[0]
    return values[repeat - 1]


def rescore(
    records: list[dict],
    questions: list[Question],
    manual: dict[str, list[bool]] | None = None,
) -> list[dict]:
    """source_hit와 auto_correct를 다시 계산하고, 최종 판정(correct)을 붙인 사본을 돌려준다.

    최종 판정은 수동 판정이 있으면 그것, 없으면 자동 판정이다.
    수동 판정 파일 값이 jsonl에 원래 있던 manual_correct보다 우선한다.
    """
    manual = manual or {}
    by_id = {q.id: q for q in questions}
    repeats = max((r["repeat"] for r in records), default=0)

    errors = [f"{rid}: 질문 파일에 없는 id" for rid in sorted({r["id"] for r in records} - by_id.keys())]
    errors += [f"{qid}: 결과에 없는 id" for qid in sorted(manual.keys() - {r["id"] for r in records})]
    errors += [
        f"{qid}: 회차별 판정이 {len(v)}개인데 결과는 {repeats}회"
        for qid, v in manual.items()
        if len(v) not in (1, repeats)
    ]
    if errors:
        raise ValueError("재채점 오류:\n- " + "\n- ".join(errors))

    out: list[dict] = []
    for r in records:
        q = by_id[r["id"]]
        new = dict(r)
        new["type"] = q.type
        new["source_hit"] = (
            source_hit(q.expected_sources, r["retrieved_sources"])
            if q.type == "in_notes"
            else None
        )
        new["auto_correct"] = auto_verdict(q, r["answer"])
        m = _manual_for(manual, q.id, r["repeat"])
        if m is not None:
            new["manual_correct"] = m
        new["correct"] = (
            new["manual_correct"] if new.get("manual_correct") is not None else new["auto_correct"]
        )
        out.append(new)
    return out


def summarize_rescored(records: list[dict]) -> dict:
    """runner.summarize(자동 판정 기준)에 최종 판정 기준 값을 더한다."""
    summary = summarize(records)
    first = [r for r in records if r["repeat"] == 1]
    summary["final_correct_rate"], summary["final_judged"] = _rate([r["correct"] for r in first])
    summary["final_in_notes_rate"], _ = _rate(
        [r["correct"] for r in first if r["type"] == "in_notes"]
    )
    summary["final_not_in_notes_rate"], _ = _rate(
        [r["correct"] for r in first if r["type"] == "not_in_notes"]
    )
    summary["final_all_repeats_rate"], summary["final_all_judged"] = _rate(
        [r["correct"] for r in records]
    )
    summary["manual_changed"] = sum(
        1
        for r in records
        if r.get("manual_correct") is not None and r["manual_correct"] != r["auto_correct"]
    )
    if summary["repeats"] >= 2:
        by_id: dict[str, list[dict]] = {}
        for r in records:
            by_id.setdefault(r["id"], []).append(r)
        same = [len({r["correct"] for r in rs}) == 1 for rs in by_id.values()]
        summary["final_same_verdict_rate"] = sum(same) / len(same)
    return summary


def render_markdown(meta: dict, summary: dict, records: list[dict]) -> str:
    lines = [
        f"# 재채점 결과: {meta['source']}",
        "",
        f"- 재채점 시각: {meta['rescored_at']}",
        f"- 질문 파일: {meta['questions']} (sha256 {meta.get('questions_sha8') or '-'})",
        f"- 수동 판정: {meta['manual'] or '없음'}",
        f"- 질문 {summary['questions']}개 x {summary['repeats']}회",
        "- 응답 시간과 토큰은 다시 재지 않았습니다. 원래 결과 .md를 보세요.",
        "",
        "| 지표 | 값 |",
        "| --- | --- |",
        f"| 정답률 (최종, 수동 우선) | {_pct(summary['final_correct_rate'])} "
        f"({summary['final_judged']}개 판정) |",
        f"| 정답률 (자동 판정) | {_pct(summary['auto_correct_rate'])} |",
        f"| 노트에 있는 질문 정답률 (최종) | {_pct(summary['final_in_notes_rate'])} |",
        f"| 노트에 없는 질문에 '모른다' (최종) | {_pct(summary['final_not_in_notes_rate'])} |",
        f"| 출처 일치율 | {_pct(summary['source_hit_rate'])} |",
        f"| 전 회차 정답률 (최종) | {_pct(summary['final_all_repeats_rate'])} "
        f"({summary['final_all_judged']}개 기록) |",
        f"| 수동 판정이 자동과 다른 기록 | {summary['manual_changed']}개 |",
    ]
    if "final_same_verdict_rate" in summary:
        lines.append(
            f"| 반복 시 최종 판정이 같은 비율 | {_pct(summary['final_same_verdict_rate'])} |"
        )
    lines += [
        "",
        "## 문항별",
        "",
        "회차별 판정을 `/`로 나눠 적습니다 (1회차/2회차/...). 수동 판정이 없으면 `-`.",
        "",
        "| id | 유형 | 출처 | 자동 | 수동 | 최종 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    mark = {True: "O", False: "X", None: "-"}
    by_id: dict[str, list[dict]] = {}
    for r in records:
        by_id.setdefault(r["id"], []).append(r)
    for qid, rs in by_id.items():
        rs = sorted(rs, key=lambda r: r["repeat"])
        first = rs[0]
        lines.append(
            f"| {qid} | {first['type']} | {mark[first['source_hit']]} | "
            + " | ".join(
                "/".join(mark[r.get(key)] for r in rs)
                for key in ("auto_correct", "manual_correct", "correct")
            )
            + " |"
        )
    lines += [
        "",
        "비율은 1회차 기준입니다 ('전 회차 정답률'만 모든 회차).",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MALA 평가 재채점 (모델 호출 없음)")
    parser.add_argument("results", help="eval_run이 남긴 결과 jsonl")
    parser.add_argument("--questions", default="eval/questions.yaml")
    parser.add_argument("--manual", default=None, help="수동 판정 yaml (선택)")
    parser.add_argument(
        "--suffix",
        default="_rescored",
        help="결과 파일 이름 끝 (기본 _rescored). 라벨이 바뀌면 예: _rescored-v2",
    )
    args = parser.parse_args(argv)

    src = Path(args.results)
    try:
        records = load_records(src)
        questions = load_questions(args.questions)
        manual = load_manual(args.manual) if args.manual else {}
        rescored = rescore(records, questions, manual)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    meta = {
        "source": src.name,
        "rescored_at": datetime.now().isoformat(timespec="seconds"),
        "questions": args.questions,
        "questions_sha8": file_sha8(args.questions),
        "manual": args.manual,
    }
    report = render_markdown(meta, summarize_rescored(rescored), rescored)

    out_jsonl = src.with_name(f"{src.stem}{args.suffix}.jsonl")
    out_md = src.with_name(f"{src.stem}{args.suffix}.md")
    write_jsonl(out_jsonl, rescored)
    out_md.write_text(report, encoding="utf-8")

    print(report)
    print(f"저장: {out_jsonl}, {out_md.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

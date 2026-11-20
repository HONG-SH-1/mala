"""정답을 아는 교란 답(합성) 만들기 — 토론 측정 표본 늘리기 (ADR-006). 공식 평가와 분리: data/eval/synthetic/ 에만 쓴다 (git 제외).

    python -m src.scripts.eval_synth --name synth1 \\
        --from eval/results/20261030-2139_baseline-docs-ctrl_rescored-v2.jsonl ... \\
        --human-from data/eval/judge/20261107-1428_full120 --perturbed 20 --controls 6

만든 파일을 면접관에게 먼저 돌린다 (1라운드):
    python -m src.scripts.eval_judge data/eval/synthetic/synth1_rescored-v2.jsonl --judges claude,codex,gemini --tag synth1
그 뒤 갈린 건만 토론:
    python -m src.scripts.eval_judge --debate data/eval/judge/<실행폴더> --dry-run

원래 결과의 컬렉션이 mala_eval_docs가 아니면 만들지 않는다 (외부 면접관에 보낼 수 있는 결과만 쓴다).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.eval.judge_guard import ALLOWED_PREFIX, collections_of
from src.eval.judge_human import load_human
from src.eval.judge_report import DEFAULT_CORPUS
from src.eval.runner import load_questions
from src.eval.synth import build_synthetic
from src.scripts.eval_rescore import load_records

_ROOT = Path(__file__).resolve().parents[2]
SYNTH_DIR = _ROOT / "data" / "eval" / "synthetic"
DEFAULT_FROM = [
    "eval/results/20261028-2205_baseline-docs_rescored-v2.jsonl",
    "eval/results/20261030-2139_baseline-docs-ctrl_rescored-v2.jsonl",
    "eval/results/20261030-2134_baseline-docs-prefix_rescored-v2.jsonl",
]


def make(name: str, sources: list[str], questions: str, human_from: str | None, n_perturbed: int, n_controls: int, seed: int,
         out_dir: Path = SYNTH_DIR, root: Path = _ROOT, corpus_dir: Path = DEFAULT_CORPUS) -> tuple[Path, int, int]:
    for f in sources:  # 안전장치: 원래 결과가 모두 공개 문서 컬렉션이어야 한다
        names = collections_of(f, root)
        if not names or not all(n.startswith(ALLOWED_PREFIX) for n in names):
            raise SystemExit(f"{Path(f).name}: 공개 문서 컬렉션({ALLOWED_PREFIX}...)이 아니거나 알 수 없어 합성하지 않습니다.")
    records = [r for f in sources for r in load_records(f)]
    passed: set[str] = set()
    if human_from:
        passed = {k for k, h in load_human(Path(human_from)).items() if h.get("blind") is True and h.get("human_verdict") == "합격"}
    rows = build_synthetic(records, load_questions(questions), corpus_dir, human_blind_pass=passed, n_perturbed=n_perturbed,
                           n_controls=n_controls, seed=seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / f"{name}_rescored-v2.jsonl"
    jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    # 안전장치(judge_guard)가 읽는 짝 .md: 원래 결과가 모두 mala_eval_docs라서 이 이름을 적는다
    (out_dir / f"{name}.md").write_text(
        "# 합성 교란 답 (공식 평가가 아님)\n\n- 원래 결과: " + ", ".join(Path(f).name for f in sources) + f", 컬렉션: {ALLOWED_PREFIX}\n"
        "- 교란 답은 필수 사실 하나를 틀린 값으로 바꿨으므로 정답이 불합격이다. 통제 답은 바꾸지 않은 답이다.\n", encoding="utf-8")
    return jsonl, sum(1 for r in rows if r["label"] == "synthetic-perturbed"), sum(1 for r in rows if r["label"] == "synthetic-control")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="정답을 아는 교란 답(합성)을 만든다. 공식 평가와 분리.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--from", dest="sources", nargs="+", default=DEFAULT_FROM)
    ap.add_argument("--questions", default="eval/questions.yaml")
    ap.add_argument("--human-from", default=None, help="통제 답을 고를 실행 폴더 (human.jsonl의 blind=true 합격만 씀)")
    ap.add_argument("--perturbed", type=int, default=20)
    ap.add_argument("--controls", type=int, default=6)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    jsonl, p, c = make(args.name, args.sources, args.questions, args.human_from, args.perturbed, args.controls, args.seed)
    print(f"만들었습니다: {jsonl} (교란 {p}건, 통제 {c}건)")
    if p < args.perturbed:
        print(f"참고: 조건을 만족하는 교란 답이 {p}건뿐입니다 (요청 {args.perturbed}).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

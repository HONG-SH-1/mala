"""평가 실행 — 질문 파일을 study 모드(--inline)로 돌리고 결과를 data/eval/에 남긴다.

    # 질문 파일 형식만 검사 (Ollama 없이, 노트북에서도 가능)
    python -m src.scripts.eval_run --questions eval/questions.yaml --dry-run

    # 기준선 측정 (데스크톱, Ollama와 Redis 실행 중)
    python -m src.scripts.eval_run --questions eval/questions.yaml --label baseline --repeat 2

    # 검색만 재기 (답변 모델과 Redis 없이, 임베딩 때문에 Ollama는 필요)
    python -m src.scripts.eval_run --questions eval/questions.yaml --retrieval-only --label ret-k3-keyword
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", message=r"The default value of `allowed_objects`")

from src.config import get_settings
from src.eval.runner import (
    _norm_path,
    default_run_fn,
    default_search_fn,
    load_questions,
    render_markdown,
    render_retrieval_markdown,
    run_eval,
    run_meta,
    run_env,
    run_retrieval_eval,
    summarize,
    summarize_retrieval,
    write_jsonl,
)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("chromadb").setLevel(logging.CRITICAL)


def _check_sources_exist(questions, settings) -> list[str]:
    """expected_sources가 실제 노트 경로와 맞는지 본다. 볼트가 없으면 건너뛴다."""
    from src.retrieval.pipeline import resolve_vault_path

    try:
        vault = resolve_vault_path(settings)
    except (ValueError, FileNotFoundError) as exc:
        return [f"볼트를 찾지 못해 출처 경로 확인은 건너뜀: {exc}"]
    existing = {_norm_path(str(p.relative_to(vault))) for p in vault.rglob("*.md")}
    problems = []
    for q in questions:
        for src in q.expected_sources:
            want = _norm_path(src)
            if not any(e == want or e.endswith("/" + want) for e in existing):
                problems.append(f"{q.id}: 볼트에 '{src}' 노트가 없습니다.")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MALA 평가 실행")
    parser.add_argument("--questions", default="eval/questions.yaml")
    parser.add_argument("--label", default="run", help="결과 파일 이름에 붙일 이름 (예: baseline)")
    parser.add_argument("--repeat", type=int, default=1, help="같은 질문을 몇 번 돌릴지")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개만 (시험용)")
    parser.add_argument("--out-dir", default="data/eval")
    parser.add_argument("--dry-run", action="store_true", help="질문 파일 검사만 하고 끝냄")
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="답변 모델 없이 검색만 잰다 (in_notes 질문, 1회)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        questions = load_questions(args.questions)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.limit:
        questions = questions[: args.limit]

    n_in = sum(q.type == "in_notes" for q in questions)
    print(f"질문 {len(questions)}개 (노트에 있음 {n_in}, 없음 {len(questions) - n_in})")
    for p in _check_sources_exist(questions, settings):
        print("  주의:", p)

    if args.dry_run:
        print("형식 검사 통과. 실제 측정은 --dry-run 없이 실행하세요.")
        return 0

    from src.retrieval.chroma_store import ChromaVaultStore

    if ChromaVaultStore(settings).count() == 0:
        print("Chroma가 비어 있습니다. 먼저: python -m src.scripts.build_index", file=sys.stderr)
        return 1

    meta = run_meta(settings, label=args.label, questions_path=args.questions)
    if meta["git_dirty_src"]:
        print("  주의: src에 커밋 안 된 변경이 있습니다. 기준선이면 커밋 상태에서 재는 게 맞습니다.")

    if args.retrieval_only:
        return _run_retrieval_only(args, questions, settings, meta)

    total = len(questions) * args.repeat
    done = 0

    def _progress(rec: dict) -> None:
        nonlocal done
        done += 1
        mark = {True: "O", False: "X", None: "?"}[rec["auto_correct"]]
        print(f"  [{done}/{total}] {rec['id']} {mark} {rec['wall_ms']}ms")

    records = run_eval(
        questions,
        run_fn=default_run_fn(settings),
        label=args.label,
        repeat=args.repeat,
        on_record=_progress,
    )
    summary = summarize(records)

    out_dir = _out_dir(args, settings)
    stem = f"{datetime.now():%Y%m%d-%H%M}_{args.label}"
    write_jsonl(out_dir / f"{stem}.jsonl", [{**r, "run_env": run_env(meta)} for r in records])
    report = render_markdown(meta, summary, records)
    (out_dir / f"{stem}.md").write_text(report, encoding="utf-8")

    print()
    print(report)
    print(f"저장: {out_dir / stem}.jsonl, .md")
    return 0


def _out_dir(args, settings) -> Path:
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = settings.project_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _run_retrieval_only(args, questions, settings, meta) -> int:
    if args.repeat != 1:
        print("  주의: --retrieval-only는 1회만 돕니다 (--repeat 무시).")
    print(f"  rerank: {settings.rag_rerank}, TOP_K: {settings.rag_top_k}")

    def _progress(rec: dict) -> None:
        rank = rec["evidence_rank_expected"]
        print(f"  {rec['id']} 출처 {'O' if rec['source_hit'] else 'X'} 근거 {rank or 'X'}")

    records = run_retrieval_eval(
        questions,
        search_fn=default_search_fn(settings),
        label=args.label,
        on_record=_progress,
    )
    out_dir = _out_dir(args, settings)
    stem = f"{datetime.now():%Y%m%d-%H%M}_{args.label}"
    write_jsonl(out_dir / f"{stem}.jsonl", [{**r, "run_env": run_env(meta)} for r in records])
    report = render_retrieval_markdown(meta, summarize_retrieval(records), records)
    (out_dir / f"{stem}.md").write_text(report, encoding="utf-8")

    print()
    print(report)
    print(f"저장: {out_dir / stem}.jsonl, .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

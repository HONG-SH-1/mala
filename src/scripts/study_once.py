"""V1.5 — study mode: always vault RAG + filter observability + source citations."""

from __future__ import annotations

import argparse
import logging
import sys
import warnings

warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects`",
)

from src.agents.graph import run_task
from src.config import get_settings
from src.retrieval.chroma_store import ChromaVaultStore
from src.retrieval.pipeline import (
    VaultIndexer,
    compute_vault_filter_stats,
    format_citations,
    log_vault_filter_stats,
    resolve_vault_path,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logging.getLogger("chromadb").setLevel(logging.CRITICAL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MALA study mode (vault RAG)")
    parser.add_argument(
        "question",
        nargs="?",
        default="이 노트에서 핵심 개념을 요약해줘",
        help="Question (always uses vault RAG; no keyword required)",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Re-index vault before query",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Call Ollama directly (no worker.py)",
    )
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    vault = resolve_vault_path(settings)
    print(f"Vault: {vault}")

    filter_stats = compute_vault_filter_stats(vault, settings)
    log_vault_filter_stats(filter_stats)

    if filter_stats.included == 0:
        print(
            "No markdown files match OBSIDIAN_INCLUDE — fix .env or run build_index.",
            file=sys.stderr,
        )
        return 1

    if not args.skip_index:
        stats = VaultIndexer(settings).index_vault(force=args.reindex)
        print(
            f"Index: scanned={stats.files_scanned} +{stats.added} "
            f"~{stats.updated} chunks={stats.chunks_upserted}"
        )

    count = ChromaVaultStore(settings).count()
    if count == 0:
        print("Chroma empty — run: python -m src.scripts.build_index", file=sys.stderr)
        return 1
    print(f"Chroma chunks: {count}")

    if not args.inline:
        print("Note: python -m src.worker in another terminal", file=sys.stderr)

    final = run_task(
        args.question,
        use_queue=not args.inline,
        settings=settings,
        use_hermes_router=False,
        force_vault_rag=True,
    )

    print("--- STUDY RUN ---")
    print(f"task_id: {final['task_id']}")
    print(f"route: {final.get('route_decision')}")
    print(f"history: {final.get('history', [])}")

    chunks = final.get("retrieved_chunks") or []
    if chunks:
        print(f"retrieved_chunks: {len(chunks)}")
        for i, c in enumerate(chunks[:5], 1):
            print(f"  [{i}] {c.get('source')} — {c.get('heading')}")

    print("--- answer ---")
    print(final.get("answer") or "(empty)")

    cites = format_citations(chunks)
    if cites:
        print(cites)

    if final.get("valid"):
        print("--- STUDY SUCCESS ---")
        return 0
    print("--- STUDY FAILED ---", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

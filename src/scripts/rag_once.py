"""Phase 3 — index vault (if needed) + LangGraph RAG E2E."""

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
from src.retrieval.pipeline import VaultIndexer, resolve_vault_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logging.getLogger("chromadb").setLevel(logging.CRITICAL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MALA RAG E2E (Phase 3)")
    parser.add_argument(
        "--task",
        default="vault 노트에서 MALA Phase 2가 무엇인지 한 문장으로 설명해줘",
        help="Must trigger route=needs_context (옵시디언/노트/vault/검색 등)",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Run full index before query",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Ollama direct (no worker.py)",
    )
    parser.add_argument("--skip-index", action="store_true", help="Skip index step")
    args = parser.parse_args(argv)

    settings = get_settings()
    vault = resolve_vault_path(settings)
    print(f"Vault: {vault}")

    if not args.skip_index:
        stats = VaultIndexer(settings).index_vault(force=args.reindex)
        print(
            f"Index: +{stats.added} ~{stats.updated} chunks={stats.chunks_upserted}"
        )

    count = ChromaVaultStore(settings).count()
    if count == 0:
        print("Chroma collection empty — run build_index first.", file=sys.stderr)
        return 1
    print(f"Chroma chunks: {count}")

    if not args.inline:
        print("Note: python -m src.worker in another terminal", file=sys.stderr)

    final = run_task(args.task, use_queue=not args.inline, settings=settings)
    print("--- RAG RUN ---")
    print(f"task_id: {final['task_id']}")
    print(f"route: {final.get('route_decision')}")
    print(f"history: {final.get('history', [])}")
    if final.get("analysis_result"):
        print("--- retrieved context (preview) ---")
        preview = final["analysis_result"][:500]
        print(preview + ("..." if len(final["analysis_result"]) > 500 else ""))
    print("--- answer ---")
    print(final.get("answer") or "(empty)")

    if final.get("valid"):
        print("--- RAG SUCCESS ---")
        return 0
    print("--- RAG FAILED ---", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

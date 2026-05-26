"""Build or refresh Chroma index from Obsidian vault (Phase 3)."""

from __future__ import annotations

import argparse
import logging
import sys

from src.retrieval.pipeline import VaultIndexer, resolve_vault_path
from src.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logging.getLogger("chromadb").setLevel(logging.CRITICAL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index Obsidian vault into Chroma")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index all files (ignore manifest)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    vault = resolve_vault_path(settings)
    print(f"Vault: {vault}")
    print(f"Embed model: {settings.ollama_embed_model}")
    print("Ensure: ollama pull", settings.ollama_embed_model)

    try:
        stats = VaultIndexer(settings).index_vault(force=args.force)
    except Exception as exc:
        print(f"Index failed: {exc}", file=sys.stderr)
        return 1

    print("--- INDEX OK ---")
    print(
        f"files={stats.files_scanned} added={stats.added} "
        f"updated={stats.updated} removed={stats.removed} "
        f"skipped_unchanged={stats.skipped_unchanged} "
        f"chunks_upserted={stats.chunks_upserted} failed={stats.files_failed}"
    )
    if stats.files_failed:
        print(f"DLQ: {settings.index_failures_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

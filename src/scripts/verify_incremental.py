"""Chaos-style check: N synthetic MD files, touch 1, re-index — expect N-1 skip."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CHAOS_ROOT = _ROOT / "data" / "chaos_verify"


def _apply_chaos_env() -> None:
    vault = _CHAOS_ROOT / "vault"
    os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
    os.environ["CHROMA_PERSIST_DIR"] = str(_CHAOS_ROOT / "chroma")
    os.environ["INDEX_MANIFEST_PATH"] = str(_CHAOS_ROOT / "manifest.json")
    os.environ["INDEX_FAILURES_PATH"] = str(_CHAOS_ROOT / "failures.jsonl")


def _write_synthetic_vault(vault: Path, count: int) -> None:
    if vault.exists():
        shutil.rmtree(vault)
    vault.mkdir(parents=True)
    for i in range(count):
        (vault / f"note_{i:03d}.md").write_text(
            f"# Note {i}\n\nbody {i}\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify SHA-256 incremental indexing (synthetic vault)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of synthetic markdown files (use 100 for full chaos)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep data/chaos_verify after run",
    )
    args = parser.parse_args(argv)

    if args.count < 2:
        print("--count must be >= 2", file=sys.stderr)
        return 1

    _apply_chaos_env()
    vault = _CHAOS_ROOT / "vault"
    _write_synthetic_vault(vault, args.count)

    from src.retrieval.pipeline import VaultIndexer

    print(f"Chaos vault: {vault} ({args.count} files)")
    print("Run 1: full index (force)...")
    indexer = VaultIndexer()
    run1 = indexer.index_vault(force=True)
    embed_calls_run1 = run1.chunks_upserted

    target = vault / "note_042.md"
    if not target.exists():
        target = vault / "note_001.md"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n<!-- chaos touch -->\n", encoding="utf-8")
    print(f"Touched: {target.name}")

    print("Run 2: incremental index...")
    run2 = indexer.index_vault(force=False)

    print("--- VERIFY RESULT ---")
    print(
        f"run1: files={run1.files_scanned} chunks_upserted={run1.chunks_upserted}"
    )
    print(
        f"run2: +{run2.added} ~{run2.updated} skip={run2.skipped_unchanged} "
        f"chunks_upserted={run2.chunks_upserted} failed={run2.files_failed}"
    )

    ok = (
        run2.updated == 1
        and run2.added == 0
        and run2.removed == 0
        and run2.chunks_upserted >= 1
        and run2.skipped_unchanged == args.count - 1
        and run2.files_failed == 0
    )

    if ok:
        print(
            f"--- INCREMENTAL OK: {run2.skipped_unchanged} unchanged, "
            f"1 updated, embed work only for changed file ---"
        )
    else:
        print("--- INCREMENTAL FAIL ---", file=sys.stderr)
        if run2.updated != 1:
            print(
                f"  expected updated=1, got {run2.updated}",
                file=sys.stderr,
            )
        if run2.skipped_unchanged != args.count - 1:
            print(
                f"  expected skip={args.count - 1}, "
                f"got {run2.skipped_unchanged}",
                file=sys.stderr,
            )
        return 1

    if not args.keep:
        shutil.rmtree(_CHAOS_ROOT, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())

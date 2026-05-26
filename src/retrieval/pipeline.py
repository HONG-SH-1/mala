"""Vault scan, incremental index, and semantic search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.config import Settings, get_settings
from src.retrieval.chunker import chunk_markdown
from src.retrieval.chroma_store import ChromaVaultStore, SearchHit
from src.retrieval.index_dlq import append_index_failure
from src.retrieval.manifest import (
    diff_manifest,
    file_sha256,
    load_manifest,
    save_manifest,
)
from src.retrieval.rerank import rerank_hits

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules"}


@dataclass
class IndexStats:
    files_scanned: int
    added: int
    updated: int
    removed: int
    chunks_upserted: int
    unchanged: int
    files_failed: int
    skipped_unchanged: int


def resolve_vault_path(settings: Settings) -> Path:
    raw = settings.obsidian_vault_path.strip()
    if not raw:
        raise ValueError(
            "OBSIDIAN_VAULT_PATH is empty. Set it in .env "
            "(e.g. vault_sample or your Obsidian vault)."
        )
    path = Path(raw)
    if not path.is_absolute():
        path = settings.project_root / path
    if not path.is_dir():
        raise FileNotFoundError(f"Vault not found: {path}")
    return path.resolve()


def iter_markdown_files(vault: Path) -> list[Path]:
    files: list[Path] = []
    for path in vault.rglob("*.md"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _rel_source(vault: Path, file_path: Path) -> str:
    return file_path.relative_to(vault).as_posix()


def _scan_hashes(
    vault: Path,
    md_files: list[Path],
    previous: dict[str, str],
    settings: Settings,
) -> tuple[dict[str, str], int]:
    current: dict[str, str] = {}
    failures = 0
    for file_path in md_files:
        rel = _rel_source(vault, file_path)
        try:
            current[rel] = file_sha256(file_path)
        except OSError as exc:
            failures += 1
            append_index_failure(
                rel, str(exc), phase="hash", settings=settings
            )
            logger.warning("Hash skip %s: %s", rel, exc)
            if rel in previous:
                current[rel] = previous[rel]
    return current, failures


def _index_one_file(
    vault: Path,
    rel: str,
    store: ChromaVaultStore,
    settings: Settings,
) -> int:
    file_path = vault / Path(rel)
    text = file_path.read_text(encoding="utf-8", errors="replace")
    store.delete_source(rel)
    chunks = chunk_markdown(text, rel)
    return store.upsert_chunks(chunks)


class VaultIndexer:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._store = ChromaVaultStore(self._settings)

    def index_vault(self, *, force: bool = False) -> IndexStats:
        settings = self._settings
        vault = resolve_vault_path(settings)
        manifest_path = Path(settings.index_manifest_path)
        if not manifest_path.is_absolute():
            manifest_path = settings.project_root / manifest_path

        previous = {} if force else load_manifest(manifest_path)
        md_files = iter_markdown_files(vault)
        current, scan_failures = _scan_hashes(
            vault, md_files, previous, settings
        )

        added, changed, removed = diff_manifest(current, previous)
        if force:
            added = list(current.keys())
            changed = []
            removed = list(previous.keys())

        chunks_upserted = 0
        index_failures = scan_failures
        manifest_out = dict(previous)

        for rel in added + changed:
            try:
                n = _index_one_file(vault, rel, self._store, settings)
                chunks_upserted += n
                manifest_out[rel] = current[rel]
            except OSError as exc:
                index_failures += 1
                append_index_failure(
                    rel, str(exc), phase="index", settings=settings
                )
                logger.warning("Index skip %s: %s", rel, exc)
                if rel in previous:
                    manifest_out[rel] = previous[rel]
                elif rel in manifest_out:
                    del manifest_out[rel]

        for rel in removed:
            self._store.delete_source(rel)
            manifest_out.pop(rel, None)

        save_manifest(manifest_path, manifest_out)
        unchanged = len(current) - len(added) - len(changed)
        skipped = max(unchanged, 0)

        stats = IndexStats(
            files_scanned=len(md_files),
            added=len(added),
            updated=len(changed),
            removed=len(removed),
            chunks_upserted=chunks_upserted,
            unchanged=unchanged,
            files_failed=index_failures,
            skipped_unchanged=skipped,
        )
        logger.info(
            "Index done: files=%s +%s ~%s -%s skip=%s chunks=%s "
            "failed=%s total_in_chroma=%s",
            stats.files_scanned,
            stats.added,
            stats.updated,
            stats.removed,
            stats.skipped_unchanged,
            stats.chunks_upserted,
            stats.files_failed,
            self._store.count(),
        )
        return stats


class VaultRetriever:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._store = ChromaVaultStore(self._settings)

    def search(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        k = top_k or self._settings.rag_top_k
        pool = min(max(k * 4, k), 20)
        candidates = self._store.search(query, pool)
        return rerank_hits(query, candidates, k)

    def format_context(self, hits: list[SearchHit]) -> str:
        if not hits:
            return ""
        parts = []
        for i, hit in enumerate(hits, 1):
            parts.append(
                f"[{i}] {hit.source} — {hit.heading}\n{hit.text[:1200]}"
            )
        return "\n\n".join(parts)

    def hits_to_chunks(self, hits: list[SearchHit]) -> list[dict]:
        return [
            {
                "id": h.chunk_id,
                "source": h.source,
                "heading": h.heading,
                "text": h.text,
                "distance": h.distance,
            }
            for h in hits
        ]

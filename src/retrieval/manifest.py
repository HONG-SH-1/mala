"""SHA-256 manifest for incremental vault indexing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def diff_manifest(
    current: dict[str, str],
    previous: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Return (added, changed, removed) relative paths."""
    added = [p for p in current if p not in previous]
    removed = [p for p in previous if p not in current]
    changed = [
        p for p in current if p in previous and current[p] != previous[p]
    ]
    return added, changed, removed

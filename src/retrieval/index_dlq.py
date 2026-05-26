"""Per-file index failures — append-only DLQ log."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import Settings, get_settings


def resolve_failures_path(settings: Settings) -> Path:
    path = Path(settings.index_failures_path)
    if not path.is_absolute():
        path = settings.project_root / path
    return path


def append_index_failure(
    rel: str,
    error: str,
    *,
    phase: str,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    path = resolve_failures_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": rel,
        "phase": phase,
        "error": error,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

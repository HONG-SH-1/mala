"""Preflight — paths and services before Hermes / RAG."""

from __future__ import annotations

import sys
from pathlib import Path

from src.config import get_settings


def main() -> int:
    s = get_settings()
    ok = True
    lines: list[str] = []

    def check(label: str, good: bool, detail: str) -> None:
        nonlocal ok
        mark = "OK" if good else "FAIL"
        if not good:
            ok = False
        lines.append(f"  [{mark}] {label}: {detail}")

    lines.append("=== MALA preflight ===\n")

    try:
        from src.retrieval.pipeline import resolve_vault_path

        vault = resolve_vault_path(s)
        md = list(vault.rglob("*.md"))
        check("Obsidian vault", True, f"{vault} ({len(md)} .md files)")
    except Exception as exc:
        check("Obsidian vault", False, str(exc))

    chroma = Path(s.chroma_persist_dir)
    if not chroma.is_absolute():
        chroma = s.project_root / chroma
    check("Chroma dir", chroma.is_dir(), str(chroma))

    manifest = Path(s.index_manifest_path)
    if not manifest.is_absolute():
        manifest = s.project_root / manifest
    check("Index manifest", manifest.exists(), str(manifest))

    try:
        import redis

        r = redis.Redis(
            host=s.redis_host, port=s.redis_port, db=s.redis_db, socket_timeout=2
        )
        r.ping()
        check("Redis", True, f"{s.redis_host}:{s.redis_port}")
    except Exception as exc:
        check("Redis", False, f"{exc} (start Native Redis for worker/rag)")

    try:
        import httpx

        with httpx.Client(timeout=3) as c:
            c.get(f"{s.ollama_base_url.rstrip('/')}/api/tags")
        check("Ollama API", True, s.ollama_base_url)
    except Exception as exc:
        check("Ollama API", False, str(exc))

    lines.append(f"\n  Chat model:   {s.ollama_model}")
    lines.append(f"  Embed model:  {s.ollama_embed_model}")
    lines.append(f"  Router model: {s.ollama_router_model} (pull before Phase 4)")
    lines.append(f"  USE_HERMES:   {s.use_hermes_router}")
    lines.append(f"  MAX_TOOL:     {s.max_tool_steps}")

    print("\n".join(lines))
    if ok:
        print("\n--- PREFLIGHT OK (paths/services) ---")
        return 0
    print("\n--- PREFLIGHT: fix FAIL items ---", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

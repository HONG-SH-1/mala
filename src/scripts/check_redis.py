"""Smoke test — Redis ping without Ollama."""

from __future__ import annotations

import sys

from src.broker import RedisBroker
from src.config import get_settings


def main() -> None:
    settings = get_settings()
    broker = RedisBroker(settings)
    if broker.ping():
        print(f"Redis OK: {settings.redis_host}:{settings.redis_port}")
        return
    print(
        f"Redis FAIL: {settings.redis_host}:{settings.redis_port} — start Native Redis.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()

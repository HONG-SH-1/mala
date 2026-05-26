"""Phase 2 — LangGraph orchestrator E2E (Redis task_status + optional worker queue)."""

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
from src.broker.task_status import TaskStatusStore
from src.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run LangGraph once (Phase 2)")
    parser.add_argument(
        "--task",
        default="Summarize what MALA Phase 2 adds in two sentences.",
        help="User instruction passed into the graph",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Call Ollama directly (no worker.py required)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    use_queue = not args.inline
    if use_queue:
        print(
            "Note: start worker in another terminal: "
            "python -m src.worker",
            file=sys.stderr,
        )

    final = run_task(args.task, use_queue=use_queue, settings=settings)
    store = TaskStatusStore(settings)
    status = store.get_all(final["task_id"])

    print("--- GRAPH RUN ---")
    print(f"task_id: {final['task_id']}")
    print(f"route: {final.get('route_decision')}")
    print(f"valid: {final.get('valid')}")
    print(f"error_count: {final.get('error_count', 0)}")
    print(f"history: {final.get('history', [])}")
    if final.get("last_error"):
        print(f"last_error: {final['last_error']}")
    print("--- task_status (Redis) ---")
    for k, v in sorted(status.items()):
        print(f"  {k}: {v}")
    print("--- answer ---")
    print(final.get("answer") or "(empty)")

    if final.get("valid"):
        print("--- GRAPH SUCCESS ---")
        return 0
    print("--- GRAPH FAILED ---", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

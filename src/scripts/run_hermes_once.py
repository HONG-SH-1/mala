"""Phase 4 — LangGraph with Hermes router (tool search_vault + circuit breaker)."""

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MALA Hermes router E2E")
    parser.add_argument(
        "--task",
        default="옵시디언 노트에서 환영 메시지가 뭐라고 적혀 있어?",
        help="User question",
    )
    parser.add_argument(
        "--ood",
        action="store_true",
        help="Run OOD test: 2026 World Cup winner (should skip vault search)",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Direct Ollama (no worker.py)",
    )
    args = parser.parse_args(argv)

    if args.ood:
        task = "2026년 FIFA 월드컵 우승팀은 어느 나라야?"
    else:
        task = args.task

    settings = get_settings()
    print(f"Router model: {settings.ollama_router_model}")
    print(f"Chat model:     {settings.ollama_model}")
    print(f"MAX_TOOL_STEPS: {settings.max_tool_steps}")
    if not args.inline:
        print("Note: python -m src.worker in another terminal", file=sys.stderr)

    final = run_task(
        task,
        use_queue=not args.inline,
        settings=settings,
        use_hermes_router=True,
    )

    print("--- HERMES RUN ---")
    print(f"task_id: {final['task_id']}")
    print(f"route: {final.get('route_decision')}")
    print(f"tool_step_count: {final.get('tool_step_count', 0)}")
    print(f"history: {final.get('history', [])}")
    if final.get("analysis_result"):
        print("--- context preview ---")
        print(final["analysis_result"][:400])
    print("--- answer ---")
    print(final.get("answer") or "(empty)")

    if args.ood:
        used_search = any("search_vault" in h for h in final.get("history", []))
        if used_search:
            print("OOD WARN: search_vault was called (expected no tool)", file=sys.stderr)
            return 1
        print("--- OOD OK (no search_vault) ---")
        return 0 if final.get("valid") else 1

    if final.get("valid"):
        print("--- HERMES SUCCESS ---")
        return 0
    print("--- HERMES FAILED ---", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

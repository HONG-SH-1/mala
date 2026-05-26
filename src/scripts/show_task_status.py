"""Print Redis task_status:{task_id} hash."""

from __future__ import annotations

import argparse
import sys

from src.broker.task_status import TaskStatusStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", help="e.g. TASK-a1b2c3d4")
    args = parser.parse_args(argv)

    store = TaskStatusStore()
    data = store.get_all(args.task_id)
    if not data:
        print(f"No task_status for {args.task_id}", file=sys.stderr)
        return 1
    for k, v in sorted(data.items()):
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

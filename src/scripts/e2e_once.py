"""Phase 1 E2E: task_queue → Worker → result_queue (single run)."""

from __future__ import annotations

import logging
import sys
import uuid

import httpx

from src.broker import RedisBroker
from src.config import get_settings
from src.schemas import (
    EnvelopeHeader,
    EnvelopePayload,
    Intent,
    ResultEnvelope,
    TaskEnvelope,
    TaskStatus,
)
from src.worker import handle_message

logger = logging.getLogger(__name__)


def check_ollama(base_url: str) -> None:
    try:
        with httpx.Client(timeout=5.0) as client:
            client.get(f"{base_url.rstrip('/')}/api/tags")
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Ollama not reachable at {base_url} — run `ollama serve` / Ollama app first."
        ) from exc


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = get_settings()
    broker = RedisBroker(settings)

    if not broker.ping():
        logger.error(
            "Redis unreachable at %s:%s. Install/start Native Redis (see README).",
            settings.redis_host,
            settings.redis_port,
        )
        sys.exit(1)

    check_ollama(settings.ollama_base_url)

    task_id = f"TASK-{uuid.uuid4().hex[:8]}"
    envelope = TaskEnvelope(
        header=EnvelopeHeader(
            sender="e2e",
            receiver=settings.worker_id,
            task_id=task_id,
        ),
        payload=EnvelopePayload(
            intent=Intent.ANALYZE,
            instruction="Reply with one short sentence: MALA Phase 1 queue E2E OK.",
            constraints=["Keep under 20 words."],
        ),
    )

    logger.info("Publishing task %s to %s", task_id, settings.task_queue)
    broker.push_task(envelope.to_json())

    raw = broker.claim_task(timeout=5)
    if not raw:
        logger.error("No message on task queue after push")
        sys.exit(1)

    handle_message(broker, settings, raw)

    result_raw = broker.pop_result(timeout=120)
    if not result_raw:
        logger.error("No result on %s within timeout", settings.result_queue)
        sys.exit(1)

    result = ResultEnvelope.from_json(result_raw)
    if result.header.task_id != task_id:
        logger.error("Task ID mismatch: %s vs %s", task_id, result.header.task_id)
        sys.exit(1)

    if result.header.status != TaskStatus.SUCCESS:
        logger.error("Task failed: %s", result.header.error)
        sys.exit(1)

    print("\n--- E2E SUCCESS ---")
    print(f"task_id: {task_id}")
    print(f"model:   {result.payload.model}")
    print(f"reply:   {result.payload.response.strip()[:500]}")
    print("-------------------\n")


if __name__ == "__main__":
    main()

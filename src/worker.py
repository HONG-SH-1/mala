"""Ollama inference worker — consumes task_queue, produces result_queue."""

from __future__ import annotations

import json
import logging
import sys

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.broker import RedisBroker
from src.config import Settings, get_settings
from src.schemas import (
    ResultEnvelope,
    ResultHeader,
    ResultPayload,
    TaskEnvelope,
    TaskStatus,
)

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
    reraise=True,
)
def call_ollama(prompt: str, settings: Settings) -> dict:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
    with httpx.Client(timeout=settings.ollama_timeout_sec) as client:
        response = client.post(
            url,
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()


def build_prompt(envelope: TaskEnvelope) -> str:
    parts = [
        f"Intent: {envelope.payload.intent.value}",
    ]
    ctx = envelope.payload.context or {}
    retrieved = ctx.get("retrieved") or []
    if retrieved:
        parts.append(
            "Use ONLY the following notes as factual context. "
            "If the answer is not in the notes, say you do not know."
        )
        for i, chunk in enumerate(retrieved, 1):
            source = chunk.get("source", "?")
            heading = chunk.get("heading", "?")
            text = chunk.get("text", "")
            parts.append(f"[{i}] ({source}) {heading}\n{text}")
    elif ctx.get("analysis"):
        parts.append("Context:\n" + str(ctx["analysis"]))
    parts.append(envelope.payload.instruction)
    if envelope.payload.constraints:
        parts.append("Constraints: " + "; ".join(envelope.payload.constraints))
    return "\n\n".join(parts)


def handle_message(
    broker: RedisBroker,
    settings: Settings,
    raw: str,
) -> None:
    try:
        envelope = TaskEnvelope.from_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Invalid envelope: %s", exc)
        broker.push_dead_letter(raw)
        broker.ack_processing(raw)
        return

    task_id = envelope.header.task_id
    logger.info("Processing task %s", task_id)

    try:
        ollama_result = call_ollama(build_prompt(envelope), settings)
        result = ResultEnvelope(
            header=ResultHeader(task_id=task_id, status=TaskStatus.SUCCESS),
            payload=ResultPayload(
                response=ollama_result.get("response", ""),
                model=settings.ollama_model,
            ),
        )
        broker.push_result(result.to_json())
        broker.ack_processing(raw)
        logger.info("Task %s success", task_id)
    except Exception as exc:
        logger.exception("Task %s failed: %s", task_id, exc)
        error_result = ResultEnvelope(
            header=ResultHeader(
                task_id=task_id,
                status=TaskStatus.ERROR,
                error=str(exc),
            ),
            payload=ResultPayload(response=""),
        )
        broker.push_result(error_result.to_json())
        broker.push_dead_letter(raw)
        broker.ack_processing(raw)


def process_one(
    broker: RedisBroker | None = None,
    settings: Settings | None = None,
) -> bool:
    """Claim and process one task. Returns False if queue was empty."""
    settings = settings or get_settings()
    broker = broker or RedisBroker(settings)
    raw = broker.claim_task(timeout=0)
    if not raw:
        return False
    handle_message(broker, settings, raw)
    return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = get_settings()
    broker = RedisBroker(settings)
    if not broker.ping():
        logger.error(
            "Redis unreachable at %s:%s — start Native Redis first.",
            settings.redis_host,
            settings.redis_port,
        )
        sys.exit(1)
    logger.info(
        "Worker %s — waiting for tasks (Ctrl+C to stop)",
        settings.worker_id,
    )
    try:
        while True:
            raw = broker.claim_task(timeout=5)
            if raw:
                handle_message(broker, settings, raw)
    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()

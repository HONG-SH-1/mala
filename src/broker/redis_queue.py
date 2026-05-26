"""Redis list queues — reliable claim via BRPOPLPUSH (Redis 5+ compatible)."""

from __future__ import annotations

import redis

from src.config import Settings, get_settings


class RedisBroker:
    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._client = redis.Redis(
            host=self._s.redis_host,
            port=self._s.redis_port,
            db=self._s.redis_db,
            decode_responses=True,
        )

    @property
    def client(self) -> redis.Redis:
        return self._client

    def ping(self) -> bool:
        return bool(self._client.ping())

    def push_task(self, raw: str) -> None:
        self._client.rpush(self._s.task_queue, raw)

    def claim_task(self, timeout: int = 0) -> str | None:
        """Atomically move one message task_queue → processing_queue."""
        return self._client.brpoplpush(
            self._s.task_queue,
            self._s.processing_queue,
            timeout,
        )

    def ack_processing(self, raw: str) -> None:
        self._client.lrem(self._s.processing_queue, 1, raw)

    def push_result(self, raw: str) -> None:
        self._client.rpush(self._s.result_queue, raw)

    def pop_result(self, timeout: int = 30) -> str | None:
        item = self._client.blpop(self._s.result_queue, timeout)
        if item is None:
            return None
        _, raw = item
        return raw

    def push_dead_letter(self, raw: str) -> None:
        self._client.rpush(self._s.dead_letter_queue, raw)

    def requeue_processing(self, raw: str) -> None:
        """Return a stuck processing message to task_queue (manual recovery)."""
        pipe = self._client.pipeline()
        pipe.lrem(self._s.processing_queue, 1, raw)
        pipe.lpush(self._s.task_queue, raw)
        pipe.execute()

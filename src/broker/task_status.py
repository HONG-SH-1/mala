"""Redis Hash — task_status:{task_id} for orchestrator progress."""

from __future__ import annotations

import json
from typing import Any

import redis

from src.config import Settings, get_settings


class TaskStatusStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._client = redis.Redis(
            host=self._s.redis_host,
            port=self._s.redis_port,
            db=self._s.redis_db,
            decode_responses=True,
        )

    def _key(self, task_id: str) -> str:
        return f"{self._s.task_status_prefix}:{task_id}"

    def update(self, task_id: str, fields: dict[str, Any]) -> None:
        key = self._key(task_id)
        mapping = {k: str(v) for k, v in fields.items()}
        self._client.hset(key, mapping=mapping)

    def get_all(self, task_id: str) -> dict[str, str]:
        return self._client.hgetall(self._key(task_id))

    def to_json(self, task_id: str) -> str:
        return json.dumps(self.get_all(task_id), ensure_ascii=False)

"""JSON Envelope — Phase 1 A2A contract."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Intent(str, Enum):
    ROUTE = "route"
    ANALYZE = "analyze"
    CODE = "code"


class TaskStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    INVALID = "invalid"


class EnvelopeHeader(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sender: str
    receiver: str
    task_id: str


class EnvelopePayload(BaseModel):
    intent: Intent
    instruction: str
    context: dict[str, Any] = Field(default_factory=dict)
    context_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class TaskEnvelope(BaseModel):
    header: EnvelopeHeader
    payload: EnvelopePayload

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> TaskEnvelope:
        return cls.model_validate_json(raw)


class ResultHeader(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    task_id: str
    status: TaskStatus
    error: str | None = None


class ResultPayload(BaseModel):
    response: str = ""
    model: str | None = None


class ResultEnvelope(BaseModel):
    header: ResultHeader
    payload: ResultPayload

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> ResultEnvelope:
        return cls.model_validate_json(raw)

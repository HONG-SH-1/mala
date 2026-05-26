import pytest

from src.schemas import (
    EnvelopeHeader,
    EnvelopePayload,
    Intent,
    TaskEnvelope,
    TaskStatus,
    ResultEnvelope,
    ResultHeader,
    ResultPayload,
)


def test_task_envelope_roundtrip():
    env = TaskEnvelope(
        header=EnvelopeHeader(
            sender="test",
            receiver="worker_1",
            task_id="TASK-001",
        ),
        payload=EnvelopePayload(
            intent=Intent.CODE,
            instruction="hello",
        ),
    )
    restored = TaskEnvelope.from_json(env.to_json())
    assert restored.header.task_id == "TASK-001"
    assert restored.payload.intent == Intent.CODE


def test_result_envelope_status():
    res = ResultEnvelope(
        header=ResultHeader(task_id="T1", status=TaskStatus.SUCCESS),
        payload=ResultPayload(response="ok", model="qwen3:8b"),
    )
    data = ResultEnvelope.from_json(res.to_json())
    assert data.header.status == TaskStatus.SUCCESS

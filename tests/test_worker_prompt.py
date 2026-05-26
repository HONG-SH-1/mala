from src.schemas import EnvelopeHeader, EnvelopePayload, Intent, TaskEnvelope
from src.worker import build_prompt


def test_build_prompt_includes_retrieved():
    envelope = TaskEnvelope(
        header=EnvelopeHeader(
            sender="o",
            receiver="w",
            task_id="T1",
        ),
        payload=EnvelopePayload(
            intent=Intent.ANALYZE,
            instruction="What is Phase 2?",
            context={
                "retrieved": [
                    {
                        "source": "Phase-2-Agent.md",
                        "heading": "Phase 2",
                        "text": "LangGraph orchestrator",
                    }
                ]
            },
        ),
    )
    prompt = build_prompt(envelope)
    assert "LangGraph" in prompt
    assert "ONLY the following notes" in prompt

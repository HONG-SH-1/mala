# MALA Overview

MALA (Multi-Agent Local AI) is a personal project for **local** LLM orchestration on RTX 3080 10GB.

## Goals

- Obsidian markdown as the knowledge source
- Redis queues for agent-to-agent messages (JSON envelope)
- LangGraph for routing, retrieval, answer, and validation

## Phases

- **Phase 0:** VRAM proof with `qwen3:8b`
- **Phase 1:** Redis `task_queue` / `result_queue` E2E
- **Phase 2:** LangGraph + `task_status:{task_id}` in Redis
- **Phase 3:** Heading-based chunking, SHA-256 incremental index, Chroma search

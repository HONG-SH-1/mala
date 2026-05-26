# Phase 2 — Agent Layer

Phase 2 adds a **LangGraph** orchestrator on top of Phase 1 Redis queues.

## Workflow

1. `route` — keyword rules (`옵시디언`, `검색`, `code`, etc.)
2. `retrieve` — Chroma vector search + keyword rerank (Phase 3)
3. `answer` — publish to `task_queue`, worker calls Ollama
4. `validate` — minimum answer length; retry to `route` up to `GRAPH_MAX_RETRIES`

## Redis task_status

Progress is stored in hash `task_status:{task_id}` (node name, route, preview).

## Models

Primary chat model: **qwen3:8b** via Ollama (ADR-001). MoE 35B was rejected on 10GB VRAM.

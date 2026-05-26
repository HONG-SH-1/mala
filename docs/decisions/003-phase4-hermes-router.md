# ADR-003: Phase 4 — Hermes-style router (draft)

**Status:** Draft (design only; no code in V1)  
**Date:** 2026-05-26  
**Context:** Gemini/Cursor review — LLM-wiki + function-calling router on 10GB VRAM.

## Decision (proposed)

- **V1 chat model:** `qwen3:8b` (Ollama) — unchanged ([ADR-001](001-inference-engine.md)).
- **Phase 4 experiment:** Hermes 3 8B Q4 (or equivalent FC-tuned 8B) for **tool routing / JSON**, not as a second concurrent model on GPU.
- **VRAM policy:** On RTX 3080 10GB, **do not** run Hermes + Qwen + embed model loaded for inference at the same time. Measure peak with `ollama ps` / `nvidia-smi` per model.
- **If dual-role is needed:** Prefer **model swap** (unload A, load B) or **single model** that handles both route+answer with tools — accept I/O latency vs OOM.

## Consequences

- LangGraph gains a `tools` node (`search_vault`, etc.) with Pydantic validation and `recursion_limit` (infinite retrieval guard).
- Obsidian + Chroma pipeline from Phase 3 is reused; Hermes only changes **how** retrieve is triggered.
- PoC requires one row in [`model-comparison.md`](../model-comparison.md) for Hermes 8B Q4 peak MiB before implementation.

## Not in scope until PoC

- CrewAI, second always-on LLM, 35B MoE.

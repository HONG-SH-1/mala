# ADR-003: Phase 4 — Hermes-style router

**Status:** Accepted — **PoC verified** (2026-05-26)  
**Date:** 2026-05-26  
**Context:** LLM tool routing on RTX 3080 10GB; reuse Phase 3 Chroma + Obsidian.

## Decision

- **V1 chat model:** `qwen3:8b` (Ollama) — unchanged ([ADR-001](001-inference-engine.md)).
- **Phase 4 router:** `hermes3:8b` via Ollama `/api/chat` + `search_vault` tool schema.
- **VRAM policy:** **Do not** keep Hermes + Qwen loaded for inference at the same time on 10GB. Router chat → (optional) embed → Worker generate; accept swap latency vs OOM.
- **Routing fallback:** If Hermes returns no `tool_calls` but the user question matches vault keywords (Obsidian, 노트, 환영, …) and is not OOD (sports, FIFA, …), run Chroma search anyway (`hermes:fallback_search` in history). OOD must not trigger fallback.

## PoC results (2026-05-26)

| Check | Result |
|-------|--------|
| `check_paths` | OK — `USE_HERMES_ROUTER=1` |
| `run_hermes_once --ood` | OOD OK — no vault search (`TASK-9a2e30e5`) |
| `run_hermes_once` (vault) | HERMES SUCCESS — `환영합니다!.md` context, answer matches vault (`TASK-8f744eba`) |
| Hermes VRAM (solo) | **7418 MiB** peak, `ollama ps` **5.2 GB** — [`model-comparison.md`](../model-comparison.md) |
| Native Hermes `tool_calls` | Often empty on Ollama 0.24 — **mitigated by fallback** |

## Consequences

- LangGraph: `USE_HERMES_ROUTER=1` → `hermes_route_node` at `route`; `needs_context` + chunks skips redundant `retrieve`.
- `MAX_TOOL_STEPS` circuit breaker in `hermes_router.py`.
- Models on **`D:\ollama\models`** (Windows: env + `db.sqlite` `settings.models` — see troubleshooting).

## Not in scope (PoC)

- CrewAI, second always-on LLM on GPU, 35B MoE.
- Reliable native tool-calling without fallback (follow-up).
- Web UI / GraphRAG.

## References

- `src/agents/hermes_router.py`, `src/scripts/run_hermes_once.py`
- [`../development-log.md`](../development-log.md) — 2026-05-26
- [`../../troubleshooting/2026-05-26-ollama-models-path-windows.md`](../../troubleshooting/2026-05-26-ollama-models-path-windows.md)

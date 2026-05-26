# Phase 3 — Knowledge / RAG

Phase 3 indexes Obsidian (or `vault_sample`) markdown into **Chroma**.

## Chunking

- Split on ATX headings `#` .. `###`
- Each chunk keeps `source` path and `heading` metadata

## Incremental index

- Per-file **SHA-256** in `data/index_manifest.json`
- Only added/changed files are re-embedded; removed files delete their chunks

## Embeddings

- **Ollama** `nomic-embed-text` (or `OLLAMA_EMBED_MODEL`)
- Retrieved snippets are injected into the worker prompt as context

## Demo query

Ask with vault keywords, e.g. "vault 노트에서 MALA Phase 2 설명".

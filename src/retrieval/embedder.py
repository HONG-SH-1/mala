"""Ollama embedding API for Chroma."""

from __future__ import annotations

import logging

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from src.config import Settings

logger = logging.getLogger(__name__)

# nomic-embed-text는 입력 앞에 용도를 붙여야 질문용·문서용 벡터를 다르게 만든다 (fix-later 17번).
EMBED_PREFIXES = {
    "nomic": {"document": "search_document: ", "query": "search_query: "},
}


def add_prefix(texts: list[str], mode: str, kind: str) -> list[str]:
    """mode가 off면 그대로, 아니면 kind(document|query)에 맞는 접두어를 붙인다."""
    if mode == "off":
        return list(texts)
    prefix = EMBED_PREFIXES[mode][kind]
    return [prefix + t for t in texts]


class OllamaEmbeddingFunction(EmbeddingFunction[Documents]):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.ollama_base_url.rstrip("/")

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []
        return _embed_batch(input, self._settings)


def _embed_batch(texts: list[str], settings: Settings) -> list[list[float]]:
    """Call Ollama /api/embed (fallback /api/embeddings)."""
    timeout = settings.ollama_timeout_sec
    with httpx.Client(timeout=timeout) as client:
        try:
            resp = client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/embed",
                json={"model": settings.ollama_embed_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings")
            if embeddings:
                return embeddings
        except httpx.HTTPError as exc:
            logger.debug("Ollama /api/embed failed: %s", exc)

        out: list[list[float]] = []
        for text in texts:
            resp = client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
                json={"model": settings.ollama_embed_model, "prompt": text},
            )
            resp.raise_for_status()
            out.append(resp.json()["embedding"])
        return out

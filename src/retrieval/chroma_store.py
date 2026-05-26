"""Chroma persistent collection for vault chunks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

# Chroma 0.5.x: telemetry off still logs posthog errors — suppress (harmless to RAG).
logging.getLogger("chromadb").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.config import Settings
from src.retrieval.chunker import TextChunk
from src.retrieval.embedder import OllamaEmbeddingFunction


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    source: str
    heading: str
    text: str
    distance: float | None


class ChromaVaultStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        persist = Path(settings.chroma_persist_dir)
        persist.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._ef = OllamaEmbeddingFunction(settings)
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

    def delete_source(self, source: str) -> None:
        try:
            self._collection.delete(where={"source": source})
        except Exception:
            pass

    def upsert_chunks(self, chunks: list[TextChunk]) -> int:
        if not chunks:
            return 0
        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [
            {
                "source": c.source,
                "heading": c.heading,
                "level": c.level,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ]
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(chunks)

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        if top_k <= 0:
            return []
        result = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[SearchHit] = []
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        for i, chunk_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            hits.append(
                SearchHit(
                    chunk_id=chunk_id,
                    source=meta.get("source", ""),
                    heading=meta.get("heading", ""),
                    text=docs[i] if i < len(docs) else "",
                    distance=dists[i] if i < len(dists) else None,
                )
            )
        return hits

    def count(self) -> int:
        return self._collection.count()

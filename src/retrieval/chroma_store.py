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
from src.retrieval.embedder import OllamaEmbeddingFunction, add_prefix


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
        self._prefix = settings.embed_prefix
        metadata = {"hnsw:space": "cosine"}
        if self._prefix != "off":
            metadata["embed_prefix"] = self._prefix  # 새로 만들 때만 적힌다
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=self._ef,
            metadata=metadata,
        )
        # 접두어 방식이 다른 벡터가 한 컬렉션에 섞이면 거리 비교가 무의미해진다.
        # 키가 없는 기존 컬렉션은 off로 본다.
        stored = (self._collection.metadata or {}).get("embed_prefix", "off")
        if stored != self._prefix:
            raise ValueError(
                f"컬렉션 '{settings.chroma_collection}'은 EMBED_PREFIX={stored}로 색인됐는데 "
                f"지금 설정은 {self._prefix}입니다. 컬렉션이나 EMBED_PREFIX를 맞추세요."
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
        if self._prefix == "off":
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        else:
            # Chroma 0.6은 임베딩 함수에 문서/질문 구분을 안 넘기므로 벡터를 직접 만든다.
            # 저장하는 원문에는 접두어를 붙이지 않는다 (프롬프트와 rerank가 보는 글은 그대로).
            embeddings = self._ef(add_prefix(documents, self._prefix, "document"))
            self._collection.upsert(
                ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings
            )
        return len(chunks)

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        if top_k <= 0:
            return []
        include = ["documents", "metadatas", "distances"]
        if self._prefix == "off":
            result = self._collection.query(
                query_texts=[query], n_results=top_k, include=include
            )
        else:
            result = self._collection.query(
                query_embeddings=self._ef(add_prefix([query], self._prefix, "query")),
                n_results=top_k,
                include=include,
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

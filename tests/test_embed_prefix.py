"""EMBED_PREFIX 스위치 — 실제로 임베딩에 들어가는 글을 확인한다. Ollama 없음, Chroma는 메모리."""

import uuid
from dataclasses import replace

import chromadb
import pytest

from src.config import get_settings
from src.retrieval import chroma_store, embedder
from src.retrieval.chunker import TextChunk
from src.retrieval.embedder import add_prefix


@pytest.fixture
def seen(monkeypatch):
    """_embed_batch를 가짜로 바꿔 받은 글을 모은다. 벡터는 글 길이로 만든다."""
    texts: list[str] = []

    def fake(batch, settings):
        texts.extend(batch)
        return [[float(len(t)), 1.0, 0.0] for t in batch]

    monkeypatch.setattr(embedder, "_embed_batch", fake)
    # 테스트마다 새 메모리 Chroma (파일을 만들지 않는다)
    monkeypatch.setattr(
        chroma_store.chromadb, "PersistentClient", lambda path, settings: chromadb.EphemeralClient()
    )
    return texts


def _store(mode: str, collection: str | None = None):
    s = replace(
        get_settings(),
        embed_prefix=mode,
        chroma_collection=collection or f"t_{uuid.uuid4().hex[:8]}",
        chroma_persist_dir="unused",
    )
    return chroma_store.ChromaVaultStore(s)


CHUNK = TextChunk(source="a.md", heading="제목", level=1, text="Redis 큐 설명", chunk_index=0)


def test_off_sends_text_unchanged(seen):
    store = _store("off")
    store.upsert_chunks([CHUNK])
    hits = store.search("Redis 큐", 1)

    assert seen == ["Redis 큐 설명", "Redis 큐"]
    assert hits[0].text == "Redis 큐 설명"


def test_nomic_prefixes_document_and_query_but_stores_original(seen):
    store = _store("nomic")
    store.upsert_chunks([CHUNK])
    hits = store.search("Redis 큐", 1)

    assert seen == ["search_document: Redis 큐 설명", "search_query: Redis 큐"]
    assert hits[0].text == "Redis 큐 설명"  # 프롬프트·rerank가 보는 원문은 그대로


def test_nomic_collection_metadata_keeps_cosine(seen):
    store = _store("nomic")
    assert store._collection.metadata == {"hnsw:space": "cosine", "embed_prefix": "nomic"}
    assert _store("off")._collection.metadata == {"hnsw:space": "cosine"}


def test_mismatched_collection_is_rejected(seen):
    name = f"t_{uuid.uuid4().hex[:8]}"
    _store("off", name)  # 키 없는 기존 컬렉션 = off
    with pytest.raises(ValueError, match="EMBED_PREFIX"):
        _store("nomic", name)

    name2 = f"t_{uuid.uuid4().hex[:8]}"
    _store("nomic", name2)
    with pytest.raises(ValueError, match="EMBED_PREFIX"):
        _store("off", name2)


def test_add_prefix():
    assert add_prefix(["a"], "off", "document") == ["a"]
    assert add_prefix(["a"], "nomic", "query") == ["search_query: a"]


@pytest.mark.parametrize("value, want", [(None, "off"), ("", "off"), ("NOMIC", "nomic")])
def test_setting_values(monkeypatch, value, want):
    if value is None:
        monkeypatch.delenv("EMBED_PREFIX", raising=False)
    else:
        monkeypatch.setenv("EMBED_PREFIX", value)
    assert get_settings().embed_prefix == want


def test_setting_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("EMBED_PREFIX", "nomic-v2")
    with pytest.raises(ValueError, match="EMBED_PREFIX"):
        get_settings()

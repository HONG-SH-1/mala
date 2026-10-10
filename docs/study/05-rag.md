# RAG 파이프라인 — 청킹 · 증분 매니페스트 · 재정렬 · 벡터 검색

> 학습용 읽기 전용 노트 (2026-10-09 작성). 코드 수정 없음.
> 관련 노트: [`02-ollama-calls.md`](02-ollama-calls.md) · [`03-queue.md`](03-queue.md) · [`04-graph.md`](04-graph.md) · [`fix-later.md`](fix-later.md)
> 검증 환경: Ollama 0.35.1 · `nomic-embed-text` (768차원) · Chroma 0.5.x

```
[인덱싱]  .md 파일 ──chunk_markdown──> TextChunk[] ──OllamaEmbeddingFunction──> Chroma(cosine)
              └──file_sha256──> manifest.json ──diff_manifest──> 변경분만 재인덱싱

[검색]    질문 ──embed(768d)──> HNSW top-12 ──rerank_hits──> top-3 ──> 프롬프트 컨텍스트
```

---

## 1. `src/retrieval/chunker.py` (전체 76줄)

```python
"""Markdown chunking by ATX headings (# .. ###)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class TextChunk:
    source: str
    heading: str
    level: int
    text: str
    chunk_index: int

    @property
    def chunk_id(self) -> str:
        slug = re.sub(r"[^\w\-]+", "-", self.heading.lower()).strip("-") or "root"
        return f"{self.source}::{slug}::{self.chunk_index}"


def chunk_markdown(content: str, source: str) -> list[TextChunk]:
    """Split markdown into chunks; preamble before first heading is one chunk."""
    matches = list(_HEADING_RE.finditer(content))
    if not matches:
        body = content.strip()
        if not body:
            return []
        return [
            TextChunk(
                source=source,
                heading="(document)",
                level=0,
                text=body,
                chunk_index=0,
            )
        ]

    chunks: list[TextChunk] = []
    idx = 0

    preamble = content[: matches[0].start()].strip()
    if preamble:
        chunks.append(
            TextChunk(
                source=source,
                heading="(preamble)",
                level=0,
                text=preamble,
                chunk_index=idx,
            )
        )
        idx += 1

    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        text = f"#{'#' * (level - 1)} {heading}\n\n{body}".strip() if body else heading
        chunks.append(
            TextChunk(
                source=source,
                heading=heading,
                level=level,
                text=text,
                chunk_index=idx,
            )
        )
        idx += 1

    return chunks
```

**한 줄 설명**

| 대상 | 설명 |
|---|---|
| `TextChunk` | 출처·헤딩·레벨·본문·순번을 담은 불변 청크 레코드. |
| `TextChunk.chunk_id` | 헤딩을 슬러그화해 `파일경로::슬러그::순번`으로 **결정적** ID를 만든다(같은 문서를 다시 넣으면 같은 ID → upsert로 덮어쓰기). |
| `chunk_markdown` | 마크다운을 `#`~`###` 헤딩 경계로 쪼개고, 헤딩이 없으면 문서 전체를 1청크, 첫 헤딩 앞 글은 `(preamble)` 청크로 만든다. |

세부:

- 헤딩 정규식은 `^(#{1,3})\s+(.+)$` — **`####` 이하는 경계로 쓰지 않고** 상위 섹션 본문에 포함된다 (`:9`)
- 청크 본문은 헤딩을 다시 한 줄 붙여 저장 (`:64`) → 임베딩·검색 시 헤딩 단어가 본문에도 들어가 가중된다
- 본문이 빈 헤딩은 헤딩 문자열만 청크가 된다 (`:64`의 삼항)
- **크기 상한이 없다** — 긴 섹션 하나가 그대로 한 청크. 아래 6절의 임베더 컨텍스트 2048 토큰 제한과 맞물린다

---

## 2. `src/retrieval/manifest.py` (전체 42줄)

```python
"""SHA-256 manifest for incremental vault indexing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def diff_manifest(
    current: dict[str, str],
    previous: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Return (added, changed, removed) relative paths."""
    added = [p for p in current if p not in previous]
    removed = [p for p in previous if p not in current]
    changed = [
        p for p in current if p in previous and current[p] != previous[p]
    ]
    return added, changed, removed
```

**한 줄 설명**

| 함수 | 설명 |
|---|---|
| `file_sha256` | 64KB 블록 단위로 읽어 파일 내용의 SHA-256 해시를 계산한다(메모리 사용 일정). |
| `load_manifest` | 이전 실행의 `경로 → 해시` 맵을 읽고, 파일이 없으면 빈 딕셔너리를 준다(첫 실행 = 전체 인덱싱). |
| `save_manifest` | 부모 디렉터리까지 만들고 매니페스트를 들여쓴 UTF-8 JSON으로 저장한다. |
| `diff_manifest` | 현재와 이전 해시 맵을 비교해 `(added, changed, removed)` 상대 경로 목록을 돌려준다. |

> **수정 시각(mtime)이 아니라 내용 해시**를 쓰므로, 파일을 열었다 그대로 저장해도 재인덱싱되지 않습니다. 반대로 Git 체크아웃으로 mtime만 바뀌어도 영향이 없습니다.
> `load_manifest`는 JSON이 깨져 있으면 `json.JSONDecodeError`를 그대로 올립니다(빈 맵으로 폴백하지 않음) → 매니페스트 손상 시 인덱싱이 멈춥니다.

---

## 3. `src/retrieval/rerank.py` (전체 51줄)

```python
"""Lightweight rerank: semantic hits + keyword overlap (Phase 3 demo quality)."""

from __future__ import annotations

import re

from src.retrieval.chroma_store import SearchHit

_TOKEN_RE = re.compile(r"[\w가-힣]+", re.UNICODE)


def query_tokens(query: str) -> set[str]:
    q = query.lower()
    tokens = {t for t in _TOKEN_RE.findall(q) if len(t) > 1}
    if re.search(r"phase\s*2", q):
        tokens.update({"phase", "2", "phase-2", "phase2"})
    if re.search(r"phase\s*3", q):
        tokens.update({"phase", "3", "phase-3", "phase3"})
    return tokens


def _phase_source_boost(query: str, source: str) -> int:
    q = query.lower()
    s = source.lower()
    boost = 0
    if re.search(r"phase\s*2", q) and "phase-2" in s:
        boost += 8
    if re.search(r"phase\s*3", q) and "phase-3" in s:
        boost += 8
    return boost


def rerank_hits(query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
    if not hits or top_k <= 0:
        return []
    tokens = query_tokens(query)

    def score(hit: SearchHit) -> tuple[int, float]:
        heading = hit.heading.lower()
        body = f"{hit.source} {hit.text}".lower()
        kw = _phase_source_boost(query, hit.source)
        for t in tokens:
            if t in heading:
                kw += 3
            elif t in body:
                kw += 1
        dist = hit.distance if hit.distance is not None else 1.0
        return (kw, -dist)

    ordered = sorted(hits, key=score, reverse=True)
    return ordered[:top_k]
```

**한 줄 설명**

| 함수 | 설명 |
|---|---|
| `query_tokens` | 질문을 한글·영숫자 토큰으로 쪼개 2글자 이상만 남기고, `phase 2`/`phase 3` 표기 변형(`phase-2`, `phase2`)을 동의어로 끼워 넣는다. |
| `_phase_source_boost` | 질문의 `phase N`과 파일명의 `phase-N`이 맞으면 +8점을 얹어 해당 문서를 끌어올린다. |
| `rerank_hits` | 벡터 후보들을 "키워드 점수 내림차순 → 거리 오름차순"으로 다시 줄 세워 상위 `top_k`만 남긴다. |

점수 규칙 (`:38-47`):

| 항목 | 점수 |
|---|---|
| 토큰이 **헤딩**에 포함 | +3 |
| 토큰이 본문·파일명에 포함 (헤딩에 없을 때만) | +1 |
| `phase N` 파일명 일치 | +8 |
| 동점 처리 | 벡터 거리가 가까운 쪽 우선 (`-dist`) |

> `score`가 `(kw, -dist)` 튜플을 반환하고 `reverse=True`로 정렬되므로 **키워드 점수가 1차 기준, 거리가 2차 기준**입니다. 즉 의미적으로 더 가까운 청크라도 키워드가 하나 덜 겹치면 밀립니다 — 벡터 검색 결과를 키워드가 **덮어쓰는** 구조입니다.
> `phase` 관련 가중치는 `vault_sample/Phase-2-Agent.md` 같은 데모 파일명에 맞춘 하드코딩으로, 주석도 "Phase 3 demo quality"라고 밝히고 있습니다 (`:1`).

---

## 4. `src/retrieval/pipeline.py` — `VaultIndexer` (`:202-276`)

```python
class VaultIndexer:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._store = ChromaVaultStore(self._settings)

    def index_vault(self, *, force: bool = False) -> IndexStats:
        settings = self._settings
        vault = resolve_vault_path(settings)
        manifest_path = Path(settings.index_manifest_path)
        if not manifest_path.is_absolute():
            manifest_path = settings.project_root / manifest_path

        previous = {} if force else load_manifest(manifest_path)
        md_files = iter_markdown_files(vault)
        current, scan_failures = _scan_hashes(
            vault, md_files, previous, settings
        )

        added, changed, removed = diff_manifest(current, previous)
        if force:
            added = list(current.keys())
            changed = []
            removed = list(previous.keys())

        chunks_upserted = 0
        index_failures = scan_failures
        manifest_out = dict(previous)

        for rel in added + changed:
            try:
                n = _index_one_file(vault, rel, self._store, settings)
                chunks_upserted += n
                manifest_out[rel] = current[rel]
            except OSError as exc:
                index_failures += 1
                append_index_failure(
                    rel, str(exc), phase="index", settings=settings
                )
                logger.warning("Index skip %s: %s", rel, exc)
                if rel in previous:
                    manifest_out[rel] = previous[rel]
                elif rel in manifest_out:
                    del manifest_out[rel]

        for rel in removed:
            self._store.delete_source(rel)
            manifest_out.pop(rel, None)

        save_manifest(manifest_path, manifest_out)
        unchanged = len(current) - len(added) - len(changed)
        skipped = max(unchanged, 0)

        stats = IndexStats(
            files_scanned=len(md_files),
            added=len(added),
            updated=len(changed),
            removed=len(removed),
            chunks_upserted=chunks_upserted,
            unchanged=unchanged,
            files_failed=index_failures,
            skipped_unchanged=skipped,
        )
        logger.info(
            "Index done: files=%s +%s ~%s -%s skip=%s chunks=%s "
            "failed=%s total_in_chroma=%s",
            stats.files_scanned,
            stats.added,
            stats.updated,
            stats.removed,
            stats.skipped_unchanged,
            stats.chunks_upserted,
            stats.files_failed,
            self._store.count(),
        )
        return stats
```

**한 줄 설명**

| 메서드 | 설명 |
|---|---|
| `__init__` | 설정을 받아 Chroma 스토어 핸들을 하나 들고 있는다. |
| `index_vault` | vault를 스캔해 해시를 비교하고, 추가·변경 파일만 다시 청킹·upsert하며 삭제 파일은 컬렉션에서 지운 뒤 매니페스트를 갱신하고 통계를 돌려준다. |

처리 순서:

1. `resolve_vault_path` — `.env`의 상대 경로를 프로젝트 루트 기준 절대 경로로 변환, 없으면 `FileNotFoundError` (`:209`)
2. `load_manifest` — `--force`면 이전 매니페스트를 **빈 맵으로 취급** (`:214`)
3. `iter_markdown_files` — `.obsidian`·`.git`·`.trash`·`node_modules`·`_raw` 디렉터리 제외 + `OBSIDIAN_INCLUDE` 접두사 필터 (`:215`)
4. `_scan_hashes` — 읽기 실패 파일은 DLQ에 적고 **이전 해시를 유지**해 변경으로 오판하지 않게 함 (`:216-218`)
5. `diff_manifest` → `added`/`changed`/`removed`, `--force`면 전부 `added`로 재구성 (`:220-224`)
6. 파일별 `_index_one_file` — `delete_source(rel)` 먼저 → 재청킹 → `upsert_chunks` (고아 청크 방지, `:189-199`)
7. 실패 파일은 `append_index_failure` 후 **매니페스트를 되돌려** 다음 실행에서 재시도되게 함 (`:235-244`)
8. `removed` 파일은 컬렉션에서 삭제 + 매니페스트에서 제거 (`:246-248`)
9. `save_manifest` → `IndexStats` 반환 + Chroma 총 개수 로그 (`:250-275`)

> 실패 격리가 꽤 촘촘합니다 — 파일 1개가 깨져도 전체 인덱싱이 멈추지 않고, 매니페스트에 성공분만 반영되어 다음 실행에서 자동 재시도됩니다.
> 반면 `unchanged = len(current) - len(added) - len(changed)`(`:251`)는 `--force`일 때 `added`가 전체라 **0 또는 음수**가 될 수 있어 `max(unchanged, 0)`으로 막아 두었습니다 (`:252`).

---

## 5. `src/retrieval/pipeline.py` — `VaultRetriever` (`:279-310`)

```python
class VaultRetriever:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._store = ChromaVaultStore(self._settings)

    def search(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        k = top_k or self._settings.rag_top_k
        pool = min(max(k * 4, k), 20)
        candidates = self._store.search(query, pool)
        return rerank_hits(query, candidates, k)

    def format_context(self, hits: list[SearchHit]) -> str:
        if not hits:
            return ""
        parts = []
        for i, hit in enumerate(hits, 1):
            parts.append(
                f"[{i}] {hit.source} — {hit.heading}\n{hit.text[:1200]}"
            )
        return "\n\n".join(parts)

    def hits_to_chunks(self, hits: list[SearchHit]) -> list[dict]:
        return [
            {
                "id": h.chunk_id,
                "source": h.source,
                "heading": h.heading,
                "text": h.text,
                "distance": h.distance,
            }
            for h in hits
        ]
```

**한 줄 설명**

| 메서드 | 설명 |
|---|---|
| `search` | `top_k`의 4배(최대 20)만큼 벡터 후보를 넉넉히 뽑아 `rerank_hits`로 줄여 반환한다. |
| `format_context` | 히트들을 `[i] 파일 — 헤딩` + 본문 1200자로 잘라 하나의 문자열 컨텍스트로 합친다. |
| `hits_to_chunks` | `SearchHit`을 Envelope에 넣을 수 있는 평범한 딕셔너리(`id`/`source`/`heading`/`text`/`distance`)로 변환한다. |

> `format_context`는 1200자로 자르지만 `hits_to_chunks`는 **원문 전체**를 담습니다. 큐 모드에서 워커가 쓰는 건 후자(`build_prompt`가 `chunk["text"]`를 그대로 사용)이므로, 실제 프롬프트에 들어가는 본문은 **잘리지 않습니다** — `format_context` 결과(`analysis_result`)는 청크가 있을 때 `build_prompt`에서 쓰이지 않습니다 (`src/worker.py:56-68`의 `elif`).

---

## 6. `src/retrieval/chroma_store.py` — `delete_source` · `search`

### 6-1. `delete_source` (`:46-50`)

```python
    def delete_source(self, source: str) -> None:
        try:
            self._collection.delete(where={"source": source})
        except Exception:
            pass
```

**한 줄 설명:** 한 파일에서 나온 청크 전부를 `source` 메타데이터로 찾아 지워, 재인덱싱 시 사라진 헤딩의 고아 청크가 남지 않게 한다.

> `except Exception: pass`로 **모든 실패를 삼킵니다**. 삭제가 실패하면 낡은 청크가 컬렉션에 남고, 호출자(`_index_one_file`)는 성공으로 간주해 새 청크를 upsert합니다 → 같은 파일의 구/신 청크가 공존할 수 있습니다. 로그조차 남지 않습니다.

### 6-2. `search` (`:69-93`)

```python
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
```

**한 줄 설명:** 질문 문자열을 Chroma에 넘겨(임베딩은 컬렉션의 embedding function이 대신 수행) 코사인 거리 상위 `top_k`를 받아 `SearchHit` 리스트로 평탄화한다.

- `query_texts=[query]` — 쿼리가 1개라 모든 결과 배열에서 `[0]`을 꺼낸다 (`:78-81`)
- 길이가 어긋나도 터지지 않게 `i < len(...)` 가드를 매 필드에 둔다 (`:83-90`)
- `top_k <= 0`이면 Chroma를 아예 호출하지 않는다 (`:70-71`)

---

## 7. 질문 1개가 벡터 검색을 거쳐 청크가 되기까지

> **먼저 개수 주의** — 현재 `.env`는 `RAG_TOP_K=3`입니다. 코드 기본값과 `.env.example`은 5지만, 이 머신의 실제 실행은 **청크 3개**를 반환합니다. 아래는 두 경우를 함께 적습니다.
>
> | 설정 | 후보 pool | 최종 청크 |
> |---|---|---|
> | `RAG_TOP_K=3` (현재 `.env`) | `min(max(3*4, 3), 20)` = **12** | **3** |
> | `RAG_TOP_K=5` (기본값·`.env.example`) | `min(max(5*4, 5), 20)` = **20** | **5** |

### 단계별

**① 노드가 질문을 그대로 넘긴다** — `src/agents/nodes.py:132-136`

`query = state["task_input"]` — 질문 가공·확장 없음. `VaultRetriever(settings).search(query)`.

**② 후보 pool 계산** — `pipeline.py:285-286`

```python
k = top_k or self._settings.rag_top_k      # 3 (현재 .env)
pool = min(max(k * 4, k), 20)              # 12
```

재정렬로 순서가 뒤집힐 수 있으니 **최종 개수의 4배를 먼저 건져 올리는** 구조입니다.

**③ Chroma에 쿼리** — `chroma_store.py:72-76`

`self._collection.query(query_texts=[query], n_results=12, include=["documents", "metadatas", "distances"])`

**④ 질문이 768차원 벡터로 변환** — `embedder.py:21-23` → `_embed_batch`

Chroma가 컬렉션 생성 시 받은 embedding function(`OllamaEmbeddingFunction`)을 **쿼리 텍스트에도 자동 적용**합니다. 코드에서 직접 임베딩을 호출하는 곳은 없습니다.

`POST /api/embed {"model": "nomic-embed-text", "input": [질문]}` → 실패 시 `/api/embeddings`로 1건씩 폴백.

**⑤ HNSW 코사인 검색** — `chroma_store.py:40-44`

`data/chroma`에 영속된 `mala_vault` 컬렉션에서 `metadata={"hnsw:space": "cosine"}` 기준 근접 이웃 12개. 현재 이 컬렉션의 총 청크 수는 **30개**이므로 후보가 전체의 40%입니다.

**⑥ 결과 평탄화** — `chroma_store.py:77-93`

`ids`/`documents`/`metadatas`/`distances`의 `[0]`번째 리스트를 짝지어 `SearchHit(chunk_id, source, heading, text, distance)` 12개 생성.

**⑦ 키워드 재정렬로 압축** — `rerank.py:33-51`

`query_tokens`로 질문을 토큰화 → 각 히트에 헤딩 +3 / 본문 +1 / `phase N` 파일명 +8 → `(kw, -dist)` 내림차순 정렬 → **상위 3개(또는 5개)만 남김**.

**⑧ 노드가 상태에 적재** — `nodes.py:136-153`

| 상태 키 | 출처 |
|---|---|
| `analysis_result` | `format_context(hits)` — 1200자 절단 문자열 |
| `retrieved_chunks` | `hits_to_chunks(hits)` — 원문 전체 포함 딕셔너리 3~5개 |
| `context_refs` | 각 청크의 `chunk_id` 목록 |

**⑨ 프롬프트에 삽입** — `src/worker.py:56-68`

```
Use ONLY the following notes as factual context. If the answer is not in the notes, say you do not know.

[1] (파일경로) 헤딩
본문…
```

**⑩ 인용 출력** — `pipeline.py:102-115` `format_citations`

study 모드는 답변 아래 `--- sources ---`에 `파일 > 헤딩`을 중복 제거해 붙입니다.

### 한눈에

```
질문 "MALA Phase 2가 뭐야?"
  └─ VaultRetriever.search            k=3, pool=12
      └─ ChromaVaultStore.search      n_results=12
          └─ OllamaEmbeddingFunction  /api/embed → 768차원 벡터 1개
              └─ HNSW cosine          30개 중 근접 12개
          └─ SearchHit × 12
      └─ rerank_hits                  키워드 점수 → 상위 3개
  └─ hits_to_chunks                   dict × 3  →  context_refs × 3
      └─ build_prompt                 "[1] (source) heading\n본문" × 3
```

---

## 8. 임베딩 모델 벡터 차원 — **768차원**

`nomic-embed-text`를 두 경로로 실측 확인했습니다 (2026-10-09, Ollama 0.35.1).

`POST /api/show`:

```
capabilities: ['embedding']
general.architecture: nomic-bert
nomic-bert.embedding_length: 768
nomic-bert.context_length: 2048
details: parameter_size 137M, quantization_level F16, format gguf
```

프로젝트 코드(`src/retrieval/embedder.py:_embed_batch`)를 직접 호출한 결과:

```
OLLAMA_EMBED_MODEL: nomic-embed-text | RAG_TOP_K: 3
batch size: 2 | dim: [768, 768]
legacy /api/embeddings dim: 768
```

→ 신규 배치 경로와 구버전 폴백 경로 **모두 768차원**으로 일치합니다. 두 경로가 섞여도 벡터 공간이 어긋나지 않습니다.

| 항목 | 값 |
|---|---|
| 벡터 차원 | **768** |
| 임베더 컨텍스트 | 2048 토큰 |
| 파라미터 | 137M (F16) |
| 거리 함수 | 코사인 (`hnsw:space: cosine`) |
| 현재 컬렉션 | `mala_vault`, 청크 30개 |

> **주의할 조합:** `chunk_markdown`에는 청크 크기 상한이 없고(1절), 임베더 컨텍스트는 2048 토큰입니다. 긴 섹션 하나가 2048 토큰을 넘으면 **초과분이 임베딩에 반영되지 않습니다** — 에러 없이 검색 품질로만 드러납니다. 반면 `build_prompt`에는 청크 **원문 전체**가 들어가므로, "검색에는 안 쓰인 텍스트가 프롬프트에는 들어가는" 비대칭이 생깁니다.
>
> 차원을 바꾸려면(다른 임베딩 모델로 교체) **기존 컬렉션을 지우고 전체 재인덱싱**이 필요합니다. `build_index.py --force`는 매니페스트만 무시하고 컬렉션은 파일 단위로 덮어쓰므로, 차원이 다른 벡터가 섞이면 Chroma 쪽에서 거부됩니다.

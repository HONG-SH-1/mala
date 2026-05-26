# MALA — 데모·스크린샷 체크리스트

구현·데모 후 “직접 돌려봤다”를 1분 안에 보여주기 위한 스크린샷·로그 기록용입니다.

---

## 1. 데모 시나리오 (우선순위)

| # | 시나리오 | Phase | 상태 |
|---|----------|-------|------|
| 1 | Native Redis `redis-cli ping` → PONG | 1 | ✅ |
| 2 | `python -m src.scripts.e2e_once` → E2E SUCCESS | 1 | ✅ 2026-05-26 |
| 3 | `run_graph_once` → GRAPH SUCCESS + `task_status` | 2 | ✅ 2026-05-26 (`TASK-a4cdc28b`) |
| 4 | `rag_once` → RAG SUCCESS + `Phase-2-Agent.md` hits | 3 | ✅ 2026-05-26 (`TASK-3458907b`) |

---

## 2. 캡처 가이드

각 항목마다 아래를 `docs/assets/` (생성 예정)에 저장합니다.

- 터미널 출력 (명령 + 성공 로그)
- `nvidia-smi` (VRAM peak)
- Redis CLI `LLEN task_queue` 등 (해당 시)

**파일명 규칙:** `YYYY-MM-DD-<시나리오>-<번호>.png`

---

## 3. 데모 설명 (30초 예시)

> 3080 10GB에서 35B MoE는 VRAM 검토로 기각했고, 8B 단일 모델로 Redis 큐 왕복을 검증했습니다.  
> 로그: Envelope 스키마, BLPOP, peak VRAM.

---

## 4. 기록할 명령 (템플릿)

```bash
# Phase 1 — Redis
docker compose ps
docker compose exec redis redis-cli PING

# Phase 1 — 큐 테스트 (구현 후)
python -m src.scripts.enqueue_sample
python -m src.scripts.run_worker_once

# Phase 2 — LangGraph (Worker in another terminal unless --inline)
python -m src.worker
python -m src.scripts.run_graph_once --task "테스트 질문"
python -m src.scripts.show_task_status TASK-xxxxxxxx
python -m src.recommend_model

# Phase 3 — RAG
ollama pull nomic-embed-text
python -m src.scripts.build_index
python -m src.worker
python -m src.scripts.rag_once --task "vault 노트에서 MALA Phase 2 설명"
```

---

## 5. 스크린샷 (날짜별 일지)

상세: [`development-log.md`](development-log.md) (2026-05-23 ~ 05-26)

| 자산 | 용도 |
|------|------|
| [redis-pong](assets/2026-05-26-redis-pong.png) | 05-23 BIOS→Native Redis |
| [e2e-success](assets/2026-05-26-e2e-success.png) | 05-24 Phase 1 |
| [langgraph-dual-terminal](assets/2026-05-26-langgraph-dual-terminal.png) | 05-25 Phase 2 |
| [recommend-model-3080](assets/2026-05-26-recommend-model-3080.png) | 05-25 |
| [incremental-index](assets/2026-05-26-incremental-index.png) | 05-26 Phase 3 |
| [rag-success-phase2](assets/2026-05-26-rag-success-phase2.png) | 05-26 |
| [verify-incremental-100](assets/2026-05-26-verify-incremental-100.png) | 05-26 |
| [vram-peak](assets/026-05-20-vram-peak.png) | 05-20 PoC |

# MALA — 데모·스크린샷 체크리스트

구현·데모 후 “직접 돌려봤다”를 1분 안에 보여주기 위한 스크린샷·로그 기록용입니다.

---

## 1. 데모 시나리오 (우선순위)

| # | 시나리오 | Phase | 상태 |
|---|----------|-------|------|
| 1 | `docker compose up` 후 Redis ping | 1 | ⏳ |
| 2 | `task_queue` → worker → `result_queue` JSON 1건 | 1 | ⏳ |
| 3 | LangGraph 1회 실행 (CLI) | 2 | ⏳ |
| 4 | Obsidian 노트 1개 질의 → RAG 답변 | 3 | ⏳ |

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

# Phase 2 — LangGraph
python -m src.scripts.run_graph_once --task "테스트 질문"
```

---

## 5. 완료 시 README 반영

데모 1번이라도 성공하면 [`../README.md`](../README.md) **현재 진행 상태** 표를 ✅로 갱신하고, 이 문서에 스크린샷 링크를 추가합니다.

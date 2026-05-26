# MALA — 데모·스크린샷 체크리스트

구현·검증 후 “직접 돌려봤다”를 보여주는 스크린샷·로그 목록입니다.  
**일지 기준:** [`development-log.md`](development-log.md) (2026-05-23 ~ 05-26)

---

## 1. 파일명 규칙

| 규칙 | 설명 |
|------|------|
| 형식 | `YYYY-MM-DD-<시나리오>.png` |
| 날짜 | **개발 일지上的 작업일** (23~26). 캡처는 같은 날 몰아서 해도 파일명은 일지에 맞춤 |
| 위치 | [`docs/assets/`](assets/) |

> 예: 26일 저녁에 찍었어도 Phase 1 E2E 증빙은 `2026-05-24-e2e-success.png`

---

## 2. 스크린샷 목록 (날짜별)

| 일지 | 파일 | 내용 |
|------|------|------|
| 05-20 | [vram-peak](assets/2026-05-20-vram-peak.png) | Phase 0 VRAM PoC |
| 05-23 | [redis-pong](assets/2026-05-23-redis-pong.png) | BIOS→Native Redis, PONG |
| 05-24 | [e2e-success](assets/2026-05-24-e2e-success.png) | Phase 1 `e2e_once` (`TASK-a7525fce`) |
| 05-25 | [langgraph-dual-terminal](assets/2026-05-25-langgraph-dual-terminal.png) | Phase 2 Worker + graph (`TASK-a4cdc28b`) |
| 05-25 | [recommend-model-3080](assets/2026-05-25-recommend-model-3080.png) | `recommend_model` hybrid |
| 05-26 | [incremental-index](assets/2026-05-26-incremental-index.png) | `build_index` 증분 (`skip=2 ~1`) |
| 05-26 | [rag-vault-sample](assets/2026-05-26-rag-vault-sample.png) | Phase 3 RAG `vault_sample` (`TASK-3458907b`) |
| 05-26 | [verify-incremental-100](assets/2026-05-26-verify-incremental-100.png) | `verify_incremental --count 100` |
| 05-26 | [rag-obsidian-vault](assets/2026-05-26-rag-obsidian-vault.png) | **실제 볼트** `D:\Ob\Vault` (`TASK-4860f95a`) — 저장 시 링크 활성 |
| 05-26 | [hermes-preflight](assets/2026-05-26-hermes-preflight.png) | `check_paths` — `USE_HERMES: True` |
| 05-26 | [hermes-rag-success](assets/2026-05-26-hermes-rag-success.png) | Phase 4 `run_hermes_once` + context (`TASK-8f744eba`) |
| 05-26 | [ollama-models-d](assets/2026-05-26-ollama-models-d.png) | `server.log` — `OLLAMA_MODELS:D:\ollama\models` |

---

## 3. 데모 시나리오

| # | 시나리오 | Phase | task_id (참고) |
|---|----------|-------|----------------|
| 1 | `redis-cli ping` → PONG | 1 | — |
| 2 | `e2e_once` → E2E SUCCESS | 1 | `TASK-a7525fce` |
| 3 | `run_graph_once` → GRAPH SUCCESS | 2 | `TASK-a4cdc28b` |
| 4 | `rag_once` (vault_sample) | 3 | `TASK-3458907b` |
| 5 | `rag_once` (`D:\Ob\Vault`) | 3 | `TASK-4860f95a` |
| 6 | `run_hermes_once` (vault 질문) | 4 | `TASK-8f744eba` |
| 7 | `run_hermes_once --ood` | 4 | `TASK-9a2e30e5` |

---

## 4. 데모 설명 (30초)

> 3080 10GB에서 MoE는 VRAM 검토로 기각, Native Redis + LangGraph + Obsidian(Chroma) RAG를 로컬 E2E로 검증했습니다.  
> BIOS로 Docker는 막혀 Redis만 호스트에 두었고, Phase 4에서 Hermes 라우터 + vault 폴백 RAG로 볼트 환영 메시지까지 확인했습니다 (Hermes·Qwen VRAM **교대**, peak 각각 문서화).

---

## 5. 재현 명령 (요약)

```cmd
redis-cli ping
python -m src.scripts.e2e_once
python -m src.worker
python -m src.scripts.run_graph_once --task "..."
python -m src.scripts.build_index
python -m src.scripts.rag_once --task "옵시디언 노트에서 ..."
python -m src.scripts.verify_incremental --count 100
python -m src.scripts.check_paths
python -m src.worker
python -m src.scripts.run_hermes_once
python -m src.scripts.run_hermes_once --ood
```

상세: [`../README.md`](../README.md) · [`development-log.md`](development-log.md) · [ADR-003](decisions/003-phase4-hermes-router.md)

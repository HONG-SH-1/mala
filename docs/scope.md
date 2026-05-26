# MALA — 프로젝트 범위 (Scope)

이 문서는 **무엇을 해결하려는지**, **무엇까지가 1차 목표인지**, **의도적으로 하지 않는 것**을 명확히 합니다.  
**개요:** [`../README.md`](../README.md) · 초기 기획: [`../archive/`](../archive/)

---

## 1. 문제 정의

| 문제 | 설명 |
|------|------|
| 클라우드 API 의존 | 지식·대화가 외부로 나가는 것을 줄이고 싶음 (**Data Sovereignty**) |
| GPU 한계 | RTX 3080 10GB — 대형 모델을 “이름만 보고” 올리면 OOM |
| CPU·RAM | 5600X + **32 GB RAM** — 임베딩·인덱싱·Docker 동시 시 병목 관리 — [`hardware-environment.md`](hardware-environment.md) |
| 단일 LLM 한계 | 분석·코딩·라우팅을 한 프롬프트에 몰면 품질·토큰 비용 모두 불리 |
| 운영 단순성 | 멀티 에이전트가 직접 HTTP로 엮이면 한 에이전트 장애가 전체 마비 |

---

## 2. 목표 (Must — 1차 완료 기준)

**“이런 생각을 했다”**를 증명할 수 있는 최소 구현 단위입니다.

- [x] **Phase 0:** 3080에서 후보 모델 VRAM·속도 표 작성 ([`model-comparison.md`](model-comparison.md)에 실측 반영)
- [x] **Phase 1:** Redis + JSON Envelope `task_queue` / `result_queue` 왕복 1회 — 2026-05-26 `e2e_once` 성공 ([ADR-002](decisions/002-native-redis-phase1.md))
- [x] **Phase 2:** LangGraph로 Router → 처리 → (실패 시) 1회 재시도 루프 — 2026-05-26 `run_graph_once` (`TASK-a4cdc28b`)
- [x] **Phase 2:** `task_status:{task_id}` Redis Hash로 진행 상태 조회
- [x] **Phase 2:** `recommend_model.py` — GPU/RAM 진단 후 모델·오프로딩 추천 ([`archive/MALA_V2-vision.md`](../archive/MALA_V2-vision.md)) — `nvidia-smi` 폴백 추가
- [x] **Phase 3:** Obsidian 마크다운 소수 파일, 헤딩 단위 청킹 + SHA-256 증분 인덱싱 — 2026-05-26 `build_index` (12 chunks)
- [x] **Phase 3:** 벡터 검색 1종(Chroma + Ollama embed)으로 질의 → 답변 1회 E2E — 2026-05-26 `rag_once` (`TASK-3458907b` / Ob Vault `TASK-4860f95a`)
- [x] **Phase 4 (PoC):** Hermes 라우터 + `search_vault` / 폴백 RAG + OOD 구분 — 2026-05-26 `run_hermes_once` (`TASK-8f744eba`, `--ood` `TASK-9a2e30e5`) — [ADR-003](decisions/003-phase4-hermes-router.md)

---

## 3. 비목표 (Won’t — 초기 버전)

다음은 **비전에는 포함**되나, 1차 레포 완료 조건에 **넣지 않습니다**.

| 항목 | 이유 |
|------|------|
| Qwen 35B / Gemma 26B MoE on 10GB | VRAM PoC상 불가 — [`../troubleshooting/2026-05-20-moe-vram.md`](../troubleshooting/2026-05-20-moe-vram.md) |
| DVC 전체 파이프라인 + GraphRAG(FalkorDB/Cypher) | 단독 프로젝트 규모 — Phase 3 이후 또는 별도 이슈 |
| CrewAI + LangGraph 동시 운영 | 오케스트레이션 이중화 — LangGraph만 1차 |
| vLLM + GGUF 혼용 | 도구 경로 불일치 — ADR-001 참고 |
| 무인 `git commit` / Claude Code 자동 배포 | 검증·보안 — 수동 승인 |
| Vertex AI 30문항 PoC | Phase 4 옵션 |

---

## 4. 성공 기준

문서·아키텍처는 [`README.md`](../README.md) · [`architecture.md`](architecture.md) 기준.  
구현 목표는 **Phase별 E2E 한 번씩** 동작 확인입니다.

1. **숫자:** 모델 비교 표에 본인 환경 실측 1행 이상
2. **과정:** 트러블슈팅 2건 이상 (가설·시도·결과·교훈)
3. **구조:** [`architecture.md`](architecture.md) 다이어그램과 실제 폴더/compose가 대략 일치
4. **데모:** 1분 이내 — Redis 큐 메시지 왕복 또는 LangGraph 1회 실행 ([`demo.md`](demo.md))

---

## 5. 4축 설계 (요약)

```
지식(Data)     → Obsidian MD, (후) 증분 인덱스
두뇌(Model)    → 로컬 SLLM, 4bit·단일 모델 우선
행동(Agent)    → LangGraph + Redis JSON 큐
인프라(Infra)  → Docker Compose, .env 분리
```

상세 다이어그램: [`architecture.md`](architecture.md)

---

## 6. 로드맵

**프로젝트:** 2026-05-19 착수 · 2026-05-20 설계(문서·아키텍처) 1차 완료 · 이후 Phase별 구현·검증 진행. 요약은 [`README.md`](../README.md).

| Phase | 기간(가이드) | 산출물 |
|-------|--------------|--------|
| 0 PoC | 1~2일 | `model-comparison.md` 실측, 트러블슈팅 #1 |
| 1 Infra | 3~5일 | Native Redis 또는 `docker-compose.yml`, 큐 E2E (`src/scripts/e2e_once.py`) |
| 2 Agent | 5~7일 | `src/` LangGraph, 스키마 검증, **`recommend_model.py`** (Resource-Aware) |
| 3 Knowledge | 5~7일 | 청킹·벡터 검색 최소 |
| 4 Router | 선택 → **PoC ✅** | Hermes `hermes3:8b` + vault 폴백 RAG — Vertex/UI는 [`../archive/MALA_V2-vision.md`](../archive/MALA_V2-vision.md) |

**상태 범례:** 📝 문서만 · ⏳ 진행 예정 · ✅ 완료 · 🔲 보류

---

## 7. 리스크 & 대응 (요약)

| 리스크 | 대응 |
|--------|------|
| MoE VRAM 오해 | Phase 0 표 + 트러블슈팅 문서화 |
| 모델 스와핑 지연 | 1차는 단일 8B~14B dense |
| 파이프라인 과다 | GraphRAG·DVC는 Won’t |
| 설계 과정 불명확 | `archive/` + `design-process.md`로 이력 공개 |

---

## 8. 관련 문서

- [`architecture.md`](architecture.md)
- [`model-comparison.md`](model-comparison.md)
- [`decisions/001-inference-engine.md`](decisions/001-inference-engine.md)
- [`../troubleshooting/`](../troubleshooting/)

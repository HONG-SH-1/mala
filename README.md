# MALA (Multi-Agent Local AI)

로컬 GPU(RTX 3080 10GB, RAM 32GB) 제약 안에서 **Obsidian 지식 · Local LLM · RAG · Multi-Agent 오케스트레이션**을 구축하는 **개인 프로젝트**입니다.

| | |
|---|---|
| **기간** | 2026-05-19 ~ **진행 중** |
| **단계** | 설계 완료 (2026-05-20) → Phase 0 문서화 ✅ / Phase 1~3 구현 ⏳ |
| **문서·아키텍처** | ✅ [`docs/`](docs/) · [`troubleshooting/`](troubleshooting/) |
| **구현** | ⏳ Phase 0~3 (인프라 → Agent → RAG) |

**지식(Data) · 추론(Model) · 에이전트(Agent) · 인프라(Infra)** 네 축 — VRAM 검토 후 Redis + LangGraph + RAG로 Local LLM 서비스를 설계했습니다.

---

## 읽는 순서

1. [`docs/architecture.md`](docs/architecture.md) — 구조·다이어그램
2. [`troubleshooting/2026-05-20-moe-vram.md`](troubleshooting/2026-05-20-moe-vram.md) — MoE VRAM 검토
3. [`docs/design-process.md`](docs/design-process.md) — AI 보조·검증 과정
4. [`docs/scope.md`](docs/scope.md) — 범위·Must / Won't

---

## 현재 진행 상태

**2026-05-19** 프로젝트 착수 · **2026-05-20** 아키텍처·범위 1차 확정(설계 완료) · **현재** Phase 0 실측 및 Phase 1 구현 준비 중.

| Phase | 내용 | 상태 |
|-------|------|------|
| 0 | VRAM·모델 적합성 PoC | 📝 문서화 완료, 로컬 측정 예정 |
| 1 | Docker Compose + Redis + 추론 엔진 | ⏳ 예정 |
| 2 | LangGraph 최소 워크플로 + JSON A2A | ⏳ 예정 |
| 3 | Obsidian 청킹 + 벡터 검색(축소) | ⏳ 예정 |
| 4 | 듀얼 모델 / UI / 클라우드 PoC | 🔲 범위 외(초기) |

```
Phase 0  VRAM·RAM 실측 → Phase 1  Docker·Redis·큐 E2E
    → Phase 2  LangGraph → Phase 3  RAG E2E → Phase 4 (선택)
```

---

## 기술 스택 (1차)

Python · Docker Compose · Redis · LangGraph · Ollama 또는 vLLM · Chroma · Obsidian

| 서브시스템 | 요약 |
|------------|------|
| **추론** | MoE 35B 기각 → Qwen3-8B Q4 · Ollama 우선 ([ADR-001](docs/decisions/001-inference-engine.md)) |
| **RAG** | Obsidian → 헤딩 청킹 → SHA-256 증분 → Chroma |
| **Agent** | LangGraph + Redis 큐 + JSON Envelope |
| **인프라** | compose · `.env` · OOM 시 큐 유지 |

**1차 제외:** GraphRAG 전체, CrewAI, 35B MoE on 10GB — [`docs/scope.md`](docs/scope.md)

---

## 문서

| 문서 | 용도 |
|------|------|
| [`docs/architecture.md`](docs/architecture.md) | 아키텍처·시퀀스·LangGraph |
| [`docs/scope.md`](docs/scope.md) | 범위·로드맵·성공 기준 |
| [`docs/hardware-environment.md`](docs/hardware-environment.md) | CPU·GPU·RAM |
| [`docs/model-comparison.md`](docs/model-comparison.md) | 모델·VRAM 표 |
| [`docs/design-process.md`](docs/design-process.md) | AI 리뷰 채택/기각 |
| [`docs/demo.md`](docs/demo.md) | 데모·스크린샷 |
| [`docs/decisions/`](docs/decisions/) | ADR |
| [`troubleshooting/`](troubleshooting/) | 트러블슈팅 |
| [`archive/`](archive/) | 초안·리뷰 로그 |

---

## 하드웨어

| 구성 | 스펙 |
|------|------|
| **CPU** | AMD Ryzen 5 5600X (6C/12T) |
| **GPU** | NVIDIA RTX 3080 (10GB VRAM) |
| **RAM** | 32 GB (31.9 GB usable) |
| **OS** | Windows 10/11, Docker Desktop + WSL2 권장 |

상세: [`docs/hardware-environment.md`](docs/hardware-environment.md)

---

## 빠른 시작 (Phase 1 이후)

```bash
cp .env.example .env
docker compose up -d
```

> `docker-compose.yml`·`src/`는 Phase 1~2에서 추가 예정.

---

## 레포 구조 (목표)

```
MALA/
├── README.md
├── docs/
├── troubleshooting/
├── archive/
├── docker-compose.yml
├── .env.example
└── src/
```

---

## 타임라인

| 일자 | 내용 |
|------|------|
| 2026-05-19 | 프로젝트 착수 · 요구사항·아키텍처 초안 |
| 2026-05-20 | MoE VRAM 검토·기각 → 8B dense · ADR-001 · 범위 확정 (**설계 1차 완료**) |
| 진행 중 | Phase 0 VRAM/RAM 실측 · Phase 1 Docker/Redis 구현 예정 |

초기 마스터플랜: [`archive/`](archive/)

---

## 핵심 포인트

1. **Resource efficiency** — VRAM 측정 후 모델 결정 ([`docs/model-comparison.md`](docs/model-comparison.md))
2. **Reliability** — Redis 큐, 워커 재시작 시 작업 유지
3. **Reproducibility** — Git + 인덱스 해시 증분 갱신

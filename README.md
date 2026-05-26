# MALA (Multi-Agent Local AI)

로컬 GPU(RTX 3080 10GB, RAM 32GB) 제약 안에서 **Obsidian 지식 · Local LLM · RAG · Multi-Agent 오케스트레이션**을 구축하는 **개인 프로젝트**입니다.

| | |
|---|---|
| **기간** | 2026-05-19 ~ **2026-05-26 (V1)** |
| **단계** | 설계(05-20) ✅ · 구현·E2E(05-23~26) ✅ — [`docs/development-log.md`](docs/development-log.md) |
| **문서·아키텍처** | ✅ [`docs/`](docs/) · [`troubleshooting/`](troubleshooting/) |
| **구현** | ✅ Phase 0~4 PoC 로컬 검증 |

**지식(Data) · 추론(Model) · 에이전트(Agent) · 인프라(Infra)** 네 축 — VRAM 검토 후 Redis + LangGraph + RAG로 Local LLM 서비스를 설계했습니다.

> **구현 기준:** [`docs/scope.md`](docs/scope.md) · [`docs/architecture.md`](docs/architecture.md)  
> **확장 설계안(V2):** [`archive/MALA_V2-vision.md`](archive/MALA_V2-vision.md) (하이브리드·`recommend_model.py` 등 — E2E 이후)

---

## 읽는 순서

1. [`docs/architecture.md`](docs/architecture.md) — 구조·다이어그램
2. [`troubleshooting/2026-05-20-moe-vram.md`](troubleshooting/2026-05-20-moe-vram.md) — MoE VRAM 검토
3. [`docs/design-process.md`](docs/design-process.md) — AI 보조·검증 과정
4. [`docs/scope.md`](docs/scope.md) — 범위·Must / Won't

---

## 현재 진행 상태

**2026-05-19** 착수 · **05-20** 설계 · **05-23~26** Phase 1~3 구현·검증 ([`development-log.md`](docs/development-log.md)).

| Phase | 내용 | 상태 |
|-------|------|------|
| 0 | VRAM·모델 적합성 PoC | ✅ 실측 (`qwen3:8b` peak 7559 MiB) |
| 1 | Redis + JSON Envelope 큐 E2E (Native Redis) | ✅ 2026-05-26 E2E (`TASK-a7525fce`) |
| 2 | LangGraph 최소 워크플로 + `task_status` + `recommend_model` | ✅ 2026-05-26 (`TASK-a4cdc28b`) |
| 3 | Obsidian 청킹 + Chroma RAG E2E | ✅ 2026-05-26 (`TASK-3458907b`) |
| 4 | Hermes 라우터 + vault RAG (폴백) | ✅ 2026-05-26 (`TASK-8f744eba`) |

```
Phase 0  VRAM·RAM 실측 → Phase 1  Docker·Redis·큐 E2E
    → Phase 2  LangGraph → Phase 3  RAG E2E → Phase 4 (선택)
```

---

## 기술 스택 (1차)

Python · **Native Redis** (Phase 1) · Docker Compose (optional) · LangGraph · Ollama · Chroma · Obsidian

| 서브시스템 | 요약 |
|------------|------|
| **추론** | MoE 35B 기각 → Qwen3-8B Q4 · Ollama 우선 ([ADR-001](docs/decisions/001-inference-engine.md)) |
| **RAG** | Obsidian → 헤딩 청킹 → SHA-256 증분 → Chroma |
| **Agent** | LangGraph + Redis 큐 + JSON Envelope |
| **인프라** | Native Redis · `.env` · (optional) compose — [ADR-002](docs/decisions/002-native-redis-phase1.md) |

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
| [`docs/opinion-infra-and-career.md`](docs/opinion-infra-and-career.md) | 인프라·실무(WAS)·커리어 의견 공유 |
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
| **OS** | Windows 10/11 · Docker Desktop optional (BIOS SVM 필요) |

상세: [`docs/hardware-environment.md`](docs/hardware-environment.md)

---

## 빠른 시작 (Phase 1 — Native Redis)

### 1. Redis (Windows)

[Redis for Windows (tporadowski)](https://github.com/tporadowski/redis/releases) 또는 Memurai Developer 등 **Redis 5+** 호환 서버를 설치하고 기동합니다.

```powershell
redis-cli ping
# PONG
```

### 2. Python

```powershell
cd D:\PersonProject\MALA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

### 3. Ollama

```powershell
ollama pull qwen3:8b
# Ollama 앱 실행 또는 ollama serve
```

### 4. 검증

```powershell
python -m src.scripts.check_redis
python -m src.scripts.e2e_once
```

성공 시 `--- E2E SUCCESS ---` 와 모델 응답이 출력됩니다.

### 5. Worker (상시)

```powershell
python -m src.worker
```

다른 터미널에서 `e2e_once`, `run_graph_once`(큐 모드), 또는 Orchestrator가 `task_queue`에 push.

---

## 빠른 시작 (Phase 2 — LangGraph)

`pip install -r requirements.txt` 로 `langgraph`, `psutil` 을 추가 설치합니다.

### 1. 모델·VRAM 추천 (선택)

```powershell
python -m src.recommend_model
```

### 2. 그래프 1회 실행

**큐 모드 (Phase 1과 동일 — Worker 필요):**

```powershell
# 터미널 A
python -m src.worker

# 터미널 B
python -m src.scripts.run_graph_once --task "MALA Phase 2를 한 문장으로 설명해줘"
```

**인라인 모드 (Worker 없이 Ollama 직접 호출):**

```powershell
python -m src.scripts.run_graph_once --inline --task "hello"
```

성공 시 `--- GRAPH SUCCESS ---` 와 Redis `task_status:{task_id}` 필드가 출력됩니다.

```powershell
python -m src.scripts.show_task_status TASK-xxxxxxxx
```

검증 실패 시 `validate` 노드가 최대 `GRAPH_MAX_RETRIES` 회까지 `route`로 재시도합니다 (`.env`).

---

## 빠른 시작 (Phase 3 — RAG)

### 1. 임베딩 모델

```powershell
ollama pull nomic-embed-text
```

### 2. `.env`

```powershell
copy .env.example .env
# OBSIDIAN_VAULT_PATH=vault_sample  (기본 샘플 볼트)
# 실제 Obsidian 볼트 경로로 바꿔도 됨
```

### 3. 인덱스 빌드

```powershell
python -m src.scripts.build_index
```

두 번째 실행부터는 **SHA-256 manifest** 로 변경된 `.md` 만 재인덱싱합니다.  
읽기 실패 파일은 `data/index_failures.jsonl` (DLQ)에 기록하고 나머지는 계속 처리합니다.

```powershell
python -m src.scripts.verify_incremental --count 10
# 전체 카오스: --count 100
```

### 4. RAG E2E

```powershell
# 터미널 A
python -m src.worker

# 터미널 B
python -m src.scripts.rag_once --task "vault 노트에서 MALA Phase 2가 무엇인지 설명해줘"
```

성공 시 `--- RAG SUCCESS ---` 와 `retrieve:N_hits` 히스토리가 보입니다.  
질문에 `vault` / `노트` / `옵시디언` / `검색` 등이 있어야 `route → retrieve` 경로로 갑니다.

---

## 빠른 시작 (Phase 4 — Hermes router, PoC)

### 0. VRAM 실측 (먼저)

```powershell
ollama pull hermes3:8b
python -m src.scripts.measure_router_vram
```

Hermes 단독 peak **7418 MiB** (2026-05-26) — [`docs/model-comparison.md`](docs/model-comparison.md). 재측정 시 Qwen unload 후 `ollama run hermes3:8b` + `measure_router_vram`.

### 1. `.env`

```powershell
USE_HERMES_ROUTER=1
OLLAMA_ROUTER_MODEL=hermes3:8b
MAX_TOOL_STEPS=5
```

답변 모델은 그대로 `OLLAMA_MODEL=qwen3:8b` (동시 GPU 적재 금지 — [ADR-003](docs/decisions/003-phase4-hermes-router.md)).  
Hermes가 tool을 안 부르면 **vault 키워드 폴백**으로 Chroma 검색 (`hermes:fallback_search`).

### 2. 실행

```powershell
python -m src.worker
python -m src.scripts.run_hermes_once --task "옵시디언 노트에서 환영 메시지 설명해줘"
python -m src.scripts.run_hermes_once --ood
```

`--ood` = vault 검색 없이 답해야 함 (제미나이 카오스 시나리오).

---

### Docker (optional — BIOS SVM 활성화 후)

```powershell
docker compose up -d
python -m src.scripts.check_redis
```

→ [ADR-002](docs/decisions/002-native-redis-phase1.md)

---

## 레포 구조 (목표)

```
MALA/
├── README.md
├── requirements.txt
├── docker-compose.yml    # optional (Redis only)
├── src/
│   ├── broker/
│   ├── schemas/
│   ├── agents/           # LangGraph (Phase 2)
│   ├── retrieval/        # 청킹, Chroma (Phase 3)
│   ├── scripts/          # e2e_once, run_graph_once, rag_once, …
│   ├── vault_sample/     # 데모용 MD
│   ├── recommend_model.py
│   ├── config.py
│   └── worker.py
├── tests/
├── docs/
├── troubleshooting/
└── archive/
```

---

## 타임라인

| 일자 | 내용 |
|------|------|
| 2026-05-19 | 프로젝트 착수 · 요구사항·아키텍처 초안 |
| 2026-05-20 | MoE VRAM 검토·기각 → 8B dense · ADR-001 · 범위 확정 (**설계 1차 완료**) |
| 2026-05-23 | BIOS/Docker 막힘 → Native Redis **결정** (ADR-002) |
| 2026-05-24 | Phase 1 큐 E2E (`TASK-a7525fce`) |
| 2026-05-25 | Phase 2 LangGraph (`TASK-a4cdc28b`) |
| 2026-05-26 | Phase 3 RAG·증분 검증 (`TASK-3458907b`) — **일지:** [`development-log.md`](docs/development-log.md) |

초기 마스터플랜: [`archive/`](archive/)

---

## 핵심 포인트

1. **Resource efficiency** — VRAM 측정 후 모델 결정 ([`docs/model-comparison.md`](docs/model-comparison.md))
2. **Reliability** — Redis 큐, 워커 재시작 시 작업 유지
3. **Reproducibility** — Git + 인덱스 해시 증분 갱신

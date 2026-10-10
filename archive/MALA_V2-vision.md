<!--
  [설계 검토 기록 — Review #3 브리프]
  용도: Claude · Gemini 에게 붙여 넣어 의견 교환할 초안
  도구: Cursor 정리 (2026-05-31) · V1 완료(05-27) · SQLD 시험 종료(05-31) 이후
  구현 기준(현재): docs/scope.md, docs/architecture.md, ADR — 본 문서는 vision until accepted
  이전 리뷰: review-gemini-2026-05.md, review-claude-2026-05.md
-->

# MALA V1.5 / V2 — 확장 설계안 (AI 리뷰용)

> **이 파일을 Claude·Gemini에 통째로 전달**하고, §8 질문에 답을 받은 뒤 `docs/`·ADR에만 반영한다.

---

## 0. 상황 (2026-05-31)

| 항목 | 상태 |
|------|------|
| **V1** | Phase 0~4 PoC E2E 완료 — Redis · LangGraph · Obsidian/Chroma RAG · Hermes 라우터(+폴백) |
| **SQLD** | **시험 종료** — MALA/SQLD·자동 노트 정리 **중단**. Obsidian은 전 포폴 공부용으로 전환 |
| **다음 목표** | ① **포폴용 MALA 고도화** ② **Obsidian에 전 포폴 내용** ③ **MALA로 로컬 복습(RAG)** |
| **하드웨어** | RTX 3080 10GB · RAM 32GB · Windows · Ollama `D:\ollama\models` |

**한 줄:** 챗봇(RAG+답변)은 **1층으로 완료**. 그 위에 **플러그형 멀티에이전트 + (선택) API·MCP·멀티모달**을 얹고 싶다.

---

## 1. 설계 방향 (사용자 의도)

### 1.1 좋아하는 시스템 패턴

- **에이전트 협업** — 역할 분리(리서치·작성·검증 등). OpenHands / Cursor Agent / “Humane류”처럼 **모듈을 껐다 뺄 수 있는** 구조
- **LLM Provider** — API 있으면 API, 없으면 **로컬 Ollama**, 설정으로 on/off
- **도구** — RAG·터미널·MCP 등을 **레지스트리**에 등록
- **인프라 철학 (V1 유지)** — 에이전트끼리 **직접 HTTP 없이** Redis JSON Envelope 큐

### 1.2 시대 흐름 (습득·연결만, 전부 코어 X)

- **멀티모달:** Google **Gemini Omni**(앱/소비자 영상·편집) · 개발자 API는 **Veo 3.1**(`text/image/video-to-video` 등) — 로컬 3080에서 영상 생성 X, **API 어댑터 슬롯**만
- **AX / AI 네이티브 JD:** RAG 파이프라인, 에이전트 오케스트레이션, Tool/MCP, 로컬 vs API, 컨텍스트·토큰, 거버넌스(Human-in-the-loop), (인지) 멀티모달 API

---

## 2. 플러그형 아키텍처 (V1.5 뼈대)

V1 코드 전부 갈아엎지 않고, 아래 **5개 인터페이스**를 먼저 고정한다.

```
┌─────────────────────────────────────────┐
│  Orchestrator (LangGraph / Supervisor)   │
└───────────┬─────────────────────────────┘
            │
    ┌───────┼───────┬───────────┬──────────┐
    ▼       ▼       ▼           ▼          ▼
 LLMProvider ToolRegistry AgentRegistry Transport ModalProvider
             (MCP,RAG,…)   (역할 YAML)  (Redis)  (text/video…)
```

| 모듈 | 책임 | V1 | V1.5 목표 |
|------|------|-----|-----------|
| **Transport** | `task_queue` / `result_queue` | ✅ Redis | 유지 |
| **LLMProvider** | `ollama` / `openai-compatible` / `off` | △ Ollama만 | `.env`로 플러그 |
| **ToolRegistry** | `search_vault`, (후) shell, MCP | △ RAG | 등록·권한 |
| **AgentRegistry** | Researcher / Writer / Critic … | △ Worker 1종 | `AgentSpec` |
| **ModalProvider** | Gemini/Veo 등 | ❌ | 스텁 → 옵션 |

**VRAM 정책 (ADR-003 유지):** 10GB에서 **서로 다른 8B 모델 동시 상주 금지**. 협업은 **한 LLM + 역할은 그래프/프롬프트** 또는 **순차 스왑**.

---

## 3. 멀티에이전트 협업 — 단계안

| 단계 | 내용 | 포폴 스토리 |
|------|------|-------------|
| **A** | `AgentSpec` (이름, 역할, tools, provider_id) | 설정으로 에이전트 등록 |
| **B** | Supervisor — 작업 분해 → Envelope `receiver`별 push | A2A는 큐만 |
| **C** | 2~3역할: **Researcher**(Chroma), **Writer**(생성), **Critic**(검증) | LangChain 1파일과 차별 |
| **D** | **Human gate** — 위험 tool 전 CLI `y/n` | 거버넌스 |
| **E** | **MCP 어댑터** = ToolRegistry 항목 | 2025~ JD |
| **F** | LiteLLM류 **단일 LLM 인터페이스** | API 키 있을 때만 |

**OpenHands 등 외부 SDK:** 전면 이전 X. **Redis + LangGraph + Envelope**는 MALA 고유, Provider/Tool만 호환 패턴 차용.

---

## 4. Obsidian · 로컬 공부 (V1.5 필수에 가깝음)

| 기능 | 설명 |
|------|------|
| **폴더 include** | `.env` `OBSIDIAN_INCLUDE=06_Portfolio` — SQLD·빈 MOC 제외 |
| **출처 인용** | 답변에 `파일 > ## 헤딩` |
| **`study` CLI** | 키워드 없이도 **항상 vault RAG** (전 포폴 복습) |
| **루틴** | 노트 작성 → `build_index` → `worker` → 질문 |

데이터는 사용자가 **Obsidian에 직접** 작성 (`#` `##` `###`). PDF 자동 추출·SQLD 파이프는 **하지 않음**.

---

## 5. AX / AI 네이티브 — JD 역량 ↔ MALA 매핑

| JD에서 자주 보는 것 | 사용자 습득 | MALA 반영 우선순위 |
|---------------------|-------------|-------------------|
| RAG·지식 파이프라인 | Obsidian 정리 | ✅ → include·출처·study |
| 에이전트·오케스트레이션 | LangGraph | Supervisor·다역할 (§3) |
| Tool use / **MCP** | MCP 1개 체험 | ToolRegistry (E) |
| 로컬 vs API | VRAM·비용·프라이버시 | LLMProvider (F) |
| 컨텍스트·토큰 | 짧은 노트·요약 | Condenser 노드 (후순위) |
| 멀티모달(영상) | Veo/Omni 문서 | ModalProvider 스텁 |
| 평가·환각 | 10문항 고정 | `eval/` (후순위) |
| 관측·운영 | task_id·DLQ | 구조화 로그 강화 |
| 거버넌스 | 키·PII·승인 | Human gate (D) |
| Cursor hooks/rules | 개발 환경 | **레포 밖** (MALA와 분리) |

---

## 6. 구현 우선순위 (Review #3 합의 — 2026-05-31)

> **원칙:** 수직 E2E 먼저 → 추상화는 두 번째 구현 생길 때 추출 (Claude). **Dogfood** = study RAG 매일 쓰기.

| 순서 | 작업 | 목적 |
|------|------|------|
| **1** | **study CLI** + vault `include` + **출처** + retrieval 가시화 + “근거 없으면 없다” | 전 포폴 로컬 공부 · dogfood |
| **1b** | (같은 묶음) Obsidian **태그 필터** on `search_vault` (Gemini) | `#SQL` 등 좁히기 |
| **2** | `ToolRegistry` — `search_vault` + **MCP 데모 1개** | 플러그 증명 |
| **3** | LangGraph **reflection** — Researcher → Writer → **Critic** (단일 8B, 프롬프트만 분리) | 멀티에이전트 포폴 |
| **4** | `LLMProvider` **얇게** (Ollama + off; API는 키 있을 때만) | 껐다 켜기 |
| **5** | Human gate + **timeout/TTL** (무한 대기 방지) + 보안 checklist | 거버넌스 |
| **6** | **Condenser** 노드 (히스토리 요약) — Supervisor 앞 | 컨텍스트 OOM 방지 |
| **7** | demo/README · 포폴 한 줄 (Claude版 권장) | 지원 |

**하지 않음 (합의):** OpenHands SDK 전면 · ModalProvider 스텁(README 한 줄만) · 3모델 동시 상주 · JD 10개 얕게.

**한 번에 전부 X.** 1→2→3 깊게, 나머지 순차.

---

## 7. V1 유지 · Won't (리뷰어가 범위 넓히지 말 것)

| 유지 | Won't (당분간) |
|------|----------------|
| Redis A2A · JSON Envelope | Spring WAS 전환 |
| LangGraph 관제 | CrewAI + LangGraph 이중 |
| 8B 단일 Ollama E2E | 35B MoE on 10GB |
| ADR·트러블슈팅 투명성 | GraphRAG 전면 |
| Data Sovereignty 기본 | 무인 git push |
| | SQLD PDF 파이프 재개 |
| | 로컬 영상 생성 모델 |

---

## 8. Review #3 답변 (2026-05-31) — 원문·요약

전문: [`review-gemini-2026-05-31.md`](review-gemini-2026-05-31.md) · [`review-claude-2026-05-31.md`](review-claude-2026-05-31.md)

### 8.1 합의 (둘 다)

| 주제 | 합의 |
|------|------|
| OpenHands SDK | **전면 도입 기각** — Redis·LangGraph·Envelope **자체 구현** 유지 |
| VRAM | **단일 8B 상주** + LangGraph 노드별 **역할 프롬프트** (모델 3개 X) |
| 핵심 가치 | **Critic / reflection 루프** + **study RAG dogfood** |
| MCP | **데모 1개** + 보안(.env, 마스킹, allowlist, human gate) |
| 멀티모달 | **코어에 넣지 않음** (로컬 영상 X) |
| SQLD | 범위 밖 (본 브리프와 무관) |

### 8.2 갈림 (MALA 채택안)

| 주제 | Gemini | Claude | **채택** |
|------|--------|--------|----------|
| 5모듈 지금 | 전부 OK | 3개만 인터페이스, AgentSpec은 dict | **Claude** — 구현 2개 생기면 추출 |
| ModalProvider | 스텁 OK | 스텁도 X, README 1줄 | **Claude** |
| 우선순위 | 1→3→4→5 | **3→2→4→1→5** | **Claude 순서** (§6 반영) |
| Obsidian 추가 | 태그 필터 | retrieval 가시화 + 근거 가드 | **둘 다** |

### 8.3 포폴 한 줄 (면접용)

**권장 (Claude):**

> 외부 API 없이 단일 PC(RTX 3080 10GB)에서 도는 플러그형 로컬 멀티에이전트 RAG — Redis 큐 A2A 위에 Researcher·Writer·Critic 역할을 단일 모델 reflection 루프로 구성하고, VRAM 실측으로 모델 동시 상주 한계를 설계 제약(ADR)으로 못박았다.

**대안 (Gemini — 엔터프라이즈 톤):**

> 비동기 Redis 큐와 LangGraph 플러그형 오케스트레이션으로 결합도를 낮추고 데이터 주권을 확보한 하이브리드 멀티에이전트 시스템 (10GB VRAM 제약 설계).

### 8.4 Plan B (리스크)

| 리스크 | Plan B |
|--------|--------|
| 추상화만 있고 E2E 없음 | **수직 1줄기 먼저** (RAG+출처+reflection) → 그다음 인터페이스 추출 |
| 히스토리·컨텍스트 폭발 | **Condenser** 노드 (요약) |
| Human gate 무한 대기 | **TTL / timeout** → 자동 취소 |
| JD 10개 얕음 | **깊게 2개만**: reflection + VRAM/ADR |

---

## 9. 부록 — V1 이후 기술 메모 (기존 V2 vision)

### 9.1 메모리 예산 (RTX 3080 10GB · RAM 32GB)

```
VRAM ≈ 10GB − OS(~1GB) − KV(2~4GB) → 가중치 ~5~7GB
풀-VRAM: ~7B Q4. 하이브리드(n-gpu-layers): 더 큰 모델 가능, 속도↓
```

MoE 35B 풀-VRAM 기각: [`troubleshooting/2026-05-20-moe-vram.md`](../troubleshooting/2026-05-20-moe-vram.md)

### 9.2 V1 오케스트레이션 (유지)

```
사용자 → LangGraph → Redis queues → Router → Retrieve(Chroma) → Worker(Ollama) → validate
```

### 9.3 모델 확장 (참고, 실측 전 포폴 숫자 사용 금지)

| 단계 | 구성 |
|------|------|
| V1 | Qwen3-8B Q4 · Ollama |
| Conservative | Router 1.7B + 14B 분석 + Coder 7B (교대) |
| Ambitious | 26B~35B MoE 하이브리드 (느림) |

### 9.4 토큰 이코노미

Router-first · 로컬 Ollama · SHA 증분 인덱스 · (옵션) Vertex 30문항 대조.

---

## 10. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-05 (초안) | V2 vision — 하이브리드·모델 표 |
| **2026-05-31** | Review #3 브리프 + **Gemini/Claude 답변 반영** (§6·§8) |

---

## 11. 관련 링크

- [`docs/design-process.md`](../docs/design-process.md) — AI 협업·채택/기각
- [`docs/scope.md`](../docs/scope.md) — 현재 구현 기준
- [`review-gemini-2026-05.md`](review-gemini-2026-05.md) · [`review-claude-2026-05.md`](review-claude-2026-05.md) — 1~2차
- [`review-gemini-2026-05-31.md`](review-gemini-2026-05-31.md) · [`review-claude-2026-05-31.md`](review-claude-2026-05-31.md) — **3차**
- [`docs/opinion-infra-and-career.md`](../docs/opinion-infra-and-career.md) — 신입 vs 차별·WAS 대응

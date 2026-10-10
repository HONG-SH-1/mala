# MALA — 설계 과정 (AI 보조 · 검증 · 문서화)

MALA 설계에서 **AI를 어떻게 썼고, 무엇을 직접 검증했는지** 남긴 문서입니다.

---

## 1. 한 줄 요약

> AI로 **초안·리뷰·대안**을 빠르게 받고, **VRAM·범위·도구 선택**은 직접 검증해 **설계서·ADR·트러블슈팅**으로 고정했다.

---

## 2. 역할 분담

| 단계 | AI 역할 | 사람(본인) 역할 | 레포 산출물 |
|------|---------|-----------------|-------------|
| 브레인스토밍 | Session 1~5 구조 초안 | 요구사항·GPU 제약 입력 | [`archive/draft-masterplan.md`](../archive/draft-masterplan.md) |
| 1차 리뷰 | 강점·리스크·Plan B 제안 | Plan B 채택, MoE 칭찬은 **기각** | [`archive/review-gemini-2026-05.md`](../archive/review-gemini-2026-05.md) |
| 2차 리뷰 | VRAM·오버엔지니어링 지적 | **전부 검증** 후 설계 수정 | [`archive/review-claude-2026-05.md`](../archive/review-claude-2026-05.md) |
| **3차 리뷰** | V1.5 플러그·dogfood·reflection | 채택/기각·§6 순서 확정 | [`archive/review-gemini-2026-05-31.md`](../archive/review-gemini-2026-05-31.md), [`review-claude-2026-05-31.md`](../archive/review-claude-2026-05-31.md) |
| 확정 | — | 4축·범위·Phase 고정 | [`README.md`](../README.md), [`scope.md`](scope.md) |
| 기술결정 | ADR 초안 가능 | Accept/Reject 판단 | [`decisions/`](decisions/) |
| 반증 기록 | — | 가설 실패 문서화 | [`troubleshooting/`](../troubleshooting/) |

**최종 기준 문서는 항상 `docs/`** — `archive/`는 **과정·검토 로그**입니다.  
V1.5 구현 우선순위(비구현): [`archive/MALA_V2-vision.md`](../archive/MALA_V2-vision.md) §6.

---

## 3. AI 리뷰에서 채택·기각한 것 (요약)

### 제미나이 리뷰 (1차, 2026-05)

| 내용 | 처리 |
|------|------|
| Redis 장애 격리, Docker 이식성 | ✅ 설계 반영 |
| 인프라 → A2A → RAG 순서 | ✅ [`scope.md`](scope.md) 로드맵 |
| 모델 스와핑 I/O 리스크, 파이프라인 과다 | ✅ Won't / Phase 조정 |
| MoE 10GB “논리 완벽”, S급 표현 | ❌ **기각** — VRAM 트러블슈팅으로 정정 |
| “Qwen 3.6 하나” Plan B | ⚠️ **8B dense**로 재해석 |

### 클로드 리뷰 (2차, 2026-05)

| 내용 | 처리 |
|------|------|
| MoE active ≠ VRAM | ✅ [`troubleshooting/2026-05-20-moe-vram.md`](../troubleshooting/2026-05-20-moe-vram.md) |
| vLLM+GGUF+SGLang 혼선 | ✅ [ADR-001](decisions/001-inference-engine.md) |
| 5개 프로젝트 동시 진행 → 축소 | ✅ [`scope.md`](scope.md) Won't |
| 작은 동작 시스템 우선 | ✅ Phase 1~3 |

### 3차 리뷰 (2026-05-31 — V1.5/V2, SQLD 종료 후)

| 내용 | Gemini | Claude | **MALA 채택** |
|------|--------|--------|---------------|
| OpenHands SDK | 기각 | 기각 | ✅ **자체 구현** |
| 멀티에이전트 | 단일 모델 + 역할 프롬프트 | + **Critic reflection** | ✅ |
| 구현 순서 | 1→3→4→5 | **3→2→4→1→5** | ✅ **Claude 순서** |
| ModalProvider | 스텁 OK | 스텁 X | ✅ **README 1줄만** |
| MCP | 데모 1 + 보안 | 동일 | ✅ |
| Obsidian | 태그 필터 | 출처 + retrieval 표시 + 근거 가드 | ✅ **둘 다** |
| 인터페이스 5개 지금 | OK | 과함 → 2구현 후 추출 | ✅ **Claude** |
| Condenser / gate TTL | Condenser | 수직 E2E 먼저 | ✅ **둘 다** (순서상 6·5) |

**다음 구현 1순위:** study CLI + include + 출처 (dogfood).

---

## 4. 왜 archive를 공개하는가

- **투명성:** 설계가 하루 만에 “완성된 것처럼” 보이지 않게, **검토·수정 이력**을 남김  
- **비판적 사고:** AI 칭찬(MoE 완벽)을 **그대로 믿지 않고** 기각한 근거 제시  

설명할 때:

> “AI는 초안과 리뷰를 줬고, VRAM은 직접 검증해서 MoE안을 빼고, V1.5는 3차 리뷰로 dogfood·reflection 순서를 잡았습니다.”

---

## 5. AI 활용 원칙 (본 프로젝트)

1. **AI 출력 = 초안**, 최종 설계는 본인 검증 후 `docs/`에만 반영  
2. **숫자·스펙** (VRAM, 모델 크기)는 반드시 실측 또는 출처 링크  
3. **과장 톤** (S급, 1티어 완벽)은 archive에만 두고 정제본에서는 제거  
4. **기각한 AI 조언**도 문서화 — “맹신하지 않음”의 증거  
5. **(3차)** 인터페이스는 **돌아가는 E2E 다음** — 추상화 마비 방지 (Claude)

---

## 6. 관련 링크

- [`archive/README.md`](../archive/README.md) — 검토 기록 폴더 안내  
- [`archive/MALA_V2-vision.md`](../archive/MALA_V2-vision.md) — V1.5 브리프 + §8 합의  
- [`README.md`](../README.md) — 프로젝트 개요  
- [`troubleshooting/`](../troubleshooting/) — 검증·장애 기록  

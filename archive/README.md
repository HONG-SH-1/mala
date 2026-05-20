# Archive — 설계 검토 기록 (Design Review Log)

이 폴더는 **삭제할 쓰레기통이 아니라**, MALA 설계가 **어떻게 만들어졌는지**를 보여주는 **검토·초안 이력**입니다.

- **AI 보조:** 초안 작성·2차 관점 리뷰 (Gemini, Claude 등)  
- **사람 주도:** 채택/기각, VRAM 검증, 범위 축소, `docs/` 정제본 확정  

**「AI를 도구로 쓰되, 검증하고 문서화할 줄 안다」**는 과정을 남기기 위한 폴더입니다.  
상세: [`docs/design-process.md`](../docs/design-process.md)

---

## 파일 안내

| 파일 | 유형 | 정제·반영본 |
|------|------|-------------|
| [`draft-masterplan.md`](draft-masterplan.md) | 1차 마스터플랜 초안 (AI 협업) | [`docs/scope.md`](../docs/scope.md), [`docs/architecture.md`](../docs/architecture.md) |
| [`system-overview-draft.md`](system-overview-draft.md) | 4축 요약 초안 | [`README.md`](../README.md) |
| [`review-gemini-2026-05.md`](review-gemini-2026-05.md) | 외부 리뷰 ① — 리스크·Plan B | [`docs/scope.md`](../docs/scope.md) §6~7 |
| [`review-claude-2026-05.md`](review-claude-2026-05.md) | 외부 리뷰 ② — VRAM·범위 | [`troubleshooting/2026-05-20-moe-vram.md`](../troubleshooting/2026-05-20-moe-vram.md) |

---

## 리뷰별 채택 요약 (빠른 참고)

### `review-gemini-2026-05.md`

- **채택:** Redis 격리, Compose 이식성, 인프라 우선, 스와핑·DVC 후순위  
- **기각:** MoE VRAM “완벽”, S급·1티어 톤  
- **수정:** “Qwen 3.6 단일” → **Qwen3-8B dense** ([`model-comparison.md`](../docs/model-comparison.md))

### `review-claude-2026-05.md`

- **채택:** MoE≠VRAM, 오버엔지니어링 경고, 단일 소형 모델 우선  
- **반영:** ADR-001, scope Won't, troubleshooting #1

### `draft-masterplan.md`

- **상태:** Superseded (대체됨) — 아이디어 참고용  
- **주의:** 35B MoE·vLLM+GGUF 혼합 등은 **최종 설계에서 제거**

---

## 문서 읽는 순서

1. [`README.md`](../README.md)  
2. [`docs/architecture.md`](../docs/architecture.md)  
3. [`docs/design-process.md`](../docs/design-process.md) — AI 협업·검증 스토리  
4. (선택) 본 `archive/` — 설계 과정·리뷰 원본  

**최종 스펙·모델 표:** [`docs/model-comparison.md`](../docs/model-comparison.md) 실측 기준.

# ADR-001: 1차 추론 엔진 및 모델 포맷

| 항목 | 내용 |
|------|------|
| **상태** | Accepted (초안) |
| **날짜** | 2026-05-20 |
| **맥락** | Phase 1 인프라, RTX 3080 10GB |

---

## 맥락 (Context)

초기 기획은 **vLLM + GGUF Q4 + SGLang 모델 스와핑 + 멀티 MoE**를 동시에 가정했다.  
트러블슈팅 [MoE VRAM](../../troubleshooting/2026-05-20-moe-vram.md) 이후, **단일 소형 dense 모델**부터 검증하기로 했다.

---

## 결정 (Decision)

**Phase 1 기본 경로:**

1. **추론:** `Ollama` (또는 동등한 GGUF 런타임) + **Qwen3-8B Q4**
2. **포맷:** GGUF (`Q4_K_M` 등) — vLLM+GGUF 혼용은 하지 않음
3. **대안:** 동일 모델을 HF weights로 **vLLM** 단일 서비스 (Ollama 이슈 시)

**Phase 4 이후 검토:** vLLM 멀티 모델, SGLang 스와핑, Gemma+Qwen 듀얼

---

## 근거 (Rationale)

| 옵션 | 장점 | 단점 |
|------|------|------|
| Ollama + GGUF | Windows/로컬 셋업 단순, 8B 운영 용이 | 처리량·배치는 vLLM보다 낮을 수 있음 |
| vLLM + HF | 처리량, OpenAI 호환 API | GGUF 비주류, 10GB 튜닝 필요 |
| vLLM + GGUF | — | 비표준, 문서·예제 부족 |
| SGLang 스와핑 | 대형 MoE 이론상 유리 | 10GB·단일 GPU·일정 대비 과함 |

1차 목표는 **처리량 극대화**가 아니라 **재현 가능한 E2E**이다.

---

## 결과 (Consequences)

- `docker-compose.yml`의 `inference` 서비스는 Ollama 이미지 또는 vLLM 중 **하나만** 명시
- [`model-comparison.md`](../model-comparison.md) 실측은 선택한 엔진 기준으로 통일
- CrewAI·SGLang은 compose에 넣지 않음 (LangGraph만)

---

## 거부된 대안 (Rejected)

- 초기안: Qwen 35B-A3B MoE on 10GB — VRAM
- 초기안: vLLM + GGUF + SGLang 동시 — 운영 복잡도
- 초기안: Gemma 26B + Qwen 35B 동시 상주 — VRAM

---

## 관련

- [`../scope.md`](../scope.md)
- [`../../troubleshooting/2026-05-20-moe-vram.md`](../../troubleshooting/2026-05-20-moe-vram.md)

# MALA — 모델·VRAM 비교

RTX 3080 10GB에서 **어떤 모델을 올릴 수 있는지**를 가설이 아닌 **측정**으로 고정하기 위한 문서입니다.

> ⚠️ **「실측」열은 Phase 0에서 채웁니다.** 「문헌/추정」은 사전 조사 값입니다.

---

## 1. 핵심 교훈 (Phase 0 결론)

| 가설 (초기 기획) | 검증 결과 |
|------------------|-----------|
| MoE 35B, active 3B → VRAM ~3B급 | **기각** — 총 파라미터(전문가 가중치)가 VRAM을 지배 |
| 10GB + Q4로 Qwen 35B-A3B | **기각** — Q4만으로도 약 20GB+ 급 (소스·계산기 참고) |
| 1차 운영 모델 | **확정:** Qwen3-8B (`qwen3:8b`) — peak **7559 MiB** (~7.4 GB), ctx 4096, OOM 없음 |

상세 과정: [`../troubleshooting/2026-05-20-moe-vram.md`](../troubleshooting/2026-05-20-moe-vram.md)

---

## 2. MoE vs Dense — VRAM에 미치는 것

| 구분 | Dense | MoE |
|------|-------|-----|
| VRAM | 모델 전체 가중치 | **전체 expert 포함** 가중치 상주 |
| 연산/토큰 | 전체 FFN | **활성 expert만** 계산 (속도 이점) |
| 10GB 교훈 | 8B Q4가 안전 | 26B~35B MoE Q4는 10GB 부족 |

**요약:** MoE는 지식 용량은 크지만, VRAM은 active가 아니라 **total params**로 결정된다.

---

## 3. 후보 모델 비교표

| 모델 (가칭) | Quant | 총/활성 params | VRAM (문헌/추정) | 3080 10GB | 역할 (기획) | 실측 (본인 PC) | 비고 |
|-------------|-------|----------------|------------------|-----------|-------------|----------------|------|
| Qwen3-8B (`qwen3:8b`) | GGUF (Ollama) | 8B dense | ~4.5–5.5 GB (문헌) | ✅ | 단일 파이프라인 | **2026-05-20:** ctx **4096** · `ollama ps` **6.0 GB** · `nvidia-smi` peak **7559 MiB** / 10240 (여유 **~2.7 GB**) · GPU-Util **92%** (추론 burst) → 이후 1–12% · OOM **없음** | **Phase 1 확정** |
| Qwen3-14B-Instruct | Q4_K_M | 14B dense | ~10.8–12.8 GB | ⚠️ | 분석+코딩 통합 | _TBD_ | ctx↑ 시 OOM 위험 |
| Qwen3-14B-Instruct | Q3_K_M | 14B dense | ~8.6–9 GB | ⚠️ | 품질 타협 | _TBD_ | 10GB에서 시도 가능 |
| Qwen 35B-A3B (MoE) | Q4_K_M | 35B / ~3B active | ~21 GB+ | ❌ | 코딩 SOTA (기획) | _N/A_ | 기각 |
| Gemma 4 26B (MoE) | Q4 | 26B / ~4B active | ~14–16 GB | ❌ | 분석 (기획) | _N/A_ | 기각 |
| Gemma 4 4B (E4B) | Q4 | 4B dense | ~3 GB | ✅ | 경량 분석 | _TBD_ | 듀얼 모델 시 후보 |

**실측 채우기 컬럼:** 날짜, `max_model_len`, `nvidia-smi` peak, tok/s, OOM 여부.

---

## 4. 추론 엔진 × 포맷

| 엔진 | 포맷 | 3080 단일 GPU | MALA 1차 |
|------|------|---------------|----------|
| **Ollama** | GGUF | ✅ 단일 모델 운영 쉬움 | **우선 검토** |
| **llama.cpp** | GGUF | ✅ | Ollama와 유사 |
| **vLLM** | HF weights | ✅ 8B~14B | Phase 1 대안 |
| **vLLM** | GGUF | ❌ 비주류 | 사용 안 함 |
| **SGLang** | HF + 스와핑 | ⚠️ 복잡 | Phase 4 |

결정 기록: [`decisions/001-inference-engine.md`](decisions/001-inference-engine.md)

---

## 5. 실측 절차 (체크리스트)

로컬에서 동일 조건으로 반복합니다. **머신 스펙(CPU·RAM)** 은 [`hardware-environment.md`](hardware-environment.md)와 동일하게 기록합니다.

1. [x] CPU / RAM / OS — `hardware-environment.md` §3
2. [x] 드라이버·CUDA — **591.86 / CUDA 13.1** (`nvidia-smi`)
3. [x] 모델 ID·context — `qwen3:8b`, ctx **4096** (`ollama ps`)
4. [x] **추론 중** `nvidia-smi` peak — **7559 MiB**, GPU-Util **92%** (질문 입력 시 burst, `-l 1` 폴링)
4. [ ] 동일 프롬프트 10회 평균 tok/s (선택)
5. [ ] OOM 시 `max_model_len` / quant 한 단계 낮춰 재시도
6. [ ] 위 표 「실측」열 갱신 + 트러블슈팅 링크

### 예시 명령 (Ollama)

```bash
ollama run qwen3:8b
# 별도 터미널
nvidia-smi --query-gpu=memory.used --format=csv -l 1
```

### 예시 명령 (vLLM — Phase 1)

```bash
# .env의 MODEL_PATH, GPU_UTIL 참고
docker compose logs inference
```

---

## 6. 1차 배치 전략 (확정 전 초안)

| 역할 | 1차 | 2차 (여유 시) |
|------|-----|----------------|
| Router + 분석 + 코딩 | **Qwen3-8B Q4 단일** | 14B Q3 또는 Gemma-4B + Qwen-8B 스왑 |
| 검증/비판 | 규칙 + pytest | 소형 12B (별도 이슈) |

**모델 스와핑:** 디스크→VRAM 로딩 지연이 지배적이면 1차에서 보류 ([`scope.md`](scope.md)).

---

## 7. 참고 링크

- [MoE models explained (InsiderLLM)](https://insiderllm.com/guides/moe-models-explained/)
- [Qwen3 14B VRAM (Can It Run)](https://canitrun.net/models/qwen-3-14b/)
- [Will It Run AI — model VRAM](https://willitrunai.com/)

---

## 8. 변경 이력

| 날짜 | 변경 |
|------|------|
| 2026-05-20 | 초안 — 문헌/추정 표, 실측 TBD |
| 2026-05-20 | `qwen3:8b` 실측 확정 — peak 7559 MiB, GPU-Util 92% burst, OOM 없음 |

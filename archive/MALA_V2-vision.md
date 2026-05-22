# MALA V2 — 확장 설계안 (Vision)

> **구현 기준은 아님.** [`docs/scope.md`](../docs/scope.md) · [`docs/architecture.md`](../docs/architecture.md) · [`README.md`](../README.md)  
> V1(8B 단일 + Redis + **LangGraph** + RAG) E2E 검증 **이후** 단계적으로 검토하는 확장안.

---

## 0. 목적

V1에서 35B MoE **풀-VRAM** 기획이 불가능함이 확인됨([`troubleshooting/2026-05-20-moe-vram.md`](../troubleshooting/2026-05-20-moe-vram.md)).  
동일 철학(Data Sovereignty · Resource-Aware · 로컬 추론)을 **VRAM+RAM 하이브리드**와 **역할별 모델**로 확장하는 초안.

---

## 1. 메모리 예산 (RTX 3080 10GB · RAM 32GB)

```
VRAM 예산 ≈ 10GB − OS(~1GB) − KV캐시(2~4GB) → 가중치용 약 5~7GB
RAM  예산 ≈ 가용 ~19GB 중 오프로딩 ~14~16GB
하이브리드 수용량(4bit 가중치) ≈ VRAM 6GB + RAM 15GB ≈ 21GB 상당 (속도는 RAM 비중↑ 시 ↓)
```

- **풀-VRAM:** ~7B Q4 수준 한계  
- **하이브리드(`n-gpu-layers`):** 더 큰 MoE/dense **구동 가능** ≠ **1차 마일스톤** (튜닝·속도 부담)

---

## 2. DD-1 회고 (README·포폴용)

초기 설계에서 35B MoE를 검토했으나, **활성 파라미터가 작아도 전체 가중치는 VRAM(또는 VRAM+RAM)에 상주**해야 함을 확인했다.  
이에 **(1) 8B dense로 E2E 먼저 검증**하고, **(2) 필요 시 RAM 오프로딩·역할 분리**로 확장하는 순서를 택했다.

---

## 3. 오케스트레이션 (V1 유지)

**LangGraph**가 관제탑. Redis 큐는 에이전트 간 A2A만 담당(Open WebUI 등 UI는 선택).

```
사용자 → LangGraph Orchestrator → Redis task_queue/result_queue
         → Router(경량) → Retrieve(Chroma) → Worker(Ollama) → validate
```

---

## 4. 모델 — 1차 vs 확장

| 단계 | 구성 | 비고 |
|------|------|------|
| **V1 (지금)** | Qwen3-8B Q4 단일 · Ollama | Phase 1 E2E |
| **Conservative (다음)** | Router ~1.7B VRAM 상주 + Qwen3-14B 분석 + Qwen3-Coder-7B | 8B E2E 후 |
| **Ambitious (참고만)** | 26B~35B MoE 하이브리드 | 느림·실측 필수, 부록 참고 |

### 부록 — 4bit VRAM 참고치 (문헌·추정, 실측 전)

| 모델 | 4bit VRAM(대략) | 10GB 풀-GPU | 하이브리드 |
|------|-----------------|-------------|------------|
| Qwen3 8B | ~4.6GB | ✅ | — |
| Qwen3 14B | ~8.3GB | ⚠️ | ✅ |
| Gemma 26B MoE | ~14~16GB | ❌ | ✅(추정) |
| Qwen 35B-A3B MoE | ~21GB | ❌ | ⚠️(추정·느림) |

*KV 캐시 별도. tok/s 등 속도 수치는 **본인 PC 실측 전 포폴에 사용 금지**.*

---

## 5. 토큰 이코노미 (설계 의도)

| 전략 | 효과 |
|------|------|
| Router-First | 큰 모델 호출 최소화 |
| 로컬 추론 (Ollama) | API 종량 과금 없음 |
| 하이브리드 오프로딩 | 대형 GPU 없이 품질 확장 여지 |
| Semantic Chunking + SHA 증분 | 입력·인덱싱 비용↓ |

**Phase 4 (옵션):** Vertex AI 등 클라우드 RAG와 동일 30문항 **대조 실험** — 비용·크레딧 있을 때만.

---

## 6. `recommend_model.py` (Phase 2 — Resource-Aware 시그니처)

사양(GPU VRAM, RAM, CPU)을 읽고 Conservative/Ambitious 후보와 `n-gpu-layers`·**근거 문장**을 출력.

```python
"""recommend_model.py — 로컬 PC 사양 기준 모델·오프로딩 추천 (스켈레톤)."""
import psutil

try:
    import pynvml
    pynvml.nvmlInit()
    h = pynvml.nvmlDeviceGetHandleByIndex(0)
    gpu_name = pynvml.nvmlDeviceGetName(h)
    vram_gb = pynvml.nvmlDeviceGetMemoryInfo(h).total / 1024**3
except Exception:
    gpu_name, vram_gb = "unknown", 0.0

ram_gb = psutil.virtual_memory().total / 1024**3
vram_budget = max(vram_gb - 1 - 3, 0)
ram_budget = ram_gb * 0.55

def pick(vram, ram):
    if vram >= 16:
        return "full-gpu", "14B~32B class", "VRAM 여유"
    if 6 <= vram <= 10 and ram >= 24:
        return "hybrid", "14B or MoE with offload", "VRAM 작고 RAM 충분"
    if 6 <= vram <= 10:
        return "vram-first", "8B~14B Q4", "RAM 여력 적음 — 8B E2E 우선"
    return "minimal", "8B Q4", "보수적 단일 모델"

mode, model_hint, why = pick(vram_budget + 4, ram_gb)
print(f"GPU {gpu_name} {vram_gb:.0f}GB | RAM {ram_gb:.0f}GB\nmode={mode}\n{model_hint}\n{why}")
```

---

## 7. Phase 정렬 (V1 기준)

| Phase | V1 (구현 기준) | V2 vision |
|-------|----------------|-----------|
| 0~1 | 8B · Redis · Ollama | 동일 |
| 2 | LangGraph + Envelope + **`recommend_model.py`** | + Conservative 하이브리드 검토 |
| 3 | Obsidian · Chroma RAG | 동일 |
| 4 | 선택 | Vertex 대조 · Open WebUI · GraphRAG |

---

*원본 전체 초안: 루트 `MALA_V2_아키텍처.md` (다이어트 후 본 파일로 대체)*

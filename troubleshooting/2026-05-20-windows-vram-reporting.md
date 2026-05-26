# [2026-05-20] Windows에서 ollama ps 6GB vs nvidia-smi 1.7GB 불일치

## 증상

`qwen3:8b` 로드 후:

| 도구 | 값 |
|------|-----|
| `ollama ps` | **SIZE 6.0 GB**, PROCESSOR **100% GPU**, CONTEXT **4096** |
| `nvidia-smi` (동일 시점, idle) | **1704 MiB / 10240 MiB** (~1.7 GB), GPU-Util **1%** |

문헌·추정(~4.5–5.5 GB Q4)과도, 두 도구끼리도 숫자가 맞지 않음.

## 환경

- **GPU:** RTX 3080 10GB
- **드라이버:** 591.86 (Windows 32.0.15.9186) · **CUDA 13.1** (`nvidia-smi` 표기)
- **OS:** Windows · **Driver Model: WDDM**
- **엔진:** Ollama · `qwen3:8b`

## 비교 (같은 날 측정)

| 상태 | `nvidia-smi` Used | 비고 |
|------|-------------------|------|
| Ollama 3프로세스 + Claude 등 (정리 전) | **7476 MiB** | 일반 사용 스냅샷 |
| `qwen3:8b` 단독 로드 후 idle | **1704 MiB** | WDDM idle — peak와 별도 기록 |
| `qwen3:8b` **추론 중** peak (질문 입력) | **7559 MiB**, GPU-Util **92%** | burst 후 **7557 MiB** 유지, Util 1–12% |

## 원인 (확정)

1. **WDDM idle under-report:** idle `nvidia-smi`는 **추론 peak보다 훨씬 낮게** 보일 수 있다.
2. **peak ≈ ollama ps:** 추론 중 **7559 MiB (~7.4 GB)** 는 `ollama ps` **6.0 GB** + KV·버퍼와 **일치**. VRAM은 질문 직후 **~7557 MiB에 고정**, 토큰 생성 중 **GPU-Util만 92% → 1–12%로 진동**.
3. **idle 폴링(질문 없음):** GPU-Util **0–4%**만 보일 수 있음 — **질문을 넣은 구간**으로 peak를 잡는다.

## 시도한 것

| # | 시도 | 결과 |
|---|------|------|
| 1 | Ollama 다중 프로세스 정리 | ✅ `nvidia-smi` 7476 → 1704 MiB로 감소 |
| 2 | `ollama ps` + idle `nvidia-smi` | ⚠️ 6.0 GB vs 1.7 GB 불일치 확인 |
| 3 | 추론 **중** 질문 입력 + `nvidia-smi -l 1` | ✅ peak **7559 MiB**, Util **92%** burst |

## 해결 / 우회 (Phase 0 기록 규칙)

1. **MALA 10GB 예산 (qwen3:8b):** peak **~7.4 GB (7559 MiB)** → Docker/Redis용 **~2.7 GB** 여유.
2. **`.env` `MAX_MODEL_LEN=4096`** 유지 — 실측 ctx와 일치.
3. Phase 1 전 **Claude·Edge·Ollama 중복** 정리 권장.

## 재측정 명령

```powershell
# 터미널 1
ollama run qwen3:8b

# 터미널 2 (1초마다)
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv -l 1
```

긴 프롬프트 1회 보낸 뒤 **memory.used 최대값**을 peak로 기록.

## 교훈 (한 줄)

> **idle 폴링만** 하면 Util 0–4%로 오해하기 쉽다. **질문을 넣은 구간**에서 peak VRAM·Util을 잡는다.

## 참고

- [`../docs/model-comparison.md`](../docs/model-comparison.md)
- [`../docs/hardware-environment.md`](../docs/hardware-environment.md)

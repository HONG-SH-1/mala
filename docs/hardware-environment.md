# MALA — 하드웨어·런타임 환경

Local LLM·RAG·멀티 에이전트는 **GPU만**이 아니라 **CPU·RAM·디스크**도 병목이 됩니다.  
PoC·실측 시 **동일 스펙 표**를 기준으로 재현성을 맞춥니다.

---

## 1. 개발·운영 워크스테이션 (기준)

| 구성 | 스펙 | MALA에서의 역할 |
|------|------|-----------------|
| **CPU** | AMD Ryzen 5 5600X (6C/12T, ~3.7GHz) | Docker·Redis·에이전트 로직, **임베딩**, 일부 CPU offload, 인덱싱 |
| **GPU** | NVIDIA GeForce **RTX 3080** (**10GB VRAM**) | LLM 추론 가중치·KV cache (**1차 병목**) |
| **GPU 드라이버** | **591.86** (Windows 32.0.15.9186) · **CUDA 13.1** (`nvidia-smi`) | CUDA·Ollama 호환; Phase 0 실측 환경 |
| **RAM** | **32.0 GB** 설치 (총 실제 **31.9 GB**) | Ollama/vLLM 호스트·offload, Chroma, Redis, Docker |
| **Storage** | _TBD_ (SSD 권장) | GGUF 모델, Obsidian vault, 벡터 인덱스 |
| **OS** | Windows 10/11 | 개발 호스트 |
| **컨테이너** | Docker Desktop + WSL2 (권장) | Redis, inference, agent 동일 네트워크 |

### RAM · 가상 메모리 (Windows `msinfo32` / 시스템 정보, 2026-05 기준)

| 항목 | 값 | 설명 |
|------|-----|------|
| 설치된 실제 메모리 | **32.0 GB** | 물리 DIMM 용량 |
| 총 실제 메모리 | **31.9 GB** | OS에서 보이는 물리 RAM (펌웨어·예약 일부 차감) |
| 사용 가능한 실제 메모리 | **17.7 GB** | **측정 시점** 스냅샷 — 백그라운드 앱·브라우저 등에 따라 변동 |
| 총 가상 메모리 | **63.9 GB** | 물리 RAM + 페이징 파일(page file) |
| 사용 가능한 가상 메모리 | **44.4 GB** | **측정 시점** 스냅샷 |

> **문서에 고정하는 값은 「32 GB 설치」** 입니다. 「사용 가능 17.7 GB」는 스펙이 아니라 **그때 idle에 가까운 여유**이므로, LLM 추론·인덱싱 **peak**은 Phase 0에서 별도 기록합니다.

---

## 2. 왜 GPU만 적으면 안 되는가

| 작업 | 주로 쓰는 자원 | 5600X + RAM 관점 |
|------|----------------|------------------|
| LLM 추론 (8B Q4) | GPU VRAM | VRAM 부족 시 **RAM/CPU offload** → RAM 압박 |
| 임베딩 (RAG) | CPU 또는 GPU | 보통 **CPU+RAM** — GPU만 문서화하면 설계가 반쪽 |
| Chroma / 인덱스 빌드 | CPU + RAM + 디스크 | 대량 MD 인덱싱 시 **RAM·I/O** 병목 |
| Redis · LangGraph | CPU + RAM | 상대적으로 가벼움 |
| Docker 여러 서비스 | RAM | inference + redis + agent 동시 기동 시 **여유 RAM** 필요 |

**설계 요약:** GPU(10GB)로 LLM 한계를 잡고, **RAM 32GB**로 Docker·Chroma·임베딩·(필요 시) CPU offload 여유를 확보합니다.

---

## 3. 실측·기록 체크리스트 (Phase 0)

동일 머신에서 한 번에 기록해 [`model-comparison.md`](model-comparison.md)와 연결합니다.

- [x] **RAM 설치:** 32 GB (`msinfo32` 확인)
- [ ] **RAM peak:** 추론+인덱싱 동시 실행 시 사용 가능 메모리 최소값
- [x] **GPU 모델·드라이버:** RTX 3080 · 32.0.15.9186
- [x] **GPU VRAM peak:** `qwen3:8b` 질문 입력 시 **7559 MiB**, GPU-Util **92%** burst (2026-05-20)
- [ ] **CPU:** 인덱싱·추론 시 Utilization (과열/스로틀 여부)
- [ ] **디스크:** 모델·vault·index 경로, 여유 공간

### Windows에서 RAM 확인 (예시)

```powershell
# 설치 RAM (GB)
(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB

# 또는
systeminfo | findstr /C:"Total Physical Memory"
```

---

## 4. 설계에 미치는 제약 (요약)

| 자원 | 보수적 가정 (10GB GPU 기준) |
|------|----------------------------|
| VRAM | 8B Q4 + context — [`model-comparison.md`](model-comparison.md) |
| RAM | **32 GB** — 8B Q4 + Compose + Chroma 동시 구동에 **여유** (peak는 Phase 0 실측) |
| CPU | 6C — 에이전트·임베딩 **동시** 시 큐·배치로 겹침 최소화 (Phase 2) |

---

## 5. `.env` / Compose와의 관계

- GPU: `GPU_MEMORY_UTILIZATION`, `MAX_MODEL_LEN` — [`.env.example`](../.env.example)
- CPU/RAM: 코드에서 **동시 인덱싱 + 추론** 피하기 (Phase 3), worker 수 1부터

---

## 6. 변경 이력

| 날짜 | 변경 |
|------|------|
| 2026-05-20 | 문서 신규 — CPU 5600X, RAM 32 GB (`msinfo32`) |
| 2026-05-20 | GPU 드라이버 32.0.15.9186 기록 (Phase 0) |

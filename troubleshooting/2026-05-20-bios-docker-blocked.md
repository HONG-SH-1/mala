# [2026-05-22] BIOS 잠금으로 Docker Desktop Engine 불가

## 증상

- Docker Desktop: **Virtualization support not detected**, Engine stopped
- `systeminfo`: **가상화 기반 보안: 사용 안 함**, Hyper-V 펌웨어 가상화 **아니요**
- BIOS 진입 시 **Setup Password** 요구 — 중고 PC, 이전 판매자 암호 미확보

## 기대 vs 실제

| 항목 | 기대 (초기 Phase 1) | 실제 |
|------|---------------------|------|
| 인프라 | `docker compose up` | **Engine 시작 불가** |
| SVM | Enabled | **BIOS 접근 불가로 변경 불가** |

## 환경

- MSI B550M MORTAR (MS-7C94), Ryzen 5600X, RTX 3080 10GB
- Windows, WSL 2.7.3 (CLI는 있으나 Docker Engine 미기동)

## 시도한 것

| # | 시도 | 결과 |
|---|------|------|
| 1 | `wsl --update` | ✅ WSL 버전 OK, Docker Engine 여전히 stopped |
| 2 | Docker Desktop Skip 로그인 | ✅ irrelevant |
| 3 | BIOS Del 진입 | ❌ Setup Password |

## 해결 / 우회

**ADR-002:** Windows **Native Redis** + 호스트 Python Worker + Ollama(호스트)  
→ Phase 1 Must(큐 왕복) **Docker 없이** 진행

**나중에 (선택):** 판매자 BIOS 암호 또는 CMOS 클리어(JBAT1) → SVM Enabled → `docker compose up`

## 교훈 (한 줄)

> **로컬 Docker 성공 여부 ≠ MALA Must** — 큐·Envelope·Ollama E2E가 본체이고, Docker는 재현성 옵션이다.

## 참고

- [`../docs/decisions/002-native-redis-phase1.md`](../docs/decisions/002-native-redis-phase1.md)

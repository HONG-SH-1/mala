# ADR-002: Phase 1 — Native Redis (Docker 우회)

| 항목 | 내용 |
|------|------|
| **상태** | Accepted |
| **날짜** | 2026-05-22 |
| **맥락** | BIOS Setup Password 잠금 → SVM(AMD-V) 비활성 → Docker Desktop Engine 불가 |

---

## 맥락 (Context)

- `systeminfo`: **Hyper-V 펌웨어 가상화 = 아니요**
- Docker Desktop: **Virtualization support not detected**
- 중고 PC **BIOS 진입 불가**(Setup Password)
- Phase 0 **Ollama `qwen3:8b` 실측 완료** (peak 7559 MiB) — 추론 경로는 Windows 네이티브로 충분

Phase 1 Must: **Redis + JSON Envelope `task_queue` / `result_queue` 왕복 1회** ([`../scope.md`](../scope.md))

---

## 결정 (Decision)

**Phase 1 기본 경로 (현재):**

1. **Redis:** Windows **Native** 설치 (`localhost:6379`)
2. **Worker / E2E:** 호스트 Python (`src/`)
3. **Ollama:** Windows 호스트 (`http://127.0.0.1:11434`) — 컨테이너 아님
4. **Docker Compose:** [`docker-compose.yml`](../../docker-compose.yml)는 **BIOS 해제 후 optional** — Phase 1 완료 조건에 필수 아님

---

## 근거 (Rationale)

| 옵션 | 장점 | 단점 |
|------|------|------|
| BIOS SVM + Docker | IaC·`compose up` 재현성 | BIOS 암호로 **차단**, WSL2 RAM ~1–2GB |
| **Native Redis (채택)** | **지금 즉시** 큐 E2E, RAM 절약 | 원클릭 clone 실행성 ↓ (Redis 설치 필요) |
| WSL2 Redis only | Linux Redis | SVM OFF면 **동일 차단** |

**Trade-off:** 재현성 일부 ↔ **개발 속도·VRAM/RAM 확보**. 큐·Envelope·Ollama 연동 **패턴은 동일** — 엔드포인트만 `localhost`.

---

## 결과 (Consequences)

- README **빠른 시작** = Native Redis 경로 우선
- `docker-compose.yml` 유지 — SVM 활성화 후 전환 가능
- 트러블슈팅: BIOS 잠금은 [`../../troubleshooting/2026-05-20-bios-docker-blocked.md`](../../troubleshooting/2026-05-20-bios-docker-blocked.md)

---

## 관련

- [ADR-001](001-inference-engine.md)
- [`../architecture.md`](../architecture.md)
- [`../../troubleshooting/2026-05-20-windows-vram-reporting.md`](../../troubleshooting/2026-05-20-windows-vram-reporting.md)

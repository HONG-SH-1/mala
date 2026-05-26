# MALA — 인프라 방향·실무·커리어 의견 공유

> **성격:** 구현 기준(`scope.md`, ADR)이 아니라 **상황·가설·트레이드오프·의견**을 모은 문서.  
> **작성:** 2026-05-22 · Phase 1 Native Redis 구현 직후  
> **관련:** [ADR-002](decisions/002-native-redis-phase1.md) · [architecture.md](architecture.md) · [troubleshooting/2026-05-20-bios-docker-blocked.md](../troubleshooting/2026-05-20-bios-docker-blocked.md)

---

## 1. 지금 우리가 처한 상황 (Facts)

| 항목 | 상태 |
|------|------|
| **목표** | MALA V1 — 로컬 LLM + Redis 큐 + (후) LangGraph + RAG |
| **하드웨어** | RTX 3080 10GB, 32GB RAM, Ryzen 5600X, Windows |
| **Phase 0** | ✅ `qwen3:8b` 실측 (peak 7559 MiB), MoE 35B 기각 문서화 |
| **Phase 1 코드** | ✅ Native Redis 경로 — `src/worker.py`, `e2e_once.py` |
| **Docker Desktop** | ❌ BIOS Setup Password → SVM OFF → Engine stopped |
| **Ollama** | ✅ Windows 호스트에서 동작 (가상화 불필요) |
| **레포 Must** | 큐 왕복 1회 · (문서상) 재현 가능한 인프라 |

**한 줄:** 추론(Ollama)은 이미 **온프레 호스트**이고, 막힌 건 **「컨테이너로 Redis를 올리는 재현 레이어」** 뿐이다.

---

## 2. 사용자 의견 (Your take)

> 「Redis를 보통 WAS에 올리지 않나?」  
> 「실무를 생각하면 아예 그쪽으로 가는 게 좋지 않을까?」

### 2.1 의견이 맞는 부분

실무에서 **Redis를 개발자 노트북에 “서비스처럼” 상시 두는 경우**는 상대적으로 적다.

| 환경 | Redis가 있는 위치 (흔한 패턴) |
|------|------------------------------|
| **금융·대기업 온프레** | 전용 Redis 클러스터 / **공용 미들웨어** (WAS **옆** 또는 **앞** 단) |
| **클라우드** | **ElastiCache**, Memorystore, Azure Cache for Redis |
| **Kubernetes** | Redis Operator / **별도 StatefulSet** (앱 Pod와 분리) |
| **WAS (Spring 등)** | WAS **인스턴스 안**이 아니라 **외부 엔드포인트**로 `spring.data.redis.host` 연결 |

즉 **「Redis = WAS 프로세스 안에 내장」** 이 아니라,  
**「WAS(애플리케이션 서버)가 Redis(메시지/캐시 인프라)를 호출한다」** 가 정확에 가깝다.

**MALA에서의 대응 개념:**

```
[WAS에 해당]     Python Worker / (후) LangGraph Orchestrator  ← 비즈니스·에이전트
[Redis에 해당]   task_queue / result_queue                     ← 인프라 (별도 프로세스)
[LLM에 해당]     Ollama @ host:11434                           ← 또 다른 외부 엔드포인트
```

지금 Native Redis는 **「노트북에 Redis.exe 깔기」** 이지만, **아키텍처 역할**은  
**「앱 서버와 분리된 Redis 엔드포인트」** 라는 점에서 **실무 그림과 같은 축**이다.

### 2.2 조정이 필요한 부분

**「WAS 쪽으로 아예 다 옮기자」** 를 **지금 전부** 의미한다면 범위가 커진다.

| 해석 | Phase 1과의 관계 |
|------|------------------|
| Redis를 **Spring Boot + WAS** 로만? | 스택 전환 → **새 프로젝트**에 가깝음 |
| **배포 단위**를 WAS/서비스 jar·war처럼? | Phase 2~3 이후 **패키징** 이슈 |
| **엔드포인트 분리** (앱 / Redis / LLM)? | ✅ **이미 그 방향** — Native든 Docker든 동일 |

**실무 WAS**는 보통 **Tomcat/Jeus/WebLogic + Spring** 이고,  
MALA는 **Python + LangGraph** — **런타임은 다르지만 “앱 ↔ 외부 Redis/LLM” 분리**는 동일한 설계 문법이다.

---

## 3. 신입이 흔히 내는 「최선」 (Baseline)

취준·신입 포트폴리오에서 **자주 보이고, 면접에서도 통과는 하는** 수준:

| # | 패턴 | 한계 |
|---|------|------|
| 1 | LangChain 한 파일에 RAG+LLM | 장애·큐·재시도 없음 |
| 2 | Docker 없이 `main.py` 한 방 | 재현성·환경 차이 설명弱 |
| 3 | 「Redis 썼습니다」 | **왜** 큐인지, 유실 방지 없음 |
| 4 | VRAM 숫자 없음 | 「로컬 LLM 해봤다」만 |
| 5 | 기획서만 크고 E2E 없음 | 신뢰도 ↓ |

**신입 최선 = “해 봤다” + 튜토리얼 조합.**

---

## 4. 그 위에 있는 생각 (Beyond baseline) — 합의·차별

아래는 **이미 MALA에서 하고 있거나, 하려는 것**과 **사용자 의견(WAS/실무)** 을 겹쳐 본 **한 단계 위**이다.

### 4.1 리소스에서 결정한다 (이미 함)

- MoE active ≠ VRAM → **기각 + 트러블슈팅**
- `qwen3:8b` **7559 MiB 실측** → 설계 숫자

→ 신입은 “8B 썼다”; 그 위는 **“왜 35B가 아닌지 한 줄 증명”**.

### 4.2 인프라 장애를 숨기지 않는다 (지금 함)

- BIOS 잠금 → Docker 불가 → **ADR-002 Native Redis**
- 실패를 우회가 아니라 **기록**

→ 신입은 Docker 실패를 포기; 그 위는 **「제약下 B안 + Must 충족」**.

### 4.3 실무와 같은 「엔드포인트 분리」 (부분 일치)

| 실무 | MALA V1 |
|------|---------|
| WAS → Redis host:port | Worker → `localhost:6379` |
| WAS → LLM API | Worker → `127.0.0.1:11434` |
| (후) API Gateway | Phase 2 Orchestrator |

**사용자 의견「WAS 쪽」** 을 **“Spring으로 갈아타자”** 가 아니라  
**“앱 레이어와 인프라 레이어를 문서·폴더·프로세스로 분리하자”** 로 읽으면 **이미 정렬**이다.

### 4.4 신입을 넘는 다음 한 칸 (아직 여지)

| 주제 | 내용 | 시기 |
|------|------|------|
| **환경 프로파일** | `local` (Native Redis) / `docker` (compose) / `corp` (host만 env) | Phase 1.5 문서 |
| **WAS 아키텍처 대응 표** | “Spring RedisTemplate = 우리 `RedisBroker`” 1페이지 | 이 문서 §6 |
| **무결점 큐** | BRPOPLPUSH, DLQ (코드 있음) | Phase 1 검증 후 |
| **Pass-by-Reference envelope** | 제미나이 설계, Phase 3 전 스키마 | ADR-003 예정 |
| **관측** | `task_status`, 구조화 로그 | Phase 2 |
| **평가** | 동일 10질문 로컬 vs (옵션) Vertex | Phase 4 |

**“WAS로 간다”의 현실적 다음 스텝 (Python 유지):**

- Worker/Orchestrator를 **하나의 “애플리케이션 서비스”** 로 보고  
- Redis URL을 **`.env` / 환경별 설정** 만 바꿈 (`localhost` → `redis.corp.internal`)  
- **배포 산출물**은 `pip install` + systemd 또는 (BIOS 해제 후) **단일 컨테이너 이미지** — 이게 **실무 WAS 배포와 대화 가능한 지점**

---

## 5. 트레이드오프 — 세 갈래 비교

| | **A. 지금 (Native Redis + Python)** | **B. Docker Compose** | **C. “진짜 실무” (공용 Redis + WAS/K8s)** |
|--|--------------------------------------|------------------------|-------------------------------------------|
| **지금 가능** | ✅ | ❌ (BIOS) | ❌ (회사 인프라 없음) |
| **Must 충족** | ✅ 큐 E2E | BIOS 후 | N/A |
| **실무 유사도** | 엔드포인트 분리 **중** | compose **상** | **최상** (직장에서만) |
| **포트폴리오 스토리** | 제약·ADR·실측 | 재현성 | JD 맞춤 (경력 후) |
| **RAM** | 가장 가벼움 | WSL2 +1~2GB | 해당 없음 |
| **신입 최선 대비** | ✅✅ | ✅ | 경력자 |

**권고:** **A로 Must 닫기** → BIOS 풀리면 **B 추가** → 면접/이력서에는 **C의 “연결 방식”만 언어로 대응** (§6).

---

## 6. 면접·실무 한 줄 번역 (WAS ↔ MALA)

면접관이 **「WAS에서 Redis 어떻게 쓰나요?」** 라고 하면:

| 실무 (Java/Spring) | MALA (Python) |
|--------------------|---------------|
| `@EnableRedis`, `RedisTemplate` | `RedisBroker` (`src/broker/`) |
| JMS / 메시지 리스너 | `worker.py` + `BRPOPLPUSH` |
| 외부 `application.yml` redis.host | `.env` `REDIS_HOST` |
| WAS 재기동 시 세션/큐 | processing 큐 + (수동) requeue |
| LLM은 별도 API 호출 | Ollama HTTP |

**「노트북 Native Redis」** 는 **개발 환경** 이고,  
**「WAS가 외부 Redis를 바라본다」** 는 **아키텍처** — 둘은 모순이 아니다.

---

## 7. 종합 의견 (Cursor / 아키텍트)

### 7.1 사용자 의견에 대한 답

- **「Redis는 WAS(애플리케이션)와 분리된 인프라」** → **동의.** 그게 실무 표준이다.
- **「그래서 지금부터 Spring WAS로」** → **Phase 1 Must에는 과함.** Python MALA와 **역할 분리 개념만 공유**하면 충분.
- **「Native Redis는 초라하지 않나?」** → **개발 환경일 뿐.** ADR-002 + 엔드포인트 분리 설명이면 **신입 최선을 넘는다.**

### 7.2 신입 최선을 넘기려면 (우선순위)

1. **`e2e_once` 성공** (Must 닫기)  
2. **이 문서 + ADR-002** 로 「왜 Native인지」 30초 설명  
3. **§6 WAS 대응 표** 로 「실무에서 어디에 두나」 연결  
4. Phase 2 LangGraph — **Orchestrator = WAS 역할** 명시  
5. (선택) BIOS 해제 후 `docker compose` **한 줄** 추가 — 재현성 보너스  

### 7.3 하지 말 것 (지금)

- 스택을 Spring으로 **갈아타기** (Must 리셋)  
- Jenkins / 5000건 카오스 / Vertex 전면 전환  
- Docker 안 되니까 **프로젝트 멈추기**  

---

## 8. 결론 한 장

```
상황:  BIOS → Docker X  |  Ollama O  |  Phase 1 코드 O
의견:  실무는 WAS(앱) + 외부 Redis  →  MALA도 같은 분리 (런타임만 Python)
신입:  튜토리얼 + "Redis 써봄"
그 위:  VRAM 실측 + MoE 기각 + ADR 우회 + 큐 무결 + (면접) WAS 대응 표
다음:  e2e_once ✅ → Phase 2 LangGraph = "WAS/Orchestrator" 레이어
```

---

## 9. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-05-22 | 초안 — 상황·사용자 의견·신입 vs 차별·WAS 대응 |

---

## 10. 관련 링크

- [README.md](../README.md) — Phase 1 빠른 시작  
- [design-process.md](design-process.md) — AI 리뷰 채택/기각  
- [archive/MALA_V2-vision.md](../archive/MALA_V2-vision.md) — 확장 (하이브리드, Vertex 옵션)

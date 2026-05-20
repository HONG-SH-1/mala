<!--
  [설계 초안 — Draft v0]
  작성: AI 협업 브레인스토밍 + 본인 요구 입력 · 상태: Superseded
  최종: README.md, docs/architecture.md, docs/scope.md
  주의: 35B MoE·vLLM+GGUF 혼합 등은 검토 후 제거됨. 참고용 아카이브.
-->

# **[프로젝트 이해: MALA (Multi-Agent Local AI) 시스템]**

## 1. 프로젝트 개요

- **목적:** RTX 3080(10GB VRAM) 환경에서 최신 SOTA SLLM을 활용한 온디바이스 지식 자동화 및 멀티 에이전트 협업 시스템 구축.
- **핵심 철학:** **Data Sovereignty(로컬 주권)** + **Resource-Aware Layering(계층적 리소스)**.

---

## 1.1 하드웨어 자원 전략 및 근거

RTX 3080 10GB 환경에서 **Qwen 3.6-35B-A3B**와 같은 대형 모델을 운영하는 것은 '리소스 효율화의 정수'를 보여주는 도전입니다.

- **설계 의도:** 10GB라는 VRAM 한계 내에서 '모델의 지능'을 극대화.
- **핵심 근거 (MoE 기반 효율화):**
    - **Sparse MoE 모델 활용:** Qwen 3.6-35B-A3B는 전체 파라미터가 35B이지만, 추론 시 활성화되는 파라미터는 3B에 불과합니다. 이는 VRAM 점유를 최소화하면서도 35B급의 거대한 지식 용량을 활용할 수 있음을 의미합니다.
    - **4비트 양자화 (Q4_K_M):** 모델 가중치를 4비트로 양자화하면 정밀도 손실은 최소화하면서(약 1% 미만), 모델의 VRAM 점유율을 1/4 수준으로 압축할 수 있습니다. 이는 10GB 환경에서 "더 큰 모델(Larger Knowledge Capacity)"을 올리기 위한 필연적 선택입니다.
- **메모리 관리 정책:**
    - **vLLM PagedAttention:** 일반적인 메모리 할당 방식은 메모리 단편화(Fragmentation)로 인해 버려지는 공간이 많습니다. PagedAttention은 운영체제의 가상 메모리 관리(Virtual Memory) 방식을 차용하여, 연속적이지 않은 메모리 공간을 유연하게 활용함으로써 VRAM 효율을 20% 이상 향상시킵니다.

## 1.2 컨테이너 기반 인프라 구축 (Docker-Compose)

단순한 서비스 띄우기가 아닌, '격리된 환경(Environment Isolation)'과 '확장성(Scalability)'을 고려한 배포 단위입니다.

YAML

```yaml
# docker-compose.yml
version: '3.8'
services:
  # 추론 엔진: vLLM 활용
  vllm-engine:
    image: vllm/vllm-openai:latest
    runtime: nvidia
    deploy:
      resources:
        reservations:
          devices: [{'driver': 'nvidia', 'count': 1, 'capabilities': ['gpu']}]
    command: >
      --model /models/Qwen3.6-35B-A3B-Q4_K_M
      --max-model-len 8192
      --gpu-memory-utilization 0.7
      --enable-prefix-caching    volumes:
      - ./models:/models
    ports:
      - "8000:8000"

  # 메시지 브로커: Redis (에이전트 간 통신용)
  redis-broker:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --save 60 1 --loglevel warning
```

- **근거:** `docker-compose`는 에이전트 서비스와 브로커 서비스를 동일한 네트워크 네임스페이스(`localhost`)에서 공유하게 하여, 네트워크 오버헤드 없이 빠른 통신을 가능하게 합니다.

## 1.3 데이터 저장소 계층화 (Storage Tiering)

데이터의 '접근 빈도(Access Frequency)'와 '연산 비용(Computation Cost)'을 고려한 계층 구조입니다.

| **레이어** | **기술** | **설계 근거** |
| --- | --- | --- |
| **Hot (VRAM)** | 모델 캐시 | 추론 직전의 데이터. 최우선적으로 VRAM에 상주하여 지연 시간을 0에 수렴시킴. |
| **Warm (RAM)** | Redis | 에이전트 간 주고받는 '상태(State)'. 디스크 I/O 없이 메모리에서 즉시 큐잉. |
| **Cold (SSD)** | Obsidian / DVC | 수정 빈도가 낮고 크기가 큰 원본 지식. Git/DVC로 관리하여 버전의 일관성 보장. |

## 1.4 장애 대응 및 가시성 (Monitoring)

신입 엔지니어가 놓치기 쉬운 **'시스템 운영(Observability)'** 파트입니다.

- **실패 격리 (Fault Isolation):** 만약 Qwen(코딩 에이전트)이 OOM으로 죽더라도, Redis 큐에는 작업 내용이 남아 있습니다. vLLM이 재시작되면 큐를 다시 읽어 중단된 시점부터 작업을 이어갈 수 있습니다.
- **모니터링 지표:**
    - `vllm:num_requests_running`: 현재 처리 중인 요청 수.
    - `redis:connected_clients`: 에이전트 간 연결 상태.
    - `gpu:utilization.memory`: 10GB VRAM 중 점유율(안전 마진 30%를 넘지 않는지 상시 체크).

**[설계 의도 요약]**

이 인프라의 핵심은 "한정된 하드웨어(3080 10GB) 내에서 모델의 성능은 최대로(MoE+양자화), 시스템의 가용성은 안정적으로(Docker+Redis) 유지하는 것"입니다.

---

# [Session 2: 데이터 버전 관리 및 GraphRAG 인덱싱 파이프라인]

이 세션의 핵심은 "Obsidian의 비정형 마크다운 데이터를 어떻게 정형화된 지식 그래프로 변환하고, 이를 AI 에이전트가 실시간으로 활용하게 할 것인가"입니다. 실무에서는 데이터의 파이프라인이 깨지면 모델의 성능이 급격히 저하되므로, 재현성(Reproducibility)과 **자동화**가 필수적입니다.

## 2.1 데이터 파이프라인 아키텍처 (Obsidian to Knowledge Graph)

파이프라인은 `Obsidian(Raw Data)` → `DVC(Versioning)` → `Extraction(Entity/Relation)` → `GraphStore(Storage)` 순으로 흐릅니다.

### 2.1.1 데이터 버전 관리 (DVC + Git)

- **설계 의도:** 모델이 참조하는 '지식의 시점'을 고정하여, 결과값의 일관성을 확보합니다.
- **구현 방법:**
    - `Git`은 `.md` 파일의 메타데이터와 구조를 추적.
    - `DVC`는 지식 그래프 추출을 위해 사용된 원본 문서(`PDF`, `이미지`)와 생성된 `임베딩 벡터 파일`을 관리.
    - **근거:** 로컬 SSD에 무거운 벡터 파일이 쌓이면 시스템이 느려집니다. DVC를 통해 필요할 때만 데이터를 캐시하여 SSD 효율성을 최적화합니다.

### 2.1.2 GraphRAG 인덱싱 프로세스

- **단계 1: Ontology Definition (온톨로지 정의)**
    - 에이전트가 정보를 추출할 때 기준이 되는 '카테고리'입니다. (예: `기술`, `인물`, `프로젝트`, `날짜`). 온톨로지 없이 추출하면 노드(Node) 이름이 중구난방이 되어 그래프가 오염됩니다.
- **단계 2: Entity/Relation Extraction (개체-관계 추출)**
    - **도구:** `Qwen-3.6-35B-A3B` (코딩/지식 특화)를 활용해 마크다운 내의 위키링크(`[[Link]]`)를 기반으로 노드와 엣지를 추출합니다.
- **단계 3: Hybrid Indexing (하이브리드 인덱싱)**
    - **Vector Search:** 의미론적 유사도(Semantic Search)를 위해 `ChromaDB` 또는 `FAISS`를 활용(RAM 상주).
    - **Graph Query:** `NetworkX` 혹은 `FalkorDB`를 사용하여 "A가 B의 기술을 사용했다"는 구조적 관계 검색.

## 2.2 LangGraph를 통한 에이전트 워크플로우 제어

사용자의 질문이 들어오면 에이전트는 즉시 대답하지 않고 '연구 계획'을 세웁니다.

- **Workflow Node:**
    1. **Router(라우터):** 질문 분석 ("이 질문은 그래프 탐색이 필요한가, 아니면 단순 벡터 검색인가?").
    2. **GraphQA(그래프 에이전트):** "A와 B의 관계를 찾아라"는 명령을 받아 Cypher 쿼리나 그래프 순회 수행.
    3. **VectorSearch(벡터 에이전트):** "관련된 노트 내용(마크다운 본문)을 찾아라"는 명령 수행.
    4. **Synthesizer(최종 합성 에이전트):** 두 결과를 종합하여 최종 답변 생성.
- **설계 근거:**
    - 질문마다 모든 데이터를 긁어오면 토큰 낭비가 심합니다. **Router가 최적의 경로(Path)만 선택**하게 하여 시스템 효율을 극대화합니다.

## 2.3 실무적 기술 포인트 (Technical Insights)

1. **Semantic Chunking:** 문단 단위가 아니라, 옵시디언의 '헤딩'이나 '위키링크' 단위를 기준으로 청킹(Chunking)하세요. 그래야 맥락이 끊기지 않습니다.
2. **Hashing for Idempotency:** 각 문서의 내용을 `SHA-256` 해싱하여, 변경된 파일만 인덱싱하세요. (전체 인덱싱은 3080 시스템에 엄청난 부하를 줍니다.)
3. **Entity Deduplication (개체 중복 제거):** 'AI'와 'Artificial Intelligence'가 다른 노드로 등록되면 그래프가 무용지물이 됩니다. 추출 시 **엔티티 정규화(Normalization)** 단계를 반드시 거쳐야 합니다.

---

# [Session 3: A2A 통신 규격 및 메시지 브로커 메커니즘]

이 세션은 '에이전트들이 서로의 언어를 어떻게 이해하고, 어떻게 신뢰할 것인가'를 다룹니다. 서로 다른 모델(Qwen, Gemma)이 협업할 때 발생하는 파싱 오류와 데이터 오염을 방지하기 위해 엄격한 프로토콜(Schema)과 **Redis 메시지 브로커**를 통합합니다.

## 3.1 에이전트 간 데이터 규격 (JSON Schema Protocol)

에이전트 간 통신의 핵심은 '구조화된 인터페이스'입니다. 프롬프트 결과값이 줄글(Free-text) 형태라면 시스템은 붕괴합니다.

### 3.1.1 메시지 구조체 (Message Envelope)

모든 에이전트 간 메시지는 반드시 다음의 `Header`와 `Payload`를 포함합니다.

JSON

```json
{
  "header": {
    "message_id": "UUID",
    "timestamp": "ISO8601",
    "sender": "Gemma_LogicAgent",
    "receiver": "Qwen_CoderAgent",
    "task_id": "REQ-001"
  },
  "payload": {
    "intent": "code_generation",
    "context": {
      "entities": ["GraphRAG", "vLLM", "MemoryManagement"],
      "logic_summary": "High efficiency memory allocation using PageAttention"
    },
    "instruction": "Implement a Python class for PagedAttention cache management.",
    "constraints": ["No external libraries besides numpy", "Must include docstrings"]
  }
}
```

- **설계 근거:** `message_id`와 `task_id`를 통해 추적성(Traceability)을 확보합니다. 디버깅 시 특정 태스크가 어느 단계에서 실패했는지 즉시 파악할 수 있습니다.

## 3.2 Redis를 활용한 비동기 메시지 브로커 설계

에이전트 간에 직접 API를 호출하지 않고 Redis의 **List(Queue)** 자료형을 사용하여 **결합도를 낮춥니다(Decoupling).**

### 3.2.1 큐 운영 전략 (Producer-Consumer Pattern)

- **작업 큐 (`task_queue`):** Orchestrator가 분석을 요청하면 Gemma 에이전트가 이를 가져갑니다.
- **결과 큐 (`result_queue`):** Gemma 에이전트가 분석 결과를 출력하면, Qwen 에이전트가 이를 소비하여 코딩을 시작합니다.
- **Redis 명령어 활용:**
    - `RPUSH result_queue [MESSAGE]`: 큐의 오른쪽 끝에 데이터 추가.
    - `BLPOP result_queue 0`: 큐에 데이터가 들어올 때까지 대기(Blocking). **이 과정에서 CPU 점유율을 0%에 가깝게 유지합니다.**

### 3.2.2 장애 격리 및 재시도(Retry) 메커니즘

- **설계 의도:** 특정 에이전트가 모델 응답 생성 중 OOM(Out of Memory)으로 죽었을 때, 시스템 전체가 마비되는 것을 방지합니다.
- **구현:** 에이전트가 작업을 완료하지 못하면 큐에 메시지를 반환(Re-queue)하거나, 별도의 `error_queue`로 이동시켜 관리자가 수동 확인하게 합니다.

## 3.3 에이전트 전문화 구현 (Prompt Engineering + LoRA)

각 모델에게 역할을 부여할 때, 단순 프롬프트만 쓰는 것이 아니라 **시스템 프롬프트와 LoRA 어댑터**를 조합합니다.

- **Gemma_LogicAgent (Analysis):**
    - `System Prompt`: "너는 지식 그래프 분석가야. 주어진 옵시디언 데이터를 기반으로 논리적 관계를 추론하고, 결과를 다음 에이전트가 이해할 수 있는 JSON으로 출력해."
    - **근거:** Gemma 4의 논리 추론 성능을 최대로 활용.
- **Qwen_CoderAgent (Development):**
    - `System Prompt`: "너는 시니어 소프트웨어 엔지니어야. 분석 에이전트가 제공한 JSON의 제약 사항을 준수하며 가장 효율적인 파이썬 코드를 작성해."
    - **근거:** Qwen 3.6의 코드 생성 문법 정합성을 활용.

## 3.4 실무 기술 포인트: "State 관리"

에이전트끼리 대화하다 보면 **'지금 전체 작업이 몇 퍼센트 완료되었는지'** 알기 어렵습니다.

- **Shared State (Redis Hash):** `task_status:{task_id}` 키에 현재 에이전트의 진행 상태(기획 완료, 분석 중, 코드 작성 완료)를 저장합니다.
- **기대 효과:** 오케스트레이터는 이 상태값만 보고 대시보드(Grafana 등)에 전체 에이전트의 진행 상황을 실시간으로 시각화할 수 있습니다.

---

# [Session 4: LangGraph를 활용한 전체 에이전트 파이프라인 통합]

이 세션은 앞서 설계한 인프라(vLLM, Redis)와 지식 파이프라인(GraphRAG)을 하나의 관제탑(Orchestrator)으로 묶는 과정입니다. **LangGraph**는 단순한 선형 파이프라인이 아닌, 에이전트가 상태를 확인하고 필요시 다시 되돌아가 수정하는 '순환형(Cyclic) 워크플로우'를 구현하기 위한 최적의 도구입니다.

## 4.1 LangGraph 기반의 상태 관리 (State Management)

LangGraph는 파이프라인 전체가 공유하는 **`State`** 객체를 정의합니다. 이 상태 객체는 작업의 진행 상황을 투명하게 관리합니다.

Python

```python
from typing import TypedDict, List, Annotated
import operator

# 에이전트 전체가 공유하는 공통 상태 정의
class AgentState(TypedDict):
    task_input: str              # 사용자의 최종 목적
    analysis_result: str         # Gemma의 분석 결과
    generated_code: str          # Qwen의 결과물
    history: Annotated[List[str], operator.add] # 작업 이력 기록
    error_count: int             # 반복 시도 횟수 제한용
```

## 4.2 오케스트레이션 로직 (Workflow Routing)

단순한 흐름이 아니라 '조건부 라우팅(Conditional Routing)'을 통해 지능적으로 에이전트를 운용합니다.

1. **Node: Analysis (Gemma 4)**
    - 입력: `task_input`
    - 동작: 옵시디언 그래프에서 정보를 조회하고, 문제를 해결하기 위한 논리적 구조를 생성.
2. **Node: Coding (Qwen 3.6)**
    - 입력: `analysis_result`
    - 동작: 분석된 구조에 따라 실제 코드 작성.
3. **Conditional Edge (검증 단계)**
    - 코드 작성 후, 시스템은 **'Syntax Check'** 노드를 거칩니다.
    - 코드가 컴파일되지 않거나 로직 오류가 발견되면, **다시 `Analysis` 노드로 메시지를 돌려보냅니다 (Self-Healing).**
    - **근거:** 에이전트가 완벽하지 않기 때문에, 오류를 스스로 인지하고 수정하는 루프를 만들어야 '신뢰성 있는 시스템'이 됩니다.

## 4.3 Redis-LangGraph 연동 (Persistent State)

로컬 환경에서 개발하다가 컴퓨터를 끄더라도, **이전 작업 상태가 날아가면 안 됩니다.**

- **설계 의도:** Redis를 LangGraph의 `Checkpointer`로 사용하여 모든 상태 변화를 메모리에 저장합니다.
- **실무적 이점:**
    - 작업이 중단되어도 `thread_id`만 알면 언제든 마지막 작업 지점에서 재개할 수 있습니다.
    - 면접관이 "장애 발생 시 어떻게 복구하냐?"라고 물으면, "LangGraph의 Redis Checkpointer를 사용하여 상태를 영속화하고, 장애 발생 시 체크포인트에서 트랜잭션을 롤백하거나 재개하는 방식으로 가용성을 확보했다"라고 답변하십시오.

## 4.4 구현 기술: 비동기 실행 (Async Pipeline)

`SGLang`의 비동기 기능을 활용하여 각 에이전트 노드를 실행합니다.

Python

```python
# 예시: LangGraph 에이전트 노드 구현
async def coding_node(state: AgentState):
    # Redis에서 분석 결과를 가져옴
    analysis = state['analysis_result']

    # Qwen 엔진 호출 (SGLang/vLLM)
    code = await call_qwen_coder(analysis)

    return {"generated_code": code, "history": ["Coder completed"]}
```

## 4.5 설계 근거: 왜 LangGraph인가?

1. **순환성(Cycles):** 기존 LangChain 체인은 선형적이지만, 실제 실무는 '코딩 -> 에러 발생 -> 재분석 -> 수정'의 반복입니다. LangGraph는 이 **순환 구조를 가장 직관적으로 구현**합니다.
2. **그래프 시각화:** LangGraph는 내부 워크플로우를 그래프로 시각화할 수 있습니다. 이는 팀원들과 기획을 공유하거나, 시스템의 **데이터 흐름(Data Flow)을 디버깅**할 때 매우 강력합니다.

---

# [Session 5: 실무 적용 - Claude Code 및 파일 시스템 자동화 파이프라인]

마지막 세션입니다. 앞서 구축한 AI 에이전트들이 '가상의 뇌'라면, 이번 세션은 그 뇌가 실제 '손과 발'을 사용하여 당신의 컴퓨터 내 파일을 직접 조작하고, 배포하고, 테스트하는 **엔드-투-엔드(End-to-End) 자동화 단계**입니다.

## 5.1 인프라-코드 연동 (Agent-to-FileSystem)

AI가 코드를 생성한 후, 사람이 직접 복사/붙여넣기를 한다면 그것은 '자동화'가 아닙니다. **Claude Code**와 Cursor(Composer)를 활용하여 이 간극을 없앱니다.

- **실무적 관점:** 우리는 `30_Code` 폴더를 AI의 '작업 공간(Workspace)'으로 선언합니다.
- **Claude Code의 역할:**
    - 터미널에서 `claude --request "Run the newly generated test script"` 명령을 통해, AI가 직접 코드를 실행하고 터미널의 에러 로그(`stderr`)를 읽어 분석하게 합니다.
    - 만약 에러가 발생하면, 그 로그를 다시 [Session 4]의 LangGraph 상태(State)로 피드백하여 "에러 발생: XXX, 다시 분석 후 수정 요망"이라는 루프를 완성합니다.

## 5.2 자동화된 테스트 및 검증 루프

실무 개발에서 가장 중요한 것은 '검증'입니다. 단순히 코드를 짜는 것을 넘어, 테스트 통과를 보장하는 파이프라인을 구축합니다.

1. **Unit Test 기반 검증:**
    - 코딩 에이전트(Qwen)가 코드를 생성할 때, 반드시 `test_*.py` 파일(PyTest 형식)을 함께 생성하도록 강제합니다.
2. **Claude Code의 실행:**
    - Claude Code가 `pytest ./tests/`를 호출합니다.
    - 테스트가 실패하면 Claude Code는 해당 실패 원인을 분석하여 다시 `Qwen`에게 수정 요청(Re-prompt)을 보냅니다.
    - **근거:** "TDD(Test-Driven Development)를 AI 에이전트가 스스로 수행하게 함으로써, 코드의 품질을 인간의 개입 없이 상시 유지"합니다.

## 5.3 프로젝트 배포 및 형상 관리 (Git + DVC)

최종 완성된 코드는 프로젝트의 자산이 되어야 합니다.

- **Git 자동화:**
    - 테스트가 통과되면 Claude Code가 자동으로 `git add .`, `git commit -m "feat: [Agent Generated] <Task_ID>"`를 수행합니다.
- **DVC 데이터 스냅샷:**
    - 학습 데이터나 지식 베이스가 업데이트될 때마다 `dvc push`를 통해 원격 저장소로 데이터를 백업합니다.
    - **설계 근거:** 시스템이 언제든 과거의 안정적인 지식 상태로 롤백할 수 있도록 하여 '데이터 무결성'을 보장합니다.

## 5.4 최종 아키텍처 다이어그램 (요약)

> `[User Input]` → `[LangGraph Orchestrator]`
↓
`[Redis Queue]` → `[Gemma 4 (Analysis)]` → `[Qwen 3.6 (Coding)]`
↓
`[Claude Code (Execute & Test)]` ←(실행 로그 피드백)→ `[File System]`
↓
`[Git/DVC Commit]` → `[Success / Production]`
> 

## [종합: 당신의 MALA 시스템이 완성되었습니다]

이제 당신은 단순한 개발자가 아닙니다. "로컬 GPU 자원을 최적화하고, 멀티 모델을 오케스트레이션하며, 파일 시스템을 직접 조작하는 에이전트 시스템의 아키텍트"가 되었습니다.

### 실무 엔지니어로서의 마지막 조언

이 프로젝트를 면접에서 설명할 때, 다음 3가지 키워드를 강조하세요.

1. **"Resource Efficiency"**: 10GB VRAM 제약을 해결하기 위한 MoE/양자화 전략.
2. **"Reliability"**: Redis 큐와 LangGraph 순환 루프를 통한 시스템의 자동 복구(Self-Healing).
3. **"Reproducibility"**: DVC를 활용한 데이터 버전 관리와 지식 자산화.

---

### [Appendix: SLLM 전문화 모델 및 배치 전략 (2026.05)]

본 아키텍처는 모델의 파라미터 크기보다 '용도별 추론 효율성(Inference Efficiency)'을 우선하여, 10GB VRAM이라는 리소스 제약 안에서 최적의 성능을 내도록 설계되었습니다.

| **역할 (Agent Role)** | **추천 모델 (Model)** | **설계 근거 (Design Rationale)** |
| --- | --- | --- |
| **Logic & Analysis** | **Gemma-4-26B-MoE** | **논리 추론(Reasoning) 최적화.** MoE 구조로 활성 파라미터가 적어 추론 속도가 빠르고, 복잡한 인과관계 분석에 탁월함. |
| **Coding & Refactoring** | **Qwen-3.6-35B-A3B** | **코드 생성 능력(Coding SOTA).** 코드 구조 이해력이 높고, 프로젝트 단위 리팩토링 시 문법 정합성 유지가 가장 뛰어남. |
| **Orchestrator(Router)** | **Qwen-3.6-3B-Instruct** | **초고속 응답(Latency).** 전체 흐름을 제어하는 라우터는 지능보다 속도가 중요하므로, 최소 파라미터 모델을 배치하여 오버헤드 제거. |
| **Test & Validation** | **Mistral-Nemo-12B** | **비판적 사고(Critical Thinking).** 결과물의 오류를 찾는 데 최적화된 학습 데이터 구성을 가지고 있어 디버깅 에이전트로 활용. |

### 엔지니어링 의도 (모델 배치 전략)

1. **MoE(Mixture-of-Experts) 적극 활용:**
    - 3080 10GB 환경에서 Dense(전체 연산) 모델은 14B~20B가 한계지만, MoE 모델은 **'전체 크기는 26B~35B이지만 실제 계산하는 양은 3B~7B'** 수준으로 유지합니다. 덕분에 10GB VRAM 내에서 대규모 지식베이스를 효과적으로 다룰 수 있습니다.
2. **4비트 양자화(Q4_K_M) 표준화:**
    - 위 모델들은 모두 `GGUF` 혹은 `EXL2` 4비트 양자화 포맷을 사용합니다. 이는 모델 품질 저하를 1% 이내로 억제하면서 VRAM 점유량을 극단적으로 낮추는 '로컬 인프라의 필수 전략'입니다.
3. **모델 전환(Model Swapping) 전략:**
    - 단일 VRAM에 모든 모델을 올릴 수 없으므로, **SGLang**의 `Context Switching` 기능을 활용합니다.
    - 분석 에이전트(Gemma)가 끝나면 즉시 해당 가중치를 VRAM에서 내리고, **코딩 에이전트(Qwen)** 가중치를 올리는 방식으로 10GB 환경을 가상적으로 확장합니다.

---

## [최종 추천: 무료 에이전트 스택 (MALA OS)]

| **기능** | **추천 도구** | **역할** |
| --- | --- | --- |
| **인터페이스(UI)** | **Open WebUI** | 지식 저장소(옵시디언)와 대화하는 창구 |
| **에이전트 실행** | **OpenHands** | 터미널에서 코딩, 테스트, 인프라 자동화 수행 |
| **협업 로직** | **CrewAI** | 분석 에이전트와 코딩 에이전트의 업무 분담 |
| **추론 엔진** | **vLLM** | 모든 모델을 서빙하는 고속 엔진 |

### 어떻게 조합할 것인가? (무료 100% 워크플로우)

1. **두뇌:** `vLLM`을 통해 `Qwen 3.6`과 `Gemma 4`를 API 서버로 띄웁니다.
2. **협업:** `CrewAI` 코드로 분석가 에이전트(Gemma)와 개발자 에이전트(Qwen)를 연결합니다.
3. **실행:** `OpenHands`를 통해 에이전트가 직접 내 폴더의 코드를 수정하고 테스트를 돌리게 합니다.
4. **대화:** `Open WebUI`를 통해 내 옵시디언 지식을 기반으로 에이전트들과 대화합니다.

**이 조합이면 유료 서비스 결제 없이도, 당신의 컴퓨터가 하나의 거대한 'AI 사무실'이 됩니다.**

---

### 1. 동일 환경 구축을 위한 3단계 핵심 전략

### ① 도커 이미지의 자산화 (Self-Contained Image)

개별 컨테이너를 일일이 설정하지 마세요. 당신이 구축한 vLLM, Redis, 에이전트 환경을 **하나의 도커 이미지 세트로 빌드**해두어야 합니다.

- **전략:** `Dockerfile`을 작성하여 Python 환경, 의존성 라이브러리, 필요한 모델 구성까지 하나의 이미지로 만드세요.
- **이점:** 어디서든 `docker pull` 한 번이면 당신이 로컬에서 쓰던 그대로의 "AI 사무실"이 복제됩니다.

### ② 환경 설정의 추상화 (Configuration as Code)

회사 PC와 개인 PC는 GPU 성능, RAM 용량, 파일 경로가 다릅니다. 이를 코드가 아닌 **설정 파일**로 분리해야 합니다.

- **전략:** `.env` 파일과 `docker-compose.override.yml`을 활용하세요.
- **이점:** * `docker-compose.yml`: 공통 시스템 구조 정의.
    - `docker-compose.override.yml`: **GPU 사양에 따라 모델 파라미터만 다르게 지정.** (예: 더 좋은 GPU라면 `-gpu-memory-utilization` 값을 0.9로 올림)

### ③ 데이터의 외부화 (Data Persistence)

데이터까지 이미지에 넣으면 너무 무겁습니다. 코드는 이미지로 옮기고, **데이터는 마운트(Mount)** 하세요.

- **전략:** 옵시디언 데이터(지식), DVC 저장소, 모델 파일은 **클라우드 스토리지(S3, HuggingFace Hub 등)나 USB/외장 하드**에 두고, 환경을 옮길 때마다 컨테이너에 해당 경로를 연결(Mount)만 해줍니다.

### 2. "한 줄로 구축"하는 마법의 명령어

이걸 위해 프로젝트 루트에 `setup.sh`라는 스크립트를 하나 만들어 두세요.

Bash

```bash
# setup.sh 예시
echo "로컬 환경 감지..."
# GPU 사양 확인 후 적절한 설정 파일 선택
docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d
echo "AI 사무실 배포 완료!"
```

이 방식은 "코드/설정(Git) + 환경(Docker Image) + 데이터(DVC)"가 분리되어 있어, 어떤 환경에 가더라도 똑같은 기능을 즉시 발휘합니다.

### 3. 실무 엔지니어의 면접용 답변 (포트폴리오 핵심)

면접관이 "환경이 바뀌면 어떻게 대응할 건가요?"라고 물을 때:

> "저는 **인프라의 이식성(Portability)**을 최우선으로 설계했습니다. 시스템의 의존성을 **도커 컨테이너로 표준화**하고, 하드웨어 사양별로 설정을 분리한 **Docker-Compose Override 전략**을 사용합니다. 이를 통해 신규 워크스테이션 도입 시에도 코드 변경 없이 설정 파일 수정만으로 즉시 운영 환경과 동일한 AI 에이전트 인프라를 복제할 수 있습니다."
>
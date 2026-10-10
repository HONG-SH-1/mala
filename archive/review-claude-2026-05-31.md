<!--
  [설계 검토 기록 — Review #3]
  도구: Claude · 날짜: 2026-05-31
  입력: archive/MALA_V2-vision.md §8
  렌즈: "돌아가는 코드에서 추상화를 추출하라"
-->

# Review #3 — Claude — 2026-05-31

> 원문: `클로드.txt` (바탕 화면)

## §8 답변

| # | 의견 | 채택/기각/수정 |
|---|------|----------------|
| 1 | 5모듈 **지금은 과함**. 인터페이스는 **구현 ≥2**일 때만: `LLMProvider`, `ToolRegistry`, `Transport`. `AgentRegistry` → 가벼운 `AgentSpec` dict. **ModalProvider 보류.** OpenHands **기각**, 패턴만 차용. | 수정 |
| 2 | §3C는 **단일 상주 모델 + 노드별 프롬프트**. 가치는 **Critic = reflection 루프**(생성→비판→수정). 모델 스왑 금지. | 채택(수정) |
| 3 | 순서 변경: **3 → 2 → 4 → 1(얇게) → 5**. **6 Modal 스텁 생략.** LLMProvider 1순위는 구현 1개짜리 추상화라 낮음. | 수정(순서) |
| 4 | MCP **데모 1개**. 보안: `.env`+gitignore, 시크릿 로깅 금지, 부수효과 tool→human gate, tool allowlist, PII 마스킹. | 데모 1개 |
| 5 | 스텁 **만들지 말 것**. README 로드맵 한 문장으로 멀티모달 인지만. | 채택(강화) |
| 6 | include·study·출처 **충분**. 추가: ① **retrieval 가시화**(청크 표시) ② **근거 없으면 없다** 가드. | 채택(+2) |
| 7 | 실패1: **추상화 마비**(인터페이스만). Plan B: **수직 E2E 먼저** → 인터페이스 추출. 실패2: JD 10개 얕음. Plan B: **깊게 2개만**(reflection + VRAM ADR). | — |
| 8 | (포폴 한 줄 아래) | — |

## 추가 제안

- **Dogfood 우선** — 매일 쓰는 ②③이 버그를 잡고 ①이 따라옴.
- **추상화는 리팩터링** — 두 번째 구현 생길 때 추출.
- **현실 체크** — V1.5 핵심 2개(reflection + 출처 RAG)면 **지원 가능**. 무한 고도화 회피.

## 포폴 한 줄

> 외부 API 없이 단일 PC(RTX 3080 10GB)에서 도는 플러그형 로컬 멀티에이전트 RAG — Redis 큐 A2A 위에 Researcher·Writer·Critic 역할을 단일 모델 reflection 루프로 구성하고, VRAM 실측으로 모델 동시 상주 한계를 설계 제약(ADR)으로 못박았다. 로컬·API 프로바이더와 MCP 도구를 설정으로 교체 가능.

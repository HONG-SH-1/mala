<!--
  [설계 검토 기록 — Review #3]
  도구: Gemini · 날짜: 2026-05-31
  입력: archive/MALA_V2-vision.md §8
  역할: V1.5/V2 확장 — 플러그·멀티에이전트·AX
-->

# Review #3 — Gemini — 2026-05-31

> 원문: `제미나이 생각.txt` (바탕 화면)

## §8 답변

| # | 의견 | 채택/기각/수정 |
|---|------|----------------|
| 1 | 5모듈 분리 **과하지 않음** (Controller-Service-Repository 치환). **OpenHands SDK 전면 도입 기각** — Redis·LangGraph 내부 통제가 포폴 핵심. **자체 구현 유지.** | 수정안 채택 |
| 2 | 3모델 동시 상주 **불가**, 스왑 I/O 지연. **단일 Hermes/Qwen 8B + 역할 프롬프트(가면) 스왑.** | 수정안 채택 |
| 3 | **1→3→4→5 동의.** 특히 **3 study CLI + Obsidian RAG** = 전 포폴 dogfooding 핵심. | 채택 |
| 4 | MCP **데모 1개**면 충분. **키 관리·마스킹·PII**가 진짜 실력. | 수정안 채택 |
| 5 | **ModalProvider 스텁 100% 동의** — 로컬 영상 X, API 꽂을 수 있는 유연성 어필. | 채택 |
| 6 | include·study·출처 **충분**. 추가: **Obsidian 태그 필터** (`#review_needed` 등)를 `search_vault` 파라미터로. | 수정안 채택 |
| 7 | 리스크: Message History 무한 증가 → Redis·컨텍스트 OOM. Plan B: **Condenser(Summarize) 노드** Supervisor 앞. | 채택 |
| 8 | (포폴 한 줄 아래) | — |

## 추가 제안

- **Human Gate 카오스 테스트:** 위험 tool 대기 시 5분 무응답 → **Deadlock 방지** (Redis TTL / LangGraph timeout → 자동 취소·안전 모드).

## 포폴 한 줄

> 제한된 로컬 자원(10GB VRAM)의 한계를 극복하기 위해, 비동기 메시지 큐(Redis)와 LangGraph 기반의 플러그형 오케스트레이션을 도입하여 결합도를 낮추고 데이터 주권을 확보한 하이브리드 멀티에이전트 시스템을 설계했습니다.

## 다음 검증 제안 (Gemini)

`LLMProvider` 인터페이스 + `.env` Ollama/on-off 스위칭 동작 확인.

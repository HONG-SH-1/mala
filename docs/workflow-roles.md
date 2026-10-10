# MALA — 누가 무엇을 하는지 (2026-05-31)

Review #3 합의 · 도구 역할 정리 (2026-05-31, 클로드 피드백 반영)

---

## 0. 폼팩터 (헷갈리기 쉬운 것)

| 도구 | 형태 | 레포 직접 읽기 |
|------|------|----------------|
| **Cursor** | IDE (VS Code 계열) | ✅ |
| **Claude Code** | **CLI 우선** + VS Code/JetBrains 확장 | ✅ |
| **챗 Claude** | claude.ai **웹 채팅** (Review #3 한 곳) | ❌ (붙여넣기만) |
| **Gemini** | 웹/앱 채팅 | ❌ |
| **Antigravity 2.0** | **IDE + CLI (`agy`)** + SDK | ✅ (별도 워크스페이스 권장) |

> **Review #3의 「클로드」= 챗 Claude** 이지 Claude Code가 아님. 레포 기반 리뷰는 **Claude Code**에게.

---

## 1. 한 장 요약

| 역할 | 담당 |
|------|------|
| **당신** | Obsidian 노트 · dogfood · Redis/Ollama · 최종 채택/기각 |
| **Cursor** | `D:\PersonProject\MALA` **메인 구현·pytest·Windows** |
| **Claude Code** | **레포를 보며** ADR·diff·출처 스키마·Critic stop 등 **구현 결정** |
| **챗 Claude** | 레포 없이 OK — **범위·순서·전략** (과한 추상화? 지원 타이밍?) |
| **Gemini** | 가끔 3차 눈 · 엔터프라이즈( TTL·Condenser·키) |
| **Antigravity** | 무료 티어 **스파이크** — 포폴 요약·Gemini API 실험 (**MALA `src/` X**) |

**운영 규칙:** Cursor ↔ Claude Code ↔ Antigravity — **동시에 같은 파일 수정 금지**. 한 번에 하나만.

### 임계 경로만 (챗 클로드 2026-05-31 — 메타 종료)

| | |
|--|--|
| **코어** | **당신** (Obsidian·dogfood) + **Cursor** (구현) |
| **나중에** | Claude Code — **코드 생긴 뒤** diff·ADR |
| **가끔** | 챗 Claude·Gemini — 범위·전략 (매 단계 X) |
| **나중/선택** | Antigravity — study 출하 **다음** 스파이크 |

도구 다섯 개 **조율**이 또 다른 미니 작업이 되지 않게 — **다음 액션 = Cursor에 study 1단계 구현**.

---

## 2. 당신이 할 일 (직접)

### 매일·매주

1. **Obsidian** `<VAULT_PATH>` — 전 포폴 폴더(예: `06_Portfolio/`)에 `#` `##` `###` 로 노트 작성  
2. 노트 추가 후: `python -m src.scripts.build_index`  
3. 터미널 A: `python -m src.worker`  
4. **study**로 질문하며 복습 (구현 후)  
5. 답이 틀리면 → **노트 수정** → 다시 `build_index` (dogfood)

### 가끔

- Redis·Ollama 켜져 있는지 확인  
- `.env`에 `OBSIDIAN_VAULT_PATH`, (후) `OBSIDIAN_INCLUDE`  
- **지원 타이밍:** study 출처 + reflection **동작**하면 지원 시작해도 됨 (클로드) — #4~7은 병행 폴리싱

### 하지 않음

- OpenHands로 MALA 통째 교체  
- 3080에서 로컬 영상 모델

---

## 3. Cursor에게 시킬 일 (복붙용)

### 지금 1차 (클로드·제미나이 합의 — **코어 3개만**)

```
MALA V1.5 1단계만 구현해줘 (docs/archive/MALA_V2-vision.md §6, review-claude-2026-05-31):

1) study CLI — vault 질문 시 항상 RAG (키워드 불필요)
2) OBSIDIAN_INCLUDE — 특정 폴더만 인덱스/검색
3) 답변에 출처 — 파일명 + ## 헤딩

제미나이 피드백:
- Rich UI 말고 데이터 플로우만
- 쿼리 전 structured log: 포함/제외 파일 수 (silent drop 방지)

pytest 포함. .env.example 갱신.
```

### 1단계 다음 (얇게 쌓기)

```
1b) retrieval hits를 응답에 표시 (몇 건, 어떤 청크)
1c) 근거 없으면 "모름" 가드
1d) search_vault 태그 필터 (#태그)
```

### 2~3단계 (코어 돌아간 뒤)

```
2) ToolRegistry + MCP 데모 1개 (filesystem 등)
3) LangGraph Researcher→Writer→Critic reflection, 단일 Ollama 8B
```

### 문서만

```
docs/demo.md 30초 스크립트, README 포폴 한 줄 (review-claude 포폴 문장)
```

---

## 4. Claude Code vs 챗 Claude

### Claude Code (터미널·IDE — **레포 접근**)

**시킬 때**

- `MALA` 폴더 열고 `src/agents/`, `study` 구현 **diff 리뷰**  
- **결정 포인트** — 출처 메타데이터를 Chroma metadata에 넣을지, Critic max round 등  
- ADR 초안 `docs/decisions/004-study-citations.md`  
- pytest 실패 로그 + 파일 경로 붙여 **원인 분석**

**예시 프롬프트**

```
D:\PersonProject\MALA 레포 기준으로 study CLI 설계 검토해줘.
출처는 chunk metadata에 source/heading 넣는 게 나을지, 답변 후처리인지 ADR 초안으로.
```

**금지:** Cursor가 `src/` 수정 중일 때 Claude Code도 같은 파일 편집.

### 챗 Claude (claude.ai — **레포 없음**, Review #3)

**시킬 때**

- `MALA_V2-vision.md` **요약 붙여넣기** → 범위·우선순위·포폴 문장  
- 「1단계에 기능 6개 넣으면 과한가?」 같은 **상위 판단**  
- 커리어·지원 타이밍

**시키지 말 때**

- 「`src/config.py` 47줄 봐줘」 → **Claude Code 또는 Cursor**

---

## 5. Gemini 역할

- **Review #3**처럼 브리프 통째 리뷰 (`MALA_V2-vision.md`)  
- 엔터프라이즈 톤: Human gate TTL, Condenser, 키/PII  
- Obsidian **태그·폴더** 전략

**Antigravity와 구분:** Gemini **웹/앱 채팅** = 짧은 리뷰. Antigravity = **에이전트 IDE/CLI**.

---

## 6. Antigravity (무료 티어) — IDE **및** CLI

Google **Antigravity 2.0** (2026-05) — **데스크톱 IDE · CLI `agy` · SDK** (Gemini CLI 대체 방향). 무료 티어는 레이트 리밋 있음.  
**MALA `src/` 메인 개발 = Cursor.** Antigravity는 **다른 폴더**에서 스파이크 권장.

| Antigravity에 맡기기 좋음 | Cursor에 맡기기 좋음 |
|---------------------------|----------------------|
| 전 포폴 **요약 초안** → Obsidian에 붙여넣기 전 검토 | `src/` Python 전부 |
| Gemini API **스파이크** (Veo 문서 읽고 샘플 1스크립트) | `pytest`, `worker`, Windows 경로 |
| README·이력서 **문장 다듬기** | Chroma·인덱스·study CLI |
| 다른 레포/샘플 **병렬** 실험 | `.env`, Ollama D: 드라이브 이슈 |

**설치 (Windows, 참고):** 공식 CLI — `irm https://antigravity.google/cli/install.ps1 | iex` 후 `agy`  
(Gemini CLI는 2026-06-18 전후 마이그레이션 권고 — Antigravity 쪽 문서 참고)

**금지 패턴:** Antigravity와 Cursor가 **동시에** `MALA/src` 수정.

---

## 7. 구현 순서 (최종)

```
[당신]     Obsidian 전 포폴 노트 시작
[Cursor]   study + include + 출처 (+ 인덱스 observability 로그)
[당신]     build_index → worker → study dogfood
[Cursor]   retrieval 표시 · 근거 가드 · 태그 (1b~1d)
[Claude Code] (선택) 구현 후 diff · 출처 스키마 / Critic stop ADR
[챗 Claude] (선택) 범위·지원 타이밍만 — 레포 붙여넣기
[Cursor]   ToolRegistry + MCP 데모
[Cursor]   reflection 3노드
[당신+Cursor] demo · README · (지원)
[병행]     Antigravity: 포폴 요약 초안 / Gemini API 트라이
```

---

## 8. 관련 문서

- [`archive/MALA_V2-vision.md`](../archive/MALA_V2-vision.md) §6·§8  
- [`design-process.md`](design-process.md)  
- [`archive/review-claude-2026-05-31.md`](../archive/review-claude-2026-05-31.md)  
- [`archive/review-claude-advice-2026-05-31.md`](../archive/review-claude-advice-2026-05-31.md) (운영·메타 종료)  
- [`archive/review-gemini-2026-05-31.md`](../archive/review-gemini-2026-05-31.md)

---

## 9. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-05-31 | 초안 |
| 2026-05-31 | 클로드 피드백 — **챗 Claude ≠ Claude Code**, Antigravity IDE+CLI |

# MALA 작업 규칙 (Claude Code용)

## 프로젝트

- 로컬 지식 비서. Obsidian 노트를 검색해 답하고, 앞으로 에이전트 하나에 스킬을 붙여 넓혀 간다.
- 환경: Windows 데스크톱, RTX 3080 10GB, RAM 32GB. BIOS에서 가상화가 막혀 Docker와 WSL2는 쓸 수 없다.
- 구성: Ollama(`127.0.0.1:11434`), Redis(윈도우용 5.x, `localhost:6379`), LangGraph, Chroma.
- 먼저 볼 문서: `README.md`, `docs/architecture.md`, 결함 목록 `docs/study/fix-later.md`, 결정 기록 `docs/decisions/`.

## 환경 명령 (PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"          # 한글 출력 깨짐 방지
python -m pytest -q             # Ollama와 Redis 없이도 통과해야 함
D:\Redis\redis-cli.exe ping     # PONG
ollama list                     # qwen3:8b, nomic-embed-text 있어야 함
```

## 지금 단계: 0단계 기준선

- 기준선을 재기 전까지 `src/`의 기존 파일은 고치지 않는다. 측정 도구(`src/eval/`, `src/scripts/eval_run.py`)도 기준선을 잰 뒤에 고친다.
- 측정 순서: `python -m src.scripts.eval_run --dry-run` → `python -m src.scripts.build_index` → `python -m src.scripts.eval_run --label baseline --repeat 2`
- 결과는 `data/eval/`에 `.md`와 `.jsonl`로 남는다. 숫자를 해석하기 전에 `.md`를 그대로 보여준다.

## 작업 규칙

- 파일 수정, 패키지 설치, 커밋은 계획을 먼저 보여주고 승인을 받은 뒤 한다. push는 사용자가 직접 한다.
- 수치는 실제 실행 결과에 있는 것만 쓴다. 재지 않은 값은 쓰지 않고, 모르면 모른다고 한다.
- 결정은 `docs/decisions/`에 ADR로, 진행은 `docs/development-log.md`에 남긴다.
- 테스트가 통과한 것과 실제로 동작하는 것은 다르다. 실제 Ollama와 Redis로 한 번 돌려 본 뒤에 "된다"고 말한다.

## 데이터 규칙

- `.env`, `data/`, `eval/questions.yaml`은 git에 올리지 않는다 (`.gitignore`에 있음).
- 볼트 노트 원문은 외부 무료 API로 보내지 않는다.
- API 키와 토큰은 코드, 로그, 커밋, 이 파일에 넣지 않는다.

## 답하는 방식

- 한국어, 쉬운 말, 결론 먼저.
- 코드를 바꿀 때는 왜 그렇게 바꾸는지 한두 문장으로 설명한다. 사용자가 공부하면서 진행하는 프로젝트다.

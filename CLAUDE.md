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

## 지금 단계: 1단계 검색 개선 실험

- 기준선 (질문 라벨 v2, 평가 대상은 ADR-004):
  - 답변: `eval/results/20261028-2205_baseline-docs_rescored-v2.md`
  - 검색: `eval/results/20261029-2116_ret-v2-k3-keyword.md` (`--retrieval-only`)
- 질문 라벨은 1단계 실험 중에 바꾸지 않는다.
- 기본 동작은 그대로 둔다. 새 동작은 환경변수 스위치로만 켜고, 끄면 기준선과 같은 동작이어야 한다.
- 기준선과 비교할 때는 `eval/env_docs.ps1` 설정을 그대로 쓴다. 명령마다 같은 줄에서 불러온다.
  `. .\eval\env_docs.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --label <이름> --repeat 2`
- 색인을 바꾸는 실험(임베딩 등)은 평가 전용 색인을 새로 만든 뒤 잰다.
- 결과는 `data/eval/`에 `.md`와 `.jsonl`로 남는다. 숫자를 해석하기 전에 `.md`를 그대로 보여준다. 남길 결과는 `eval/results/`로 옮긴다.
- 판정 규칙이나 질문 출처가 바뀌면 `src.scripts.eval_rescore`로 기준선도 다시 채점해 같은 잣대로 비교한다.

## 작업 규칙

- 파일 수정, 패키지 설치, 커밋은 계획을 먼저 보여주고 승인을 받은 뒤 한다. push는 사용자가 직접 한다.
- 수치는 실제 실행 결과에 있는 것만 쓴다. 재지 않은 값은 쓰지 않고, 모르면 모른다고 한다.
- 결정은 `docs/decisions/`에 ADR로, 진행은 `docs/development-log.md`에 남긴다.
- 테스트가 통과한 것과 실제로 동작하는 것은 다르다. 실제 Ollama와 Redis로 한 번 돌려 본 뒤에 "된다"고 말한다.

## 데이터 규칙

- `.env`, `data/`는 git에 올리지 않는다 (`.gitignore`에 있음). `eval/`의 질문과 결과는 공개 docs 기준이라 올린다.
- 볼트 노트 원문은 외부 무료 API로 보내지 않는다.
- API 키와 토큰은 코드, 로그, 커밋, 이 파일에 넣지 않는다.

## 답하는 방식

- 한국어, 쉬운 말, 결론 먼저.
- 코드를 바꿀 때는 왜 그렇게 바꾸는지 한두 문장으로 설명한다. 사용자가 공부하면서 진행하는 프로젝트다.

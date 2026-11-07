# 평가 (0단계 기준선)

지금 코드를 고치기 전에 한 번 재 두고, 이후 무엇을 바꾸든 같은 질문으로 다시 잽니다.
기존 `src` 코드는 건드리지 않고, Ollama 호출만 바깥에서 감싸 시간과 토큰을 기록합니다.

## 질문 파일

`questions.yaml`은 공개 `docs/` 사본을 기준으로 쓴 질문이라 git에 올립니다.
`questions.example.yaml`은 형식 예시입니다. 개인 볼트로 질문을 만들면 내용이 노트에서 나오므로 git에 올리지 않습니다.

권장 구성은 20개입니다. 노트에 답이 있는 질문 15개, 노트에 없는 질문 5개입니다.
노트에 없는 질문은 "모른다"고 답해야 정답입니다.

## 라벨 판

지금 질문 파일은 **라벨 v2**(2026-10-29)입니다. 1단계 실험 중에는 라벨을 바꾸지 않습니다.

- `expected_sources`: 답이 그 줄에 직접 있는 문서만 넣습니다. 링크나 언급만 있는 문서는 뺍니다.
- `must_include`: 항목은 모두 있어야 합니다. 항목이 목록이면 그중 하나만 있으면 됩니다 (같은 뜻의 다른 표기). 자동 판정과 근거 청크 판정에 똑같이 씁니다.

```yaml
must_include: [["7559", "7,559"]]      # 항목 1개, 표기 2개
must_include: ["retrieve", "validate"] # 항목 2개
```

- v1과 차이: q01~q05, q07, q09, q10 기대 출처 추가, q04·q07·q08 다른 표기 추가. v1 파일은 커밋 4695824에 있습니다.
- 결과 `.md` 머리에 질문 파일 sha256 앞 8자리가 찍힙니다. v2는 `68e6aebc`입니다.
- 라벨을 바꾸면 기준선도 재채점합니다 (`--suffix _rescored-v2`처럼 이전 결과를 덮어쓰지 않게).

## 평가 대상 (docs 고정 사본)

기준선은 레포 `docs/`를 고정 복사한 `data/eval_corpus/docs-20261028/`로 잽니다.
사본은 2e55c5b 시점의 docs/에서 만든다 (`data/`는 git에 없으므로 다른 PC에서는 이 커밋에서 다시 복사).
`.env`는 그대로 두고, 평가 전용 환경변수는 `eval/env_docs.ps1`에 모아 둡니다.
답변 모델, 임베딩 모델, `GRAPH_MAX_RETRIES`, `RAG_TOP_K`, `RAG_RERANK`도 여기서 정합니다. 기준선 때 쓰인 값을 적은 것이라 동작은 같습니다. `.env`가 바뀌어도 기준선 조건은 그대로 남습니다.
기존 `mala_vault` 색인과 `data/index_manifest.json`은 쓰지 않습니다.

- 레포 루트(`D:\PersonProject\MALA`)에서 실행합니다 (`CHROMA_PERSIST_DIR`가 실행 위치 기준).
- 명령마다 같은 줄에서 스크립트를 불러옵니다. 창이 바뀌면 환경변수가 사라져 `.env`의 원래 볼트로 색인될 수 있습니다.
- 실행 전에 설정값이 평가 전용인지 먼저 확인합니다.

```powershell
. .\eval\env_docs.ps1; python -c "from src.config import get_settings as g; s=g(); print(s.obsidian_vault_path, s.chroma_persist_dir, s.chroma_collection, s.index_manifest_path, s.index_failures_path)"
. .\eval\env_docs.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --dry-run
. .\eval\env_docs.ps1; python -m src.scripts.build_index
. .\eval\env_docs.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --label baseline-docs --repeat 2
```

다시 잴 때도 같은 스크립트를 씁니다. 평가 대상 문서나 스크립트 값을 바꾸면 새 기준선입니다.

## 실행

```powershell
# 노트북에서도 가능: 질문 파일 형식과 노트 경로만 검사
python -m src.scripts.eval_run --questions eval/questions.yaml --dry-run

# 데스크톱: Redis와 Ollama를 켠 상태에서, 색인이 되어 있어야 함
python -m src.scripts.eval_run --questions eval/questions.yaml --label baseline --repeat 2
```

결과는 `data/eval/<날짜-시각>_<label>.jsonl`과 `.md`로 남습니다.
경로는 `study_once --inline`과 같습니다(항상 노트 검색, worker 없이 직접 호출).

## 검색만 재기

답변 모델과 Redis 없이 검색만 잽니다. 질문 임베딩 때문에 Ollama는 켜져 있어야 합니다.
in_notes 질문만 1회 돕니다 (기준선에서 1·2회차 검색 결과가 같았음).

```powershell
. .\eval\env_docs.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --retrieval-only --label ret-k3-keyword
. .\eval\env_docs.ps1; $env:RAG_TOP_K = "5"; $env:RAG_RERANK = "off"; python -m src.scripts.eval_run --questions eval/questions.yaml --retrieval-only --label ret-k5-off
```

| 지표 | 어떻게 |
| --- | --- |
| 답 근거 청크 포함률 (기대 출처, 주 지표) | 기대 출처 파일의 청크 하나에 `must_include`가 다 있는지 |
| 답 근거 청크 포함률 (아무 청크) | 아무 청크 하나에 `must_include`가 다 있는지. 흔한 단어는 상관없는 청크에도 나와 부풀 수 있음 |
| 출처 일치율 | 파일 단위. 제목만 있는 청크를 가져와도 맞다고 셈 |
| 200자 미만 청크 비율 | 가져온 청크 중 짧은 청크 |

판정은 프롬프트에 실제로 들어가는 글(`format_context`, 본문 1200자까지)로 합니다.
`RAG_RERANK`는 `keyword`(기본, 지금 동작)와 `off`(벡터 거리순 그대로)입니다.

## 임베딩 접두어 실험 (`env_docs_prefix.ps1`)

`EMBED_PREFIX=nomic`이면 색인할 때 `search_document: `, 검색할 때 `search_query: `를 붙입니다. 2026-11-01부터 기본값은 `nomic`입니다 ([ADR-005](../docs/decisions/005-embed-prefix-default.md)). `off`는 아무것도 안 붙이는 10-28 기준선 동작입니다.
벡터가 달라지므로 색인을 따로 만듭니다. `eval/env_docs_prefix.ps1`은 `env_docs.ps1`을 불러온 뒤 바뀌는 값만 덮어씁니다.

| 값 | 10-28 기준선 재현 (`env_docs.ps1`, off) | 접두어, 1단계 비교 기준 (`env_docs_prefix.ps1`) |
| --- | --- | --- |
| `CHROMA_COLLECTION` | `mala_eval_docs` | `mala_eval_docs_prefix` |
| `INDEX_MANIFEST_PATH` | `data/eval_manifest_docs.json` | `data/eval_manifest_docs_prefix.json` |
| `INDEX_FAILURES_PATH` | `data/eval_index_failures.jsonl` | `data/eval_index_failures_prefix.jsonl` |
| `EMBED_PREFIX` | `off` | `nomic` |

매니페스트를 같이 쓰면 증분 색인이 "바뀐 것 없음"으로 보고 건너뜁니다. 그래서 매니페스트도 따로 둡니다.
접두어 방식이 다른 컬렉션을 열면 오류가 납니다. 예를 들어 `env_docs.ps1`로 `mala_eval_docs_prefix`를 열면 막힙니다.

```powershell
. .\eval\env_docs_prefix.ps1; python -m src.scripts.build_index
. .\eval\env_docs_prefix.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --retrieval-only --label ret-v2-k3-keyword-prefix
. .\eval\env_docs_prefix.ps1; $env:RAG_RERANK = "off"; python -m src.scripts.eval_run --questions eval/questions.yaml --retrieval-only --label ret-v2-k3-off-prefix
. .\eval\env_docs_prefix.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --label <이름> --repeat 2
```

결과 머리의 `임베딩 접두어:` 칸으로 어느 쪽으로 쟀는지 확인합니다.

## 재는 것

| 지표 | 어떻게 |
| --- | --- |
| 정답률 | `must_include` 단어가 답에 전부 있으면 정답. 노트에 없는 질문은 "모른다" 표현이 있으면 정답 |
| 출처 일치율 | `expected_sources` 노트가 검색 결과에 들어왔는지 |
| 응답 시간 | 질문 하나를 보내고 답을 받을 때까지 |
| 토큰 | Ollama가 돌려주는 입력(prompt_eval_count)과 출력(eval_count) |
| 재시도 | 검증에 걸려 Ollama를 두 번 이상 부른 질문 수 |
| 흔들림 | `--repeat 2` 이상일 때, 같은 질문의 판정과 답이 같은지 |

첫 문항은 모델 로드 시간이 섞일 수 있어 `load_ms`를 따로 남깁니다.

## 판정과 재채점

자동 판정은 키워드 기준이라 거칩니다. 사람이 볼 때 규칙은 이렇습니다.

- in_notes: 키워드가 있어도 결론이 "모른다/확인할 수 없다"면 X.
- not_in_notes: 문서에 없는 값을 실측처럼 말하면 X.

사람 판정은 결과 jsonl을 고치지 않고 따로 `<결과 이름>.manual.yaml`에 적습니다.

```yaml
q08: true            # 전 회차
q18: [true, false]   # 회차별 (1회차, 2회차)
```

질문 파일이나 사람 판정이 바뀌면 모델을 다시 돌리지 않고 재채점합니다.
`source_hit`, `auto_correct`를 다시 계산하고, 사람 판정이 있으면 그것을 최종 판정으로 씁니다.

```powershell
python -m src.scripts.eval_rescore eval/results/20261028-2205_baseline-docs.jsonl `
    --questions eval/questions.yaml `
    --manual eval/results/20261028-2205_baseline-docs.manual.yaml
```

원래 jsonl은 그대로 두고 같은 폴더에 `_rescored.jsonl`, `_rescored.md`를 씁니다.

## 면접관 자동화 (보조 도구)

`_rescored-v2.jsonl`의 답을 면접관 3명(Claude haiku, Codex, Gemini)이 판정한다. 공식 판정이 아니라 사람 판정을 돕는 참고용이다.
결과는 `data/eval/judge/<실행>/`에 남는다 (git 제외). `.env`에 `MALA_KDBX_PATH`, `KEEPASSXC_CLI`, `CODEX_JUDGE_MODELS`, `CODEX_JUDGE_EFFORT`, `GEMINI_JUDGE_MODELS`가 필요하다 (`.env.example` 참고). Gemini 키는 `.env`가 아니라 KeePassXC 금고의 `mala-gemini` 항목에만 둔다.

```powershell
# 첫 실행: 세 결과에서 골고루 10건 (Codex 월 한도 가늠). 금고 암호는 시작할 때 한 번 직접 입력한다.
python -m src.scripts.eval_judge <A_rescored-v2.jsonl> <B_rescored-v2.jsonl> <C_rescored-v2.jsonl> --judges claude,codex,gemini --limit 10 --tag first10
# 판정 불가 건만 같은 모델로 다시
python -m src.scripts.eval_judge --resume data/eval/judge/<실행폴더>
```

- 출력: `judge_<면접관>.jsonl`, `majority.jsonl`, `review.md`(사람이 볼 목록, 결과 이름을 가림), `blind_map.json`(번호 대응, 판정 후에 열기), `summary.md`, `retries.log`, `run.json`.
- Codex, Gemini는 시작 때 첫 모델에 확인 요청을 보내 되는 모델 하나로 그 실행 전체를 고정한다. 건마다 실제로 쓴 모델 이름이 판정 파일에 남는다.
- **안전장치**: 입력 결과의 컬렉션이 `mala_eval_docs`로 시작하는 공개 문서 컬렉션일 때만 codex, gemini를 쓴다. 그 밖의 이름이나 알 수 없으면 거부한다 (`claude`만 가능). 컬렉션 이름은 결과 `.jsonl`이 아니라 짝이 되는 원래 `.md`의 "컬렉션:" 줄에 있다. 10-28 기준선 `baseline-docs`의 `.md`에는 이 줄이 없어서, 사후 확인한 이름을 `eval/results/source_overrides.yaml`에 따로 적었다. 검사는 `.md`에 컬렉션 줄이 없을 때만 이 파일을 보고, 거기 적힌 이름에도 같은 허용 목록 규칙을 적용한다. 이 파일은 레포의 `eval/results/source_overrides.yaml` 한 곳에서만 읽고, 입력 파일이 `eval/results/` 안에 있을 때만 적용한다 (입력 파일 옆 폴더는 보지 않는다). 같은 키가 두 번 있으면 파일 전체를 거부한다. 원래 `.md`는 고치지 않는다.
- 번호: 새 실행은 모든 건에 `B001` 형식 번호를 붙여 `blind_map.json`에 저장한다. 이미 있는 번호는 바뀌지 않고, 번호가 없는 건에만 이어서 붙는다 (예전 실행의 `#01`도 그대로).
- 진행 표시: 켜진 면접관이 모두 마친 건마다 `[37/120] B012 q07 2회차 — claude 합격, codex 합격, gemini 불합격 (갈림)` 한 줄, 30초마다 면접관별 진행·건당 평균·남은 예상 한 줄. 시작할 때 이전 실행의 건당 시간으로 예상을 먼저 보여 준다. `--blind`면 판정과 (갈림)을 숨긴다. 답 본문과 이유는 찍지 않는다.
- `summary.md`에 회차별 일치율 표, `human.jsonl`이 있으면 사람 판정과의 일치율이 들어간다.
- 사람 판정은 저장하는 순간 면접관 판정이 가려져 있었는지(`blind`)를 같이 기록한다. 사람 판정과의 일치율은 `blind=true`만으로 계산하고, 면접관 판정을 본 뒤에 저장한 판정(`blind=false`)은 "임원 판정"으로 개수와 목록만 따로 보여 준다.
- 다시 저장할 때: 이미 블라인드로 저장한 건은 판정(합격/불합격/보류)이 그대로면 `blind`를 유지하고(이유 글만 고친 경우), 판정이 바뀌면 `false`가 된다. 한 번 `false`가 된 건은 판정을 되돌려도 `true`로 돌아오지 않는다. `blind` 필드가 없는 예전 파일이나 저장분은 `false`로 본다.
- `blind`는 사람이 스스로 남기는 기록이다. 내보낸 JSON이나 `human.jsonl`을 고치면 값이 바뀔 수 있고, 도구는 그것을 확인할 수 없다. 일치율의 신뢰는 기록을 정직하게 남긴다는 전제 위에 있다.
- 판정 파일 안전: `run.json`, `blind_map.json`, `inputs.json`은 임시 파일에 쓴 뒤 `os.replace`로 바꿔 끼운다. `--resume`은 먼저 `judge_*.jsonl`을 기준으로 상태를 맞춘다 (같은 건이 두 번이면 마지막 줄만 남김, 깨진 줄은 버림, 상태엔 끝났는데 판정이 없으면 다시 판정). 맞춘 건수는 `summary.md`에 남는다.
- Codex는 호출마다 작업 폴더에 겹치지 않는 새 출력 파일을 만들고 끝나면 지운다. 이번 호출에서 새로 써지지 않았거나 비어 있으면 판정 불가로 센다.
- 면접관 프롬프트는 답을 호출을 만들 때마다 바뀌는 무작위 구분자(`ANSWER-<16자리 16진수>`)로 감싼다. 답 안에 `</answer>` 같은 글이 있어도 경계를 닫지 못한다.
- Ctrl+C를 누르면 실행 중인 claude, codex 자식 프로세스에 종료를 요청하고, 3초 안에 안 끝나면 강제 종료한다. 중단 때문에 난 실패는 판정 파일에 기록하지 않는다.
- `--import-human`은 내보낸 파일의 `run` 이름이 대상 폴더와 다르거나, 한 파일 안에 같은 번호가 두 번 있으면 아무것도 쓰지 않고 거부한다.
- 금고 조회(`keystore`)는 항목 이름을 영문·숫자·점·밑줄·하이픈으로만 받고 하이픈으로 시작하면 거부한다. `KEEPASSXC_CLI`는 `keepassxc-cli.exe`의 절대 경로여야 하고, 위치 인자 앞에 `--`를 넣는다. `httpx`, `httpcore` 로그는 WARNING 이상으로 고정해 요청 주소가 로그에 남지 않게 한다.

### 결과 보기 화면 (`review.html`)

실행이 끝나거나 중단되면 실행 폴더에 `review.html` 하나가 생긴다. 파일을 더블클릭해 브라우저로 열면 된다 (서버, 포트, 외부 요청 없음, 데이터는 파일 안에 들어 있다).

- **내 판정 모드**: 사람이 볼 건을 한 건씩, 고정 시드로 섞은 순서로 보여 준다. 합격·불합격·보류와 한 줄 이유를 저장해야 그 건의 면접관 판정, 다수결, 최종 판정, 볼 이유가 보인다. 판정은 브라우저 `localStorage`(키: 실행 폴더 이름)에 자동 저장되어 창을 닫았다 열어도 이어서 할 수 있다.
- **보기 모드**: 질문, 회차로 묶어 보여 주고 묶음 안의 세 답 순서는 묶음마다 섞는다. 필터는 사람이 볼 건 / 의견이 갈린 건 / 최종과 다른 건 / 면접관별. 내 판정 전의 건은 갈림, 최종과 다름, 면접관별 필터에 걸리지 않고 항상 보인다.
- 어느 결과(기준선, 대조군, 접두어)인지와 `blind_map` 내용은 화면에 없다. 같은 질문, 회차의 세 답은 글투로 짐작될 수는 있다.
- **내보내기** 버튼 → `human-<실행폴더>.json` 다운로드 (안 되면 화면 아래 텍스트 상자를 복사). 합치기:

```powershell
python -m src.scripts.eval_judge --import-human data/eval/judge/<실행폴더> human-<실행폴더>.json
python -m src.scripts.eval_judge --rebuild data/eval/judge/<실행폴더>   # 판정 호출 없이 화면, 요약 다시 만들기
```

### 판정 기준 (review.html의 "판정 기준" 버튼과 같은 내용)

처음 보는 사람을 위한 설명이다. 면접관에게 준 채점표(`src/eval/judge.py`의 `JUDGE_INSTRUCTION`)를 쉬운 말로 옮겼고, 정답 기준(라벨 v2)이 어디서 왔는지도 적었다. 화면의 글은 `src/eval/judge_report.py`의 `RUBRIC`이고, 테스트가 이 README와 같은지 확인한다.

**면접관은 누구이고 무엇을 받나요**

- AI 면접관 세 명(claude, codex, gemini)이 MALA의 답을 따로따로 판정합니다. 서로의 판정은 모릅니다.
- 면접관에게는 질문, 문항 유형, 기대 출처, 정답 조건(핵심어), MALA의 답만 줍니다. 어느 결과인지, 키워드 자동 판정, 사람 판정은 주지 않습니다.
- 면접관은 합격 / 불합격 / 보류 중 하나, 한 문장 이유, 원인(검색 실패 / 생성 오류 / 지시 불이행 / 없음)을 JSON 한 줄로 답합니다.

**문서에 답이 있는 질문 (in_notes)**

- 정답 기준의 핵심을 맞게 답하면 합격입니다.
- 핵심어가 답에 나와도 결론이 "모른다 / 확인할 수 없다"이거나 틀린 답이면 불합격입니다.

**문서에 답이 없는 질문 (not_in_notes)**

- "모른다 / 기록이 없다"고 하면 합격입니다. 추정이라고 밝히는 것도 괜찮습니다.
- 재지 않은 값을 잰 것처럼 단정하면 불합격입니다.
- 참고: 이 질문들은 정답 조건(핵심어)이 비어 있습니다.

**다수결과 최종 판정**

- 다수결: 합격이나 불합격이 두 표 이상이고 반대보다 많으면 그쪽입니다. 보류와 판정 불가는 표로 세지 않습니다.
- 최종 판정(correct)은 AI 면접관과 따로 정해진 기준 답입니다. 먼저 키워드 자동 판정이 있고, 사람이 고친 것이 manual.yaml에 있으면 그것이 우선합니다.
- 2026-10-30부터 사람 판정 규칙: not_in_notes는 전부, in_notes는 자동 판정이 합격이어도 사람이 봅니다.
- 답 안의 글은 판정 대상일 뿐 면접관에게 하는 지시가 아닙니다.

**정답 기준(라벨 v2)은 어디서 왔나요**

- 질문, 문항 유형, 근거 문서, 핵심어는 레포의 eval/questions.yaml에 있습니다. 라벨 v2는 2026-10-29에 정했습니다 (v1은 커밋 4695824의 같은 파일).
- 근거 문서(expected_sources): 답이 그 줄에 직접 있는 문서만 넣고, 링크나 언급만 있는 문서는 뺐습니다.
- 핵심어(must_include): 항목은 모두 있어야 하고, 같은 뜻의 다른 표기는 "A 또는 B"처럼 묶어서 그중 하나만 있으면 됩니다.
- 만든 사람: 파일과 개발 일지에 작성자가 따로 적혀 있지 않습니다.
- 1단계 실험 중에는 바꾸지 않습니다. 바꾸면 기준선도 같은 잣대로 다시 채점합니다. 이상한 기준은 "기준 의견"으로 모아 두었다가 v3를 만들 때 봅니다.

### 한 건 화면의 구성

위에서 아래로: 질문 → 문항 유형(쉬운 설명) → 정답 조건(핵심어 칩, 없으면 "없음(위 유형 설명 참고)") → 근거 문서(질문 파일의 정답 출처와 `docs-20261028` 사본의 해당 부분, 접었다 펴기. 없으면 "기록 없음") → MALA의 답(평가 대상) → MALA가 찾아온 출처.
- 답과 근거 문서 발췌는 작은 마크다운 변환기로 보여 준다: 제목(#, ##, ###)은 굵은 제목, 표는 표(머리줄과 구분줄이 있을 때만), 인용(>)은 흐린 상자, 링크 `[글](주소)`는 글만 보이고 주소는 흐리게, 구분선(---)은 선, 체크 목록 `- [x]`는 ✓(`- [ ]`는 ☐), **굵게**, `코드`, 목록, 들여쓰기, 줄바꿈, 코드 블록. 발췌가 표 중간에서 잘려 머리줄이 없으면 그 부분만 글자 그대로 보이고, 지원 안 하는 문법도 글자 그대로다. 답과 발췌 모두 "원문 보기"로 원문을 볼 수 있다.
- 정답 조건(must_include)의 핵심어가 답과 근거 문서 발췌에 나오는 자리는 형광펜(`<span class="hl">`, 글자는 `textContent`)으로 표시하고, 근거 문서 칸 맨 위에 문서마다 "핵심어가 나오는 줄"을 한두 줄 먼저 보여 준다. HTML로 해석하지 않고 `createElement`와 `textContent`로만 그린다 (`src/eval/md_mini.py`가 같은 규칙의 기준 구현, `tests/test_md_mini.py`가 비교).
- "내 판정" 아래에 **기준 의견**이 따로 있다: "이 기준이 이상함" 체크와 한 줄 메모. 판정과 섞지 않고 내보내기 파일의 `criteria`에 따로 담긴다. `--import-human`이 `criteria.jsonl`에 합치고 `summary.md`에 "기준 의견(v3 후보)" 목록으로 보여 준다. 1단계 중에는 라벨을 바꾸지 않는다.
- 판정을 저장하면 최종 판정이 어디서 왔는지(키워드 자동 판정 / 사람이 고침(manual.yaml))가 같이 보인다.

#### 브라우저 수동 확인 목록 (화면 동작은 자동 테스트가 없다)

새 `review.html`을 만들 때마다 한 번 확인한다. 자동 테스트는 CSP 태그, 해시, 외부 요청 없음, 위험한 DOM API 없음, 이스케이프까지만 본다.

- [ ] 파일을 더블클릭해 열린다 (서버 없이).
- [ ] 개발자 도구 콘솔에 CSP 오류 없음
- [ ] 내 판정 모드: 저장 전에는 면접관 판정, 다수결, 최종 판정, 볼 이유가 안 보이고, 저장하면 보인다
- [ ] 판정이나 이유를 비우고 저장하면 막힌다
- [ ] "다음 미판정", 이전, 다음 이동이 맞다
- [ ] 새로 고침 후 중간 저장 유지 (판정한 건, 보던 위치, 모드)
- [ ] 창을 닫았다 다시 열어도 중간 저장 유지
- [ ] 내보내기 다운로드 됨 (`human-<실행폴더>.json`), 안 되면 아래 텍스트 상자에 같은 내용이 보인다
- [ ] 보기 모드: 질문, 회차 묶음이 맞고 같은 묶음의 세 답 순서가 묶음마다 다르다
- [ ] 필터 4개와 면접관 필터가 동작하고, 내 판정 전의 건은 항상 보인다
- [ ] "내 판정 전에는 숨김"을 끄면 모두 보인다
- [ ] 라이트/다크 모드에서 글자가 읽힌다
- [ ] 화면 어디에도 결과 이름(baseline, ctrl, prefix 등)이 없다
- [ ] 한 건 화면이 질문 → 문항 유형 → 정답 조건 → 근거 문서 → MALA의 답 → 찾아온 출처 순서고, 칸마다 쉬운 제목이 있다
- [ ] in_notes / not_in_notes 문항 유형 설명 문구가 맞다. not_in_notes는 정답 조건이 "없음(위 유형 설명 참고)", 근거 문서가 "기록 없음"이다
- [ ] 근거 문서를 펼치면 해당 부분이 보이고 파일 이름이 맞다
- [ ] 답이 읽기 좋게 보이고(굵게, 목록, 들여쓰기, 코드), "원문 보기"로 원문과 바꿔 볼 수 있다. 해석 안 되는 문법은 글자 그대로다
- [ ] 근거 문서 발췌도 같은 방식으로 읽기 좋게 보이고(제목은 굵게, 표는 표, 인용은 흐린 상자, 링크는 글만+흐린 주소, 구분선, ✓), 각 발췌마다 "원문 보기" 토글이 된다
- [ ] 표 중간에서 잘린 발췌(머리줄 없음)는 그 줄들이 글자 그대로 보인다 (표가 깨져 보이지 않는다)
- [ ] 핵심어가 답과 발췌에서 형광펜으로 칠해지고(라이트/다크 모두 읽힘), 근거 문서 칸 맨 위에 문서마다 "핵심어가 나오는 줄"이 한두 줄 보인다
- [ ] 콘솔(F12)에 CSP 오류가 없다 (새 요소도 인라인 스타일 없이 클래스로만 꾸민다)
- [ ] "판정 기준" 버튼이 열리고 닫힌다
- [ ] 기준 의견: 체크와 메모를 저장해도 판정과 섞이지 않는다. 새로 고침 후에도 남는다. 둘 다 비우고 저장하면 지워진다
- [ ] 내보낸 JSON에 `items`와 `criteria`가 따로 있다
- [ ] 판정을 저장하면 최종 판정의 출처(키워드 자동 판정 / 사람이 고침)가 보인다
- [ ] 숨김을 켠 채(기본) 사람이 볼 건을 저장하면 "저장됨 (블라인드 판정)"이 뜨고, "내 판정 전에는 숨김"을 끈 상태에서 저장하면 안내 문구가 먼저 보이고 "저장됨 (면접관 판정을 본 뒤 판정)"이 뜬다
- [ ] 블라인드로 저장한 건의 이유 글만 고쳐 다시 저장하면 "블라인드 판정"이 그대로고, 판정(합격/불합격/보류)을 바꿔 저장하면 "면접관 판정을 본 뒤 판정"으로 바뀐다
- [ ] 내보낸 JSON의 `items`마다 `blind`가 true/false로 들어 있고 위 동작과 맞다
- [ ] 개발자 도구 "문제" 탭에 "입력 칸에 id나 name이 없음" 경고가 없다

## 결과 보관

`eval_run`은 `data/eval/`(git 밖)에 씁니다. 기준선처럼 남길 결과는 `eval/results/`로 옮겨 git에 올립니다.
공개 docs 사본으로 잰 결과만 올립니다. 다른 PC에서도 같은 결과로 재채점할 수 있습니다.

- `20261028-2205_baseline-docs.*` — 0단계 기준선 (원본, 사람 판정, 재채점 v1 `_rescored`, v2 `_rescored-v2`)
- `20261029-2109_ret-*` — 검색만 재기 4개 조합, 라벨 v1
- `20261029-2116_ret-v2-*` — 검색만 재기 4개 조합, 라벨 v2 (`ret-v2-k3-keyword`가 검색 기준선)
- `20261030-2115_ret-v2-k3-*-prefix` — 임베딩 접두어(nomic), TOP_K 3 keyword·off, 라벨 v2
- `20261030-2139_baseline-docs-ctrl.*` — 답변 평가 대조군 (접두어 off, Ollama 0.40.13). 원본, 사람 판정, 재채점 v2
- `20261030-2134_baseline-docs-prefix.*` — 답변 평가 접두어 (nomic, Ollama 0.40.13). 원본, 사람 판정, 재채점 v2
- 2026-10-30부터 사람 판정 규칙: not_in_notes는 전부, in_notes는 자동 O도 사람이 봅니다. 기준선 `manual.yaml`에도 같은 규칙으로 q07·q09·q13을 더했습니다 (숫자는 그대로).

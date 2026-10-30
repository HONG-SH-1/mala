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

`EMBED_PREFIX=nomic`이면 색인할 때 `search_document: `, 검색할 때 `search_query: `를 붙입니다 (기본 `off`는 지금 동작).
벡터가 달라지므로 색인을 따로 만듭니다. `eval/env_docs_prefix.ps1`은 `env_docs.ps1`을 불러온 뒤 바뀌는 값만 덮어씁니다.

| 값 | 기준선 (`env_docs.ps1`) | 접두어 (`env_docs_prefix.ps1`) |
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

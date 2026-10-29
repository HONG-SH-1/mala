# 평가 (0단계 기준선)

지금 코드를 고치기 전에 한 번 재 두고, 이후 무엇을 바꾸든 같은 질문으로 다시 잽니다.
기존 `src` 코드는 건드리지 않고, Ollama 호출만 바깥에서 감싸 시간과 토큰을 기록합니다.

## 질문 파일

`questions.yaml`은 공개 `docs/` 사본을 기준으로 쓴 질문이라 git에 올립니다.
`questions.example.yaml`은 형식 예시입니다. 개인 볼트로 질문을 만들면 내용이 노트에서 나오므로 git에 올리지 않습니다.

권장 구성은 20개입니다. 노트에 답이 있는 질문 15개, 노트에 없는 질문 5개입니다.
노트에 없는 질문은 "모른다"고 답해야 정답입니다.

## 평가 대상 (docs 고정 사본)

기준선은 레포 `docs/`를 고정 복사한 `data/eval_corpus/docs-20261028/`로 잽니다.
사본은 2e55c5b 시점의 docs/에서 만든다 (`data/`는 git에 없으므로 다른 PC에서는 이 커밋에서 다시 복사).
`.env`는 그대로 두고, 평가 전용 환경변수는 `eval/env_docs.ps1`에 모아 둡니다.
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

- `20261028-2205_baseline-docs.*` — 0단계 기준선 (원본, 사람 판정, 재채점)

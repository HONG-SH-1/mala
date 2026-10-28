# 평가 (0단계 기준선)

지금 코드를 고치기 전에 한 번 재 두고, 이후 무엇을 바꾸든 같은 질문으로 다시 잽니다.
기존 `src` 코드는 건드리지 않고, Ollama 호출만 바깥에서 감싸 시간과 토큰을 기록합니다.

## 질문 파일

`questions.example.yaml`을 `questions.yaml`로 복사해서 내 노트 기준으로 씁니다.
`questions.yaml`은 내 노트 내용이 들어가므로 git에 올라가지 않습니다.

권장 구성은 20개입니다. 노트에 답이 있는 질문 15개, 노트에 없는 질문 5개입니다.
노트에 없는 질문은 "모른다"고 답해야 정답입니다.

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

자동 판정은 키워드 기준이라 거칩니다. 애매한 문항은 jsonl의 `manual_correct` 칸을 직접 채웁니다.
첫 문항은 모델 로드 시간이 섞일 수 있어 `load_ms`를 따로 남깁니다.

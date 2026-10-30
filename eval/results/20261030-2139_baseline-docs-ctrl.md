# 평가 결과: baseline-docs-ctrl

- 시각: 2026-10-30T21:34:44
- 커밋: 1e0fe06
- 답변 모델: qwen3:8b, 임베딩: nomic-embed-text, TOP_K: 3, rerank: keyword
- 볼트: data/eval_corpus/docs-20261028, 컬렉션: mala_eval_docs
- Ollama: 0.40.13, digest: 답변 500a1f067a9f, 임베딩 0a109f422b47, 임베딩 접두어: off
- 질문 파일: eval/questions.yaml (sha256 68e6aebc)
- 질문 20개 x 2회

| 지표 | 값 |
| --- | --- |
| 정답률 (자동 판정) | 45% (20개 판정, 0개는 수동 확인 필요) |
| 노트에 있는 질문 정답률 | 33% |
| 노트에 없는 질문에 '모른다' | 80% |
| 출처 일치율 | 80% |
| 응답 시간 중앙값 | 7,324ms |
| 응답 시간 최대 | 10,352ms |
| 입력 토큰 평균 | 511 |
| 출력 토큰 평균 | 362 |
| 재시도가 일어난 질문 | 0개 |
| 검증 실패로 끝난 질문 | 0개 |
| thinking 블록이 섞인 답 | 0개 |
| 반복 시 판정이 같은 비율 | 95% |
| 반복 시 답이 글자까지 같은 비율 | 10% |

## 문항별 (1회차)

| id | 유형 | 자동 판정 | 출처 | 시간 | 출력 토큰 | 호출 |
| --- | --- | --- | --- | --- | --- | --- |
| q01 | in_notes | X | O | 10,352ms | 638 | 1 |
| q02 | in_notes | X | O | 6,515ms | 230 | 1 |
| q03 | in_notes | O | O | 9,649ms | 570 | 1 |
| q04 | in_notes | X | O | 8,764ms | 483 | 1 |
| q05 | in_notes | X | O | 6,553ms | 237 | 1 |
| q06 | in_notes | X | X | 6,289ms | 226 | 1 |
| q07 | in_notes | O | O | 7,597ms | 360 | 1 |
| q08 | in_notes | O | O | 9,623ms | 551 | 1 |
| q09 | in_notes | O | O | 8,410ms | 448 | 1 |
| q10 | in_notes | X | O | 7,857ms | 399 | 1 |
| q11 | in_notes | X | X | 6,869ms | 289 | 1 |
| q12 | in_notes | X | O | 6,064ms | 203 | 1 |
| q13 | in_notes | O | O | 8,556ms | 478 | 1 |
| q14 | in_notes | X | X | 6,838ms | 292 | 1 |
| q15 | in_notes | X | O | 7,051ms | 312 | 1 |
| q16 | not_in_notes | O | - | 8,023ms | 412 | 1 |
| q17 | not_in_notes | O | - | 6,472ms | 247 | 1 |
| q18 | not_in_notes | X | - | 7,786ms | 370 | 1 |
| q19 | not_in_notes | O | - | 6,217ms | 206 | 1 |
| q20 | not_in_notes | O | - | 7,009ms | 283 | 1 |

첫 문항은 모델 로드 시간이 섞일 수 있습니다 (load_ms 확인).
자동 판정은 키워드 기준이라 거칩니다. jsonl의 manual_correct 칸으로 직접 확인하세요.

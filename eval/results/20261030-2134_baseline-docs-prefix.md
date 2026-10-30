# 평가 결과: baseline-docs-prefix

- 시각: 2026-10-30T21:28:19
- 커밋: 1e0fe06
- 답변 모델: qwen3:8b, 임베딩: nomic-embed-text, TOP_K: 3, rerank: keyword
- 볼트: data/eval_corpus/docs-20261028, 컬렉션: mala_eval_docs_prefix
- Ollama: 0.40.13, digest: 답변 500a1f067a9f, 임베딩 0a109f422b47, 임베딩 접두어: nomic
- 질문 파일: eval/questions.yaml (sha256 68e6aebc)
- 질문 20개 x 2회

| 지표 | 값 |
| --- | --- |
| 정답률 (자동 판정) | 55% (20개 판정, 0개는 수동 확인 필요) |
| 노트에 있는 질문 정답률 | 53% |
| 노트에 없는 질문에 '모른다' | 60% |
| 출처 일치율 | 87% |
| 응답 시간 중앙값 | 8,190ms |
| 응답 시간 최대 | 39,265ms |
| 입력 토큰 평균 | 647 |
| 출력 토큰 평균 | 443 |
| 재시도가 일어난 질문 | 0개 |
| 검증 실패로 끝난 질문 | 0개 |
| thinking 블록이 섞인 답 | 0개 |
| 반복 시 판정이 같은 비율 | 90% |
| 반복 시 답이 글자까지 같은 비율 | 0% |

## 문항별 (1회차)

| id | 유형 | 자동 판정 | 출처 | 시간 | 출력 토큰 | 호출 |
| --- | --- | --- | --- | --- | --- | --- |
| q01 | in_notes | X | O | 39,265ms | 696 | 1 |
| q02 | in_notes | O | O | 9,713ms | 550 | 1 |
| q03 | in_notes | O | O | 7,106ms | 289 | 1 |
| q04 | in_notes | X | O | 15,341ms | 1,154 | 1 |
| q05 | in_notes | O | O | 6,656ms | 241 | 1 |
| q06 | in_notes | X | X | 6,506ms | 247 | 1 |
| q07 | in_notes | O | O | 7,706ms | 357 | 1 |
| q08 | in_notes | O | O | 8,565ms | 465 | 1 |
| q09 | in_notes | O | O | 6,947ms | 299 | 1 |
| q10 | in_notes | O | O | 13,094ms | 965 | 1 |
| q11 | in_notes | X | X | 8,164ms | 427 | 1 |
| q12 | in_notes | X | O | 6,184ms | 220 | 1 |
| q13 | in_notes | O | O | 8,811ms | 499 | 1 |
| q14 | in_notes | X | O | 8,288ms | 440 | 1 |
| q15 | in_notes | X | O | 8,238ms | 438 | 1 |
| q16 | not_in_notes | X | - | 8,217ms | 412 | 1 |
| q17 | not_in_notes | O | - | 5,632ms | 155 | 1 |
| q18 | not_in_notes | X | - | 8,746ms | 476 | 1 |
| q19 | not_in_notes | O | - | 7,097ms | 304 | 1 |
| q20 | not_in_notes | O | - | 6,226ms | 222 | 1 |

첫 문항은 모델 로드 시간이 섞일 수 있습니다 (load_ms 확인).
자동 판정은 키워드 기준이라 거칩니다. jsonl의 manual_correct 칸으로 직접 확인하세요.

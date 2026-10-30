# 검색 평가: ret-v2-k3-keyword-prefix

- 시각: 2026-10-30T21:15:01
- 커밋: 53cf1d1 (src에 커밋 안 된 변경 있음)
- 볼트: data/eval_corpus/docs-20261028, 컬렉션: mala_eval_docs_prefix
- TOP_K: 3, rerank: keyword, 임베딩: nomic-embed-text
- Ollama: 0.40.13, digest: 답변 500a1f067a9f, 임베딩 0a109f422b47, 임베딩 접두어: nomic
- 질문: eval/questions.yaml (sha256 68e6aebc)의 in_notes 15개 x 1회 (답변 모델 호출 없음)

| 지표 | 값 |
| --- | --- |
| 답 근거 청크 포함률 (기대 출처, 주 지표) | 53% (8/15) |
| 답 근거 청크 포함률 (아무 청크) | 60% (9/15) |
| 출처 일치율 (파일 단위) | 87% (13/15) |
| 가져온 청크 중 200자 미만 | 42% (19/45) |
| 검색 오류 | 0개 |

## 문항별

근거 칸은 must_include가 다 들어 있는 첫 청크의 순위입니다 (다른 표기 중 하나면 됨). 없으면 X.

| id | 출처 | 근거(기대 출처) | 근거(아무 청크) | 가져온 청크 (출처:글자 수) |
| --- | --- | --- | --- | --- |
| q01 | O | X | X | decisions/001-inference-engine.md:152, decisions/002-native-redis-phase1.md:205, decisions/README.md:398 |
| q02 | O | 3 | 3 | model-comparison.md:507, study/00-MALA-study-guide.md:767, opinion-infra-and-career.md:566 |
| q03 | O | 2 | 2 | development-log.md:40, scope.md:1085, development-log.md:141 |
| q04 | O | X | X | study/00-MALA-study-guide.md:767, study/03-queue.md:522, opinion-infra-and-career.md:351 |
| q05 | O | 1 | 1 | hardware-environment.md:670, demo.md:240, model-comparison.md:507 |
| q06 | X | X | X | design-process.md:237, study/00-MALA-study-guide.md:162, development-log.md:88 |
| q07 | O | 1 | 1 | study/00-MALA-study-guide.md:359, model-comparison.md:1290, model-comparison.md:156 |
| q08 | O | 1 | 1 | study/00-MALA-study-guide.md:198, development-log.md:88, design-process.md:237 |
| q09 | O | 2 | 2 | development-log.md:50, study/04-graph.md:509, study/00-MALA-study-guide.md:26 |
| q10 | O | X | 3 | design-process.md:237, study/00-MALA-study-guide.md:200, opinion-infra-and-career.md:88 |
| q11 | X | X | X | development-log.md:50, study/04-graph.md:509, study/04-graph.md:458 |
| q12 | O | X | X | scope.md:178, design-process.md:88, workflow-roles.md:87 |
| q13 | O | 2 | 2 | demo.md:144, demo.md:240, development-log.md:312 |
| q14 | O | X | X | development-log.md:312, demo.md:144, workflow-roles.md:87 |
| q15 | O | 3 | 3 | design-process.md:24, design-process.md:237, design-process.md:271 |

판정은 프롬프트에 실제로 들어가는 글(format_context, 본문 1200자까지)로 합니다.

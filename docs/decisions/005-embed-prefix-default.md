# ADR-005: 임베딩 접두어 기본값을 nomic으로

| 항목 | 내용 |
|------|------|
| **상태** | Accepted |
| **날짜** | 2026-11-01 |
| **맥락** | 1단계 검색 개선 실험, fix-later 17번 |

---

## 맥락

`nomic-embed-text`는 입력 앞에 용도를 붙여 쓰는 모델이다. 문서에는 `search_document: `, 질문에는 `search_query: `를 붙인다. MALA는 지금까지 아무것도 붙이지 않고 임베딩했다 ([fix-later 17](../study/fix-later.md)).

2026-10-30에 스위치 `EMBED_PREFIX=off|nomic`(기본 off)을 넣고, 평가 전용 색인을 따로 만들어 검색과 답변을 쟀다. 평가 대상은 docs 고정 사본이다 ([ADR-004](004-eval-docs-snapshot.md)).

## 결정

- `src/config.py`의 `EMBED_PREFIX` 기본값을 `off`에서 `nomic`으로 바꾼다.
- `eval/env_docs.ps1`은 10-28 기준선 재현용이라 `EMBED_PREFIX=off` 고정을 그대로 둔다. 1단계의 새 비교 기준은 접두어 결과이고, 비교 설정은 `eval/env_docs_prefix.ps1`이다.

## 근거

평가 설정은 TOP_K 3, rerank keyword, 질문 라벨 v2다.

| 지표 | off → nomic | 비교 대상 |
|---|---|---|
| 답 근거 청크 포함률 (기대 출처, 검색 주 지표) | 27% (4/15) → 53% (8/15) | 10-29 검색 기준선 |
| in_notes 정답률 (최종, 사람 판정 반영) | 27% (4/15) → 47% (7/15) | 10-30 같은 날 대조군 |
| 나빠진 문항 | 검색 0, 답변 in_notes 0 | |

- 검색 기준선은 10-29 결과지만, 10-30(Ollama 0.40.13)에 `env_docs.ps1`로 다시 재서 문항별로 같음을 확인했다. 확인용이라 결과 파일은 커밋하지 않았다 (`data/eval/20261030-2115_ret-v2-k3-keyword-offcheck.md`).
- 답변은 같은 날, 같은 Ollama로 접두어만 바꿔 쟀다 (`--repeat 2`, 비율은 1회차 기준). in_notes에서 q02, q03, q05가 X → O로 바뀌었고, 모두 검색 근거가 새로 잡힌 문항이다.

결과 파일:
- 검색: [`20261029-2116_ret-v2-k3-keyword.md`](../../eval/results/20261029-2116_ret-v2-k3-keyword.md) → [`20261030-2115_ret-v2-k3-keyword-prefix.md`](../../eval/results/20261030-2115_ret-v2-k3-keyword-prefix.md)
- 답변: [`20261030-2139_baseline-docs-ctrl_rescored-v2.md`](../../eval/results/20261030-2139_baseline-docs-ctrl_rescored-v2.md) → [`20261030-2134_baseline-docs-prefix_rescored-v2.md`](../../eval/results/20261030-2134_baseline-docs-prefix_rescored-v2.md)

## 대가

| 지표 | 대조군 (off) → 접두어 (nomic) |
|---|---|
| 입력 토큰 평균 | 511 → 647 |
| 응답 시간 중앙값 | 7,324ms → 8,190ms |

- 검색 결과에서 200자 미만 청크가 76% (34/45) → 42% (19/45)로 줄었다. 입력 토큰이 늘어난 이유로 보이지만 따로 재지는 않았다.
- q01은 모델이 이미 올라온 상태(2회차, load_ms 5)에서도 19,051ms로 대조군(10,352ms)보다 느렸다. 원인은 재지 않았다.

## 한계

- in_notes 15문항, 반복 2회다. 우연을 완전히 배제할 수 없다.
- 평가 대상은 프로젝트 자신의 docs 사본이다. 개인 볼트에서도 같은 효과가 난다는 보장은 없다.

## 결과

- 기존 색인은 다시 만들어야 한다. 컬렉션 메타데이터에 `embed_prefix`가 없으면 off로 보고, 지금 설정과 다르면 열 때 오류를 낸다 (섞임 방지, `src/retrieval/chroma_store.py`). 실제 볼트는 새 컬렉션과 새 매니페스트로 다시 색인한다. 매니페스트를 같이 쓰면 증분 색인이 "바뀐 것 없음"으로 건너뛴다.
- 기존 컬렉션 `mala_vault`를 계속 쓰려면 `.env`에 `EMBED_PREFIX=off`를 적어야 한다.

## 되돌리는 방법

- 코드는 그대로 두고 `.env`에 `EMBED_PREFIX=off`를 넣는다. 그다음 접두어 없이 색인된 컬렉션과 그 매니페스트(`CHROMA_COLLECTION`, `INDEX_MANIFEST_PATH`)로 돌린다.
- 기본값 자체를 되돌릴 때는 `src/config.py`의 기본값을 `off`로 바꾸고 `tests/test_embed_prefix.py::test_setting_values`도 같이 고친다.

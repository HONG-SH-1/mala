# 임베딩 접두어 실험(fix-later 17번)용 환경변수. env_docs.ps1 값에 바뀌는 값만 덧붙인다.
# 색인을 따로 만든다: 컬렉션·매니페스트·실패 기록을 기준선과 같이 쓰면 증분 색인이
# "바뀐 것 없음"으로 건너뛰거나, 접두어가 다른 벡터가 섞인다.
#   . .\eval\env_docs_prefix.ps1; python -m src.scripts.build_index
#   . .\eval\env_docs_prefix.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --retrieval-only --label <이름>

. "$PSScriptRoot\env_docs.ps1"
$env:CHROMA_COLLECTION   = "mala_eval_docs_prefix"
$env:INDEX_MANIFEST_PATH = "data/eval_manifest_docs_prefix.json"
$env:INDEX_FAILURES_PATH = "data/eval_index_failures_prefix.jsonl"
$env:EMBED_PREFIX        = "nomic"

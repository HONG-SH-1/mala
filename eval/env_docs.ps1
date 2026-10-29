# 0단계 기준선(docs 고정 사본) 평가용 환경변수.
# .env는 그대로 두고, 이 스크립트를 같은 줄에서 불러와 그 명령에만 적용한다.
#   . .\eval\env_docs.ps1; python -m src.scripts.eval_run --questions eval/questions.yaml --dry-run
# 레포 루트에서 실행해야 한다 (CHROMA_PERSIST_DIR는 실행 위치 기준 상대 경로).

$env:PYTHONUTF8 = "1"
$env:OBSIDIAN_VAULT_PATH = "data/eval_corpus/docs-20261028"
$env:OBSIDIAN_INCLUDE    = ""
$env:CHROMA_PERSIST_DIR  = "data/chroma_eval"
$env:CHROMA_COLLECTION   = "mala_eval_docs"
$env:INDEX_MANIFEST_PATH = "data/eval_manifest_docs.json"
$env:INDEX_FAILURES_PATH = "data/eval_index_failures.jsonl"

# 기준선(20261028-2205_baseline-docs) 때 쓰인 값을 적어 둔 것. 동작은 같다.
# 모델과 TOP_K는 결과 .md 머리, GRAPH_MAX_RETRIES는 .env(마지막 수정 2026-05-26)에서 확인.
# 실험할 때는 이 스크립트 뒤에서 덮어쓴다. 예: . .\eval\env_docs.ps1; $env:RAG_TOP_K = "5"; ...
$env:OLLAMA_MODEL        = "qwen3:8b"
$env:OLLAMA_EMBED_MODEL  = "nomic-embed-text"
$env:GRAPH_MAX_RETRIES   = "2"
$env:RAG_TOP_K           = "3"
$env:RAG_RERANK          = "keyword"

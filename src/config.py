import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    redis_host: str
    redis_port: int
    redis_db: int
    task_queue: str
    result_queue: str
    processing_queue: str
    dead_letter_queue: str
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_sec: float
    worker_id: str
    graph_max_retries: int
    task_status_prefix: str
    project_root: Path
    obsidian_vault_path: str
    chroma_persist_dir: str
    chroma_collection: str
    index_manifest_path: str
    ollama_embed_model: str
    rag_top_k: int
    index_failures_path: str


def get_settings() -> Settings:
    return Settings(
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        redis_db=int(os.getenv("REDIS_DB", "0")),
        task_queue=os.getenv("TASK_QUEUE", "task_queue"),
        result_queue=os.getenv("RESULT_QUEUE", "result_queue"),
        processing_queue=os.getenv(
            "PROCESSING_QUEUE", "mala:processing:worker_1"
        ),
        dead_letter_queue=os.getenv("DEAD_LETTER_QUEUE", "mala:dead_letter_queue"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        ollama_timeout_sec=float(os.getenv("OLLAMA_TIMEOUT_SEC", "120")),
        worker_id=os.getenv("WORKER_ID", "worker_1"),
        graph_max_retries=int(os.getenv("GRAPH_MAX_RETRIES", "2")),
        task_status_prefix=os.getenv("TASK_STATUS_PREFIX", "task_status"),
        project_root=_ROOT,
        obsidian_vault_path=os.getenv("OBSIDIAN_VAULT_PATH", "vault_sample"),
        chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR", "data/chroma"),
        chroma_collection=os.getenv("CHROMA_COLLECTION", "mala_vault"),
        index_manifest_path=os.getenv(
            "INDEX_MANIFEST_PATH", "data/index_manifest.json"
        ),
        ollama_embed_model=os.getenv(
            "OLLAMA_EMBED_MODEL", "nomic-embed-text"
        ),
        rag_top_k=int(os.getenv("RAG_TOP_K", "5")),
        index_failures_path=os.getenv(
            "INDEX_FAILURES_PATH", "data/index_failures.jsonl"
        ),
    )

"""OBSIDIAN_INCLUDE path filtering."""

from pathlib import Path

from src.config import Settings
from src.retrieval.pipeline import (
    compute_vault_filter_stats,
    file_matches_include,
    iter_markdown_files,
    parse_include_prefixes,
)


def _settings(include: str, vault: Path) -> Settings:
    return Settings(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        task_queue="t",
        result_queue="r",
        processing_queue="p",
        dead_letter_queue="d",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="qwen3:8b",
        ollama_timeout_sec=120.0,
        worker_id="w",
        graph_max_retries=2,
        task_status_prefix="task_status",
        project_root=vault.parent,
        obsidian_vault_path=str(vault),
        obsidian_include=include,
        chroma_persist_dir="data/chroma",
        chroma_collection="test",
        index_manifest_path="data/manifest.json",
        ollama_embed_model="nomic-embed-text",
        rag_top_k=5,
        index_failures_path="data/failures.jsonl",
        ollama_router_model="hermes3:8b",
        max_tool_steps=5,
        use_hermes_router=False,
    )


def test_parse_include_prefixes_empty():
    assert parse_include_prefixes("") == []
    assert parse_include_prefixes("  ,  ") == []


def test_file_matches_include():
    prefixes = ["06_Portfolio", "docs"]
    assert file_matches_include("06_Portfolio/note.md", prefixes)
    assert file_matches_include("docs/a.md", prefixes)
    assert not file_matches_include("05_Certifications/SQLD/x.md", prefixes)


def test_iter_markdown_files_filtered(tmp_path):
    vault = tmp_path / "vault"
    (vault / "06_Portfolio").mkdir(parents=True)
    (vault / "05_Other").mkdir(parents=True)
    (vault / "06_Portfolio" / "a.md").write_text("# A\n", encoding="utf-8")
    (vault / "05_Other" / "b.md").write_text("# B\n", encoding="utf-8")

    settings = _settings("06_Portfolio", vault)
    files = iter_markdown_files(vault, settings)
    assert len(files) == 1
    assert files[0].name == "a.md"


def test_compute_vault_filter_stats(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "inc").mkdir()
    (vault / "exc").mkdir()
    (vault / "inc" / "i.md").write_text("# I\n", encoding="utf-8")
    (vault / "exc" / "e.md").write_text("# E\n", encoding="utf-8")

    stats = compute_vault_filter_stats(vault, _settings("inc", vault))
    assert stats.total_md == 2
    assert stats.included == 1
    assert stats.excluded == 1

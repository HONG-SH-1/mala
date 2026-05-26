"""Tool schemas — Phase 4 Hermes / function calling."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchVaultArgs(BaseModel):
    query: str = Field(min_length=1, description="Semantic search query for Obsidian vault")


def search_vault_tool_spec() -> dict:
    schema = SearchVaultArgs.model_json_schema()
    props = schema.get("properties", {})
    return {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": (
                "Search the user's local Obsidian markdown vault (Chroma RAG). "
                "Use when the question needs personal notes or project docs."
            ),
            "parameters": {
                "type": "object",
                "properties": props,
                "required": ["query"],
            },
        },
    }

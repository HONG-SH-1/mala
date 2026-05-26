"""Markdown chunking by ATX headings (# .. ###)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class TextChunk:
    source: str
    heading: str
    level: int
    text: str
    chunk_index: int

    @property
    def chunk_id(self) -> str:
        slug = re.sub(r"[^\w\-]+", "-", self.heading.lower()).strip("-") or "root"
        return f"{self.source}::{slug}::{self.chunk_index}"


def chunk_markdown(content: str, source: str) -> list[TextChunk]:
    """Split markdown into chunks; preamble before first heading is one chunk."""
    matches = list(_HEADING_RE.finditer(content))
    if not matches:
        body = content.strip()
        if not body:
            return []
        return [
            TextChunk(
                source=source,
                heading="(document)",
                level=0,
                text=body,
                chunk_index=0,
            )
        ]

    chunks: list[TextChunk] = []
    idx = 0

    preamble = content[: matches[0].start()].strip()
    if preamble:
        chunks.append(
            TextChunk(
                source=source,
                heading="(preamble)",
                level=0,
                text=preamble,
                chunk_index=idx,
            )
        )
        idx += 1

    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        text = f"#{'#' * (level - 1)} {heading}\n\n{body}".strip() if body else heading
        chunks.append(
            TextChunk(
                source=source,
                heading=heading,
                level=level,
                text=text,
                chunk_index=idx,
            )
        )
        idx += 1

    return chunks

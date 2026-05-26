from src.retrieval.chunker import chunk_markdown


def test_chunk_by_headings():
    md = """# Title

intro

## Section A

body a

## Section B

body b
"""
    chunks = chunk_markdown(md, "note.md")
    headings = [c.heading for c in chunks]
    assert "(preamble)" in headings or "Title" in headings
    assert "Section A" in headings
    assert "Section B" in headings
    assert all(c.source == "note.md" for c in chunks)


def test_chunk_ids_unique():
    chunks = chunk_markdown("# H\n\ntext", "a.md")
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))

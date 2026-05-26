from src.retrieval.manifest import diff_manifest


def test_diff_manifest():
    prev = {"a.md": "aaa", "b.md": "bbb"}
    curr = {"a.md": "aaa", "b.md": "changed", "c.md": "ccc"}
    added, changed, removed = diff_manifest(curr, prev)
    assert added == ["c.md"]
    assert changed == ["b.md"]
    assert removed == []

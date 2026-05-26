from src.retrieval.manifest import diff_manifest


def test_diff_only_one_changed():
    prev = {f"n{i}.md": f"h{i}" for i in range(10)}
    curr = dict(prev)
    curr["n5.md"] = "changed_hash"
    added, changed, removed = diff_manifest(curr, prev)
    assert added == []
    assert removed == []
    assert changed == ["n5.md"]
    assert len(curr) - len(changed) == 9

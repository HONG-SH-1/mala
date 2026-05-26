from src.recommend_model import parse_nvidia_smi_csv, pick_profile


def test_parse_nvidia_smi_csv():
    name, gb = parse_nvidia_smi_csv("NVIDIA GeForce RTX 3080, 10240")
    assert "3080" in name
    assert 9.9 < gb < 10.1


def test_pick_profile_3080_32gb():
    mode, hint, _ = pick_profile(10.0, 32.0)
    assert mode == "hybrid"
    assert "14B" in hint or "offload" in hint

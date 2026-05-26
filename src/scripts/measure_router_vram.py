"""Phase 4 — measure peak VRAM for router model (Hermes) vs chat model."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time

from src.config import get_settings


def _nvidia_smi_mib() -> str:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "nvidia-smi not found"
    proc = subprocess.run(
        [
            exe,
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return proc.stderr or "nvidia-smi failed"
    used, total = [x.strip() for x in proc.stdout.strip().split(",")]
    return f"VRAM used={used} MiB / total={total} MiB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model tag (default: OLLAMA_ROUTER_MODEL)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="nvidia-smi samples while you run inference in another window",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    model = args.model or settings.ollama_router_model
    chat = settings.ollama_model

    print("=== MALA Phase 4 VRAM measurement ===")
    print(f"Router model (Hermes): {model}")
    print(f"Chat model (Qwen):     {chat}")
    print()
    print("Step 1 — baseline (Ollama idle or only embed):")
    print(" ", _nvidia_smi_mib())
    print()
    print("Step 2 — in ANOTHER terminal, run ONE model at a time:")
    print(f"  ollama run {model}")
    print('  Then type a short prompt, e.g. "hello"')
    print()
    print("Step 3 — while generating, watch peaks here (Ctrl+C to stop):")
    try:
        for i in range(args.samples):
            print(f"  sample {i + 1}: {_nvidia_smi_mib()}")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopped.")
    print()
    print("Record peak MiB in docs/model-comparison.md (Hermes row).")
    print("Do NOT run both models loaded at once on 10GB — see ADR-003.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""GPU/RAM diagnosis — model and offload recommendation (Phase 2)."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys

import psutil


def _gpu_via_pynvml() -> tuple[str, float] | None:
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return name, info.total / 1024**3
    except Exception:
        return None


def parse_nvidia_smi_csv(line: str) -> tuple[str, float]:
    """Parse `name, <mib>` from nvidia-smi csv,noheader,nounits."""
    parts = [p.strip() for p in line.strip().split(",")]
    if len(parts) < 2:
        raise ValueError(f"unexpected nvidia-smi line: {line!r}")
    name = parts[0]
    mib = float(re.sub(r"[^\d.]", "", parts[-1]))
    return name, mib / 1024


def _gpu_via_nvidia_smi() -> tuple[str, float] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [
                exe,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        line = proc.stdout.strip().splitlines()[0]
        return parse_nvidia_smi_csv(line)
    except Exception:
        return None


def _gpu_vram_gb() -> tuple[str, float]:
    for probe in (_gpu_via_pynvml, _gpu_via_nvidia_smi):
        result = probe()
        if result is not None:
            return result
    return "unknown", 0.0


def pick_profile(vram_gb: float, ram_gb: float) -> tuple[str, str, str]:
    """Return (mode, model_hint, rationale) using conservative VRAM budget."""
    vram_budget = max(vram_gb - 1 - 3, 0)
    effective_vram = vram_budget + 4

    if effective_vram >= 16:
        return "full-gpu", "14B~32B class", "VRAM headroom for larger dense models"
    if 6 <= effective_vram <= 10 and ram_gb >= 24:
        return (
            "hybrid",
            "14B or MoE with CPU offload",
            "VRAM tight but RAM can absorb offload (watch MoE on 10GB)",
        )
    if 6 <= effective_vram <= 10:
        return (
            "vram-first",
            "8B~14B Q4 (e.g. qwen3:8b)",
            "Limited RAM - prefer proven 8B E2E on 10GB",
        )
    return "minimal", "8B Q4", "Conservative single-model default"


def format_report(gpu_name: str, vram_gb: float, ram_gb: float) -> str:
    mode, model_hint, why = pick_profile(vram_gb, ram_gb)
    lines = [
        f"GPU {gpu_name} ({vram_gb:.1f} GB VRAM total)",
        f"RAM {ram_gb:.1f} GB total",
        f"mode={mode}",
        f"model_hint={model_hint}",
        f"why={why}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MALA model/offload recommendation")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON (future tooling)",
    )
    args = parser.parse_args(argv)

    gpu_name, vram_gb = _gpu_vram_gb()
    ram_gb = psutil.virtual_memory().total / 1024**3
    report = format_report(gpu_name, vram_gb, ram_gb)

    if args.json:
        mode, model_hint, why = pick_profile(vram_gb, ram_gb)
        import json

        print(
            json.dumps(
                {
                    "gpu_name": gpu_name,
                    "vram_gb": round(vram_gb, 2),
                    "ram_gb": round(ram_gb, 2),
                    "mode": mode,
                    "model_hint": model_hint,
                    "why": why,
                },
                ensure_ascii=False,
            )
        )
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

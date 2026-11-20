"""토론(debate/) 기록 읽고 쓰기. judge.py를 가져오지 않는다 (순환 방지).

원본 판정 파일(judge_*.jsonl), 결과 .md, human.jsonl은 건드리지 않는다. 토론 결과는 실행 폴더 안 debate/ 에만 쌓는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.eval.judge_human import atomic_write_text

DEBATE_DIR = "debate"
ARBITER_FILE = "arbiter.jsonl"
COMPARE_FILE = "arbiter_compare.jsonl"
FINAL_FILE = "final.jsonl"
CONFIG_FILE = "config.json"
REPORT_MD = "report.md"
REPORT_HTML = "report.html"


PATHS = {
    "unanimous_r1": "셋이 같아 토론 안 함",
    "excluded": "판정 불가가 있어 토론에서 뺌",
    "unrun": "아직 안 돌린 건",
    "pending": "토론 진행 중",
    "unanimous_r2": "2라운드 뒤 만장일치",
    "arbiter_with_plurality": "중재가 다수 의견을 따름",
    "arbiter_minority_won": "중재에서 소수 의견이 이김",
    "arbiter_no_plurality": "다수가 없어 중재가 결정",
    "override_without_evidence": "중재가 확인된 근거 없이 뒤집으려 해 보류",
    "unresolved": "끝까지 갈림",
}
REVIEW_REASON = {
    "arbiter_minority_won": "토론: 소수 의견이 이김",
    "arbiter_no_plurality": "토론: 다수 없이 중재가 결정",
    "override_without_evidence": "토론: 중재가 근거 없이 뒤집으려 해 보류",
    "unresolved": "토론: 끝까지 갈림",
}
RESOLVED = ("unanimous_r2", "arbiter_with_plurality", "arbiter_minority_won", "arbiter_no_plurality", "override_without_evidence", "unresolved")


def ddir(out_dir: Path) -> Path:
    return out_dir / DEBATE_DIR


def read_rows(path: Path) -> dict[str, dict]:
    """키마다 마지막 줄만. 쓰는 중인 반쪽 줄이나 깨진 줄은 건너뛴다."""
    rows: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and isinstance(r.get("key"), str):
                rows[r["key"]] = r
    return rows


def round2_path(out_dir: Path, judge: str) -> Path:
    return ddir(out_dir) / f"round2_{judge}.jsonl"


def load_round2(out_dir: Path) -> dict[str, dict[str, dict]]:
    """{면접관: {key: 줄}}"""
    out: dict[str, dict[str, dict]] = {}
    d = ddir(out_dir)
    if d.is_dir():
        for p in sorted(d.glob("round2_*.jsonl")):
            out[p.stem[len("round2_"):]] = read_rows(p)
    return out


def load_config(out_dir: Path) -> dict | None:
    p = ddir(out_dir) / CONFIG_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_config(out_dir: Path, cfg: dict) -> None:
    ddir(out_dir).mkdir(parents=True, exist_ok=True)
    atomic_write_text(ddir(out_dir) / CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=1))


def load_final(out_dir: Path) -> dict[str, dict]:
    return read_rows(ddir(out_dir) / FINAL_FILE)


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rewrite_rows(path: Path, rows: list[dict]) -> None:
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def summarize(out_dir: Path) -> dict | None:
    """progress.html의 토론 구역에 쓸 현재 상태. 토론을 한 적이 없으면 None."""
    cfg = load_config(out_dir)
    if cfg is None:
        return None
    cands = list(cfg.get("candidates") or [])
    judges = list(cfg.get("judges") or [])
    r2 = load_round2(out_dir)
    per = {}
    changed = valid = invalid = 0
    for j in judges:
        rows = {k: r for k, r in (r2.get(j) or {}).items() if k in cands and r.get("status") in ("ok", "format_error")}
        per[j] = len(rows)
        for r in rows.values():
            changed += 1 if r.get("changed") else 0
            for c in r.get("citations") or []:
                if c.get("valid"):
                    valid += 1
                else:
                    invalid += 1
    arb = read_rows(ddir(out_dir) / ARBITER_FILE)
    return {"stage": cfg.get("stage", "round2"), "ended": bool(cfg.get("ended")), "interrupted": bool(cfg.get("interrupted")),
            "candidates": len(cands), "needs_arbiter": cfg.get("needs_arbiter"), "per_judge": per, "arbiter_done": len(arb),
            "changed": changed, "citations_valid": valid, "citations_invalid": invalid,
            "has_report": (ddir(out_dir) / REPORT_HTML).is_file(), "arbiter": cfg.get("arbiter"),
            "updated": cfg.get("updated")}

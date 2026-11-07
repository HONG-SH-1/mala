"""면접관 자동화 — 평가 결과(_rescored-v2.jsonl)를 Claude, Codex, Gemini 세 면접관이 판정한다.

공식 판정(eval_rescore, manual.yaml)과는 별개인 보조 도구다. 결과는 data/eval/judge/<실행>/ 에 남는다 (git 제외).

    # 첫 실행: 10건만 (Codex 월 한도 가늠). 세 결과에서 골고루, in/not_in 섞어 고정 시드로 뽑는다.
    python -m src.scripts.eval_judge eval/results/A_rescored-v2.jsonl eval/results/B_rescored-v2.jsonl \\
        eval/results/C_rescored-v2.jsonl --judges claude,codex,gemini --limit 10 --tag first10

    # 판정 불가 건만 같은 모델로 다시
    python -m src.scripts.eval_judge --resume data/eval/judge/<실행폴더>

금고 암호는 gemini를 쓸 때 시작에 한 번 터미널에서 직접 친다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.eval.judge import (
    JUDGE_NAMES,
    ClaudeJudge,
    CodexJudge,
    GeminiJudge,
    JudgeSpec,
    RateLimiter,
    build_items,
    execute,
    select_items,
    shuffle_items,
)
from src.eval.runner import load_questions
from src.keystore import GEMINI_ENTRY, KeystoreError, check_gemini_key_shape, get_secret, redact
from src.scripts.eval_rescore import load_records

_ROOT = Path(__file__).resolve().parents[2]
JUDGE_DIR = _ROOT / "data" / "eval" / "judge"


def _env_list(name: str) -> list[str]:
    return [p.strip() for p in (os.environ.get(name) or "").split(",") if p.strip()]


def resolve_workdir(raw: str | None, root: Path = _ROOT) -> Path:
    """면접관이 실행될 폴더. .env의 JUDGE_WORKDIR에서 읽고, 없거나 레포 안이면 시작 전에 멈춘다.

    레포 안에서 돌리면 CLAUDE.md 같은 파일이 면접관 입력에 섞인다 (파일럿에서 겪음).
    """
    raw = (raw or "").strip()
    if not raw:
        raise SystemExit(".env에 JUDGE_WORKDIR가 없음: 레포 밖 빈 폴더 경로를 적으세요.")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise SystemExit("JUDGE_WORKDIR 폴더가 없음: 먼저 만드세요.")
    path = path.resolve()
    if path == root.resolve() or root.resolve() in path.parents:
        raise SystemExit("JUDGE_WORKDIR가 레포 안임: 레포 밖 폴더로 바꾸세요.")
    return path


DEFAULT_GEMINI_RPM = 4  # 무료 한도: Flash 분당 5회. 하나 아래로 둔다


def resolve_gemini_rpm(cli_value: float | None, env_value: str | None) -> float | None:
    """명령줄 > .env GEMINI_JUDGE_RPM > 기본 4. 0이면 제한 없음(None)."""
    if cli_value is not None:
        value = cli_value
    elif (env_value or "").strip():
        try:
            value = float(env_value)
        except ValueError:
            raise SystemExit("GEMINI_JUDGE_RPM이 숫자가 아님") from None
    else:
        value = DEFAULT_GEMINI_RPM
    return value or None


def _build_specs(names: list[str], workdir: Path, gemini_rpm: float | None):
    """(스펙 목록, 비밀값 목록). 비밀값은 오류 문구 안전망(redact)에만 쓴다."""
    specs: list[JudgeSpec] = []
    secrets: list = []
    for name in names:
        if name == "claude":
            specs.append(JudgeSpec("claude", [None], lambda m: ClaudeJudge(workdir), ping=False))
        elif name == "codex":
            models = _env_list("CODEX_JUDGE_MODELS")
            effort = (os.environ.get("CODEX_JUDGE_EFFORT") or "low").strip()
            if not models:
                specs.append(JudgeSpec("codex", [], lambda m: None, unavailable=".env에 CODEX_JUDGE_MODELS가 없음"))
            else:
                specs.append(JudgeSpec("codex", list(models), lambda m, e=effort: CodexJudge(workdir, str(m), e)))
        elif name == "gemini":
            models = _env_list("GEMINI_JUDGE_MODELS")
            if not models:
                specs.append(JudgeSpec("gemini", [], lambda m: None, unavailable=".env에 GEMINI_JUDGE_MODELS가 없음"))
                continue
            try:
                print("Gemini 키를 금고에서 꺼냅니다. 금고 암호를 직접 입력하세요.", flush=True)
                key = get_secret(GEMINI_ENTRY)
                check_gemini_key_shape(key)
            except KeystoreError as exc:
                specs.append(JudgeSpec("gemini", [], lambda m: None, unavailable=f"금고에서 키를 못 꺼냄: {exc}"))
                continue
            secrets.append(key)
            limiter = RateLimiter(gemini_rpm)
            specs.append(JudgeSpec("gemini", list(models), lambda m, k=key, lim=limiter: GeminiJudge(str(m), k, limiter=lim)))
    return specs, secrets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="면접관 3명으로 평가 결과를 판정한다.")
    ap.add_argument("files", nargs="*", help="_rescored-v2.jsonl 파일들 (--resume이면 생략)")
    ap.add_argument("--judges", default="claude,codex,gemini")
    ap.add_argument("--limit", type=int, default=None, help="N건만 (결과 x 문항 유형에서 골고루, 고정 시드)")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--questions", default="eval/questions.yaml")
    ap.add_argument("--resume", default=None, help="이전 실행 폴더. 판정 불가 건만 같은 모델로 다시 돈다")
    ap.add_argument("--gemini-rpm", type=float, default=None, help="Gemini 분당 요청 수 상한 (기본: .env GEMINI_JUDGE_RPM, 없으면 4. 0이면 제한 없음)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args(argv)

    load_dotenv(_ROOT / ".env")
    workdir = resolve_workdir(os.environ.get("JUDGE_WORKDIR"))  # 아무것도 만들기 전에 확인
    secrets: list = []
    try:
        if args.resume:
            out_dir = Path(args.resume)
            meta = json.loads((out_dir / "inputs.json").read_text(encoding="utf-8"))
            files, names = meta["files"], meta["judges"]
            seed, limit, qpath = meta["seed"], meta["limit"], meta["questions"]
            keep = set(json.loads((out_dir / "run.json").read_text(encoding="utf-8"))["items"])
        else:
            if not args.files:
                ap.error("결과 파일이 필요합니다 (또는 --resume).")
            names = [n.strip() for n in args.judges.split(",") if n.strip()]
            bad = [n for n in names if n not in JUDGE_NAMES]
            if bad or not names:
                ap.error(f"--judges는 {JUDGE_NAMES} 중에서 고르세요.")
            files, seed, limit, qpath, keep = args.files, args.seed, args.limit, args.questions, None
            name = f"{datetime.now():%Y%m%d-%H%M}" + (f"_{args.tag}" if args.tag else "")
            out_dir = JUDGE_DIR / name

        questions = load_questions(qpath)
        records = [r for f in files for r in load_records(f)]
        items = build_items(records, questions)
        items = [it for it in items if it.key in keep] if keep is not None else select_items(items, limit, seed)
        items = shuffle_items(items, seed)
        if not items:
            print("판정할 건이 없습니다.", file=sys.stderr)
            return 1

        out_dir.mkdir(parents=True, exist_ok=True)
        if not args.resume:
            (out_dir / "inputs.json").write_text(
                json.dumps({"files": list(files), "judges": names, "seed": seed, "limit": limit, "questions": qpath},
                           ensure_ascii=False, indent=1), encoding="utf-8")

        # 면접관 실행은 레포 밖 폴더(JUDGE_WORKDIR)에서 한다 (CLAUDE.md, 설정 파일이 섞이지 않게)
        specs, secrets = _build_specs(names, workdir, resolve_gemini_rpm(args.gemini_rpm, os.environ.get("GEMINI_JUDGE_RPM")))
        print(f"대상 {len(items)}건, 면접관 {', '.join(names)}, 결과 폴더 {out_dir}", flush=True)
        stop = threading.Event()
        summary = execute(specs, items, out_dir, seed=seed, resume=bool(args.resume), secrets=tuple(secrets), stop=stop)
        print(summary)
        if stop.is_set():
            print(f"\n중단했습니다. 판정한 건은 저장했습니다. 이어서 돌리려면:\n  python -m src.scripts.eval_judge --resume {out_dir}")
            return 130
        print(f"\n사람이 볼 목록: {out_dir / 'review.md'}")
        return 0
    except Exception as exc:  # 어떤 오류든 키가 섞여 나가지 않게 한 번 더 거른다
        print(f"오류: {redact(f'{type(exc).__name__}: {exc}', *secrets)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

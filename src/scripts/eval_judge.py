"""면접관 자동화 — 평가 결과(_rescored-v2.jsonl)를 Claude, Codex, Gemini 세 면접관이 판정한다.

공식 판정(eval_rescore, manual.yaml)과는 별개인 보조 도구다. 결과는 data/eval/judge/<실행>/ 에 남는다 (git 제외).

    # 첫 실행: 10건만 (Codex 월 한도 가늠). 세 결과에서 골고루, in/not_in 섞어 고정 시드로 뽑는다.
    python -m src.scripts.eval_judge eval/results/A_rescored-v2.jsonl eval/results/B_rescored-v2.jsonl \\
        eval/results/C_rescored-v2.jsonl --judges claude,codex,gemini --limit 10 --tag first10

    # 판정 불가 건만 같은 모델로 다시
    python -m src.scripts.eval_judge --resume data/eval/judge/<실행폴더>

    # 진행 줄에서 판정과 (갈림)을 숨기고 진행 수와 예상 시간만
    python -m src.scripts.eval_judge ... --blind

    # 갈리거나 보류가 있는 건만 토론 (2라운드 + 중재). 기존 실행 폴더의 판정을 1라운드로 쓴다 (ADR-006)
    python -m src.scripts.eval_judge --debate data/eval/judge/<실행폴더> --dry-run
    python -m src.scripts.eval_judge --debate data/eval/judge/<실행폴더> [--arbiter claude:sonnet] [--arbiter-compare] [--blind] [--yes]

    # 판정 호출 없이 review.md, review.html, summary.md 다시 만들기
    python -m src.scripts.eval_judge --rebuild data/eval/judge/<실행폴더>

    # review.html에서 내보낸 내 판정을 실행 폴더의 human.jsonl에 합치기
    python -m src.scripts.eval_judge --import-human data/eval/judge/<실행폴더> human-<실행폴더>.json

금고 암호는 gemini를 쓸 때 시작에 한 번 터미널에서 직접 친다.
모든 면접관(claude 포함)과 토론 중재자는 mala_eval_docs 컬렉션, data/eval_corpus/ 볼트 결과에만 쓴다 (그 밖이거나 알 수 없으면 거부) (judge_guard).
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
    GEMINI_MODEL_RE,
    JUDGE_NAMES,
    ClaudeJudge,
    CodexJudge,
    GeminiJudge,
    JudgeSpec,
    RateLimiter,
    load_rows,
    build_items,
    ensure_blind_map,
    execute,
    finalize,
    pending_counts,
    quiet_http_logs,
    input_fingerprint,
    select_items,
    shuffle_items,
    validate_effort,
    validate_model,
    verify_inputs,
)
from src.eval.judge_guard import check_external_judges
from src.eval.judge_human import HumanImportError, atomic_write_text, import_human
from src.eval.judge_progress import Progress, load_history
from src.eval.judge_web import write_debate_page, write_static
from src.eval.runner import load_questions
from src.keystore import GEMINI_ENTRY, KeystoreError, check_gemini_key_shape, get_secret, redact
from src.scripts.eval_rescore import load_records

_ROOT = Path(__file__).resolve().parents[2]
JUDGE_DIR = _ROOT / "data" / "eval" / "judge"


def _env_list(name: str) -> list[str]:
    return [p.strip() for p in (os.environ.get(name) or "").split(",") if p.strip()]


UNSAFE_PATH_CHARS = frozenset('&|<>^%!"')  # codex.cmd를 cmd.exe가 실행할 때 명령으로 해석되는 글자


def _checked(var: str, check, *args, **kw):
    """검사 함수의 ValueError를 어느 설정이 틀렸는지 알려 주는 SystemExit로 바꾼다 (아무것도 호출하기 전에 멈춘다)."""
    try:
        return check(*args, **kw)
    except ValueError as exc:
        raise SystemExit(f"{var}: {exc}") from None


def resolve_workdir(raw: str | None, root: Path = _ROOT) -> Path:
    """면접관이 실행될 폴더. .env의 JUDGE_WORKDIR에서 읽고, 없거나 레포 안이면 시작 전에 멈춘다.

    레포 안에서 돌리면 CLAUDE.md 같은 파일이 면접관 입력에 섞인다 (파일럿에서 겪음).
    경로가 명령 인자로 들어가므로 & | < > ^ % ! " 와 제어 문자가 있으면 거부한다.
    """
    raw = (raw or "").strip()
    if not raw:
        raise SystemExit(".env에 JUDGE_WORKDIR가 없음: 레포 밖 빈 폴더 경로를 적으세요.")
    bad = sorted({c for c in raw if c in UNSAFE_PATH_CHARS or ord(c) < 32})
    if bad:
        shown = " ".join(repr(c)[1:-1] for c in bad)
        raise SystemExit(f"JUDGE_WORKDIR에 쓸 수 없는 글자가 있음 ({shown}): 이 글자가 없는 폴더 경로로 바꾸세요.")
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
            models = [_checked("CODEX_JUDGE_MODELS", validate_model, m, "codex 모델 이름") for m in _env_list("CODEX_JUDGE_MODELS")]
            effort = _checked("CODEX_JUDGE_EFFORT", validate_effort, (os.environ.get("CODEX_JUDGE_EFFORT") or "low").strip(), "codex effort")
            if not models:
                specs.append(JudgeSpec("codex", [], lambda m: None, unavailable=".env에 CODEX_JUDGE_MODELS가 없음"))
            else:
                specs.append(JudgeSpec("codex", list(models), lambda m, e=effort: CodexJudge(workdir, str(m), e)))
        elif name == "gemini":
            models = [_checked("GEMINI_JUDGE_MODELS", validate_model, m, "gemini 모델 이름", pattern=GEMINI_MODEL_RE)
                      for m in _env_list("GEMINI_JUDGE_MODELS")]  # URL 경로에 들어가므로 키를 꺼내기 전에 검사
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


def _check_inputs(meta: dict) -> None:
    """지문이 다르면 SystemExit, 지문이 없는 옛 폴더면 경고만 한다 (--resume, --rebuild, --debate 공통)."""
    warning = verify_inputs(meta)
    if warning:
        print("경고: " + warning, file=sys.stderr)


def load_folder(out_dir: Path):
    """실행 폴더에서 (items, state, meta)를 다시 만든다. 판정 호출은 하지 않는다."""
    meta = json.loads((out_dir / "inputs.json").read_text(encoding="utf-8"))
    state = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
    _check_inputs(meta)  # 질문 파일이나 채점 지시문이 실행 때와 다르면 여기서 멈춘다
    questions = load_questions(meta["questions"])
    items = build_items([r for f in meta["files"] for r in load_records(f)], questions)
    keep = set(state["items"])
    items = shuffle_items([it for it in items if it.key in keep], meta["seed"])
    return items, state, meta


def rebuild(out_dir: Path) -> str:
    """판정 파일에서 majority, review.md, review.html, summary.md를 다시 쓴다. 기존 번호는 그대로 둔다."""
    items, state, meta = load_folder(out_dir)
    retries_log = out_dir / "retries.log"
    retries = len(retries_log.read_text(encoding="utf-8").splitlines()) if retries_log.exists() else 0
    if state.get("ended") is False:  # 끝나지 않은(강제 종료로 보이는) 실행: 결과 파일은 그대로 두고 화면만 정리한다
        write_static(out_dir, items, ensure_blind_map(out_dir, items), state)
        return ""
    summary = finalize(out_dir, items, state, meta["seed"], retries)
    write_static(out_dir, items, ensure_blind_map(out_dir, items), state)  # 남아 있던 '실행 중' 화면을 정리 (새로 고침 없음)
    return summary


DEFAULT_ARBITER = ("claude", "sonnet")
DEFAULT_ARBITER_EFFORT = "medium"


def resolve_arbiter(cli_value: str | None, env, state_models: dict) -> tuple[str, str | None, str]:
    """중재 모델 설정: 명령줄 `이름[:모델]` > .env의 ARBITER_JUDGE, ARBITER_MODEL, ARBITER_EFFORT > 기본(claude sonnet).
    codex 중재의 effort는 기본 medium. 모델을 안 정한 codex, gemini는 1라운드에 쓴 모델을 쓴다."""
    name, model = DEFAULT_ARBITER
    env_name = (env.get("ARBITER_JUDGE") or "").strip()
    env_model = (env.get("ARBITER_MODEL") or "").strip()
    if env_name:
        name, model = env_name, env_model or None
    elif env_model:
        model = env_model
    if cli_value:
        name, _, m = cli_value.partition(":")
        model = m.strip() or None
    name = name.strip()
    if name not in JUDGE_NAMES:  # 허용 목록: claude, codex, gemini만 (대소문자, 덧붙은 글자도 거부)
        raise SystemExit(f"중재 면접관은 {JUDGE_NAMES} 중에서 고르세요: {name[:40]!r}")
    if name == "claude":
        model = model or "sonnet"
    else:
        model = model or state_models.get(name)
    effort = (env.get("ARBITER_EFFORT") or "").strip() or DEFAULT_ARBITER_EFFORT
    if model is not None:
        model = _checked("ARBITER_MODEL 또는 --arbiter", validate_model, model, "중재 모델 이름")
    _checked("ARBITER_EFFORT", validate_effort, effort, "중재 effort")
    return name, model, effort


def compare_arbiter(primary: str, state_models: dict, env=None) -> tuple[str, str | None, str]:
    """다른 계열 중재자: claude이면 codex(effort medium), 그 밖이면 claude sonnet. 계열 편향을 보려는 비교용이다."""
    if primary == "claude":
        models = _env_list("CODEX_JUDGE_MODELS")
        model = state_models.get("codex") or (models[0] if models else None)
        if model is not None:
            model = _checked("비교 중재 모델(CODEX_JUDGE_MODELS)", validate_model, model, "codex 모델 이름")
        return "codex", model, DEFAULT_ARBITER_EFFORT
    return "claude", "sonnet", DEFAULT_ARBITER_EFFORT


def debate_main(args) -> int:
    from src.eval.debate import estimate, format_estimate, run_debate, select_candidates
    from src.eval.debate_report import write_report

    out_dir = Path(args.debate)
    items, state, meta = load_folder(out_dir)
    names = [n for n in JUDGE_NAMES if state["judges"].get(n, {}).get("status") not in (None, "skipped")]
    if len(names) < 3:
        print(f"토론은 면접관 3명의 1라운드 판정이 필요합니다 (지금: {', '.join(names) or '없음'}).", file=sys.stderr)
        return 1
    r1 = {n: load_rows(out_dir / f"judge_{n}.jsonl") for n in names}
    groups = select_candidates(items, r1, names)
    models = {n: state["judges"][n].get("model") for n in names}
    load_dotenv(_ROOT / ".env")
    arb = resolve_arbiter(args.arbiter, os.environ, models)
    cmp_ = compare_arbiter(arb[0], models, os.environ) if args.arbiter_compare else None
    # 안전장치: 키를 꺼내기 전에 입력의 출처를 본다 (1라운드 면접관과 중재자 모두, mala_eval_docs 결과만)
    check_external_judges(list(meta["files"]), names + [arb[0]] + ([cmp_[0]] if cmp_ else []), _ROOT)
    rpm = resolve_gemini_rpm(args.gemini_rpm, os.environ.get("GEMINI_JUDGE_RPM"))
    est = estimate(items, groups, r1, names, gemini_rpm=rpm, arbiter_names=[arb[0]] + ([cmp_[0]] if cmp_ else []))
    desc = f"중재: {arb[0]} {arb[1] or '(기본 모델)'}" + (f" (effort {arb[2]})" if arb[0] == "codex" else "")
    if cmp_:
        desc += f" / 비교 중재: {cmp_[0]} {cmp_[1] or '(기본 모델)'}" + (f" (effort {cmp_[2]})" if cmp_[0] == "codex" else "")
    print(format_estimate(est) + "\n" + desc, flush=True)
    if args.dry_run:
        print("(--dry-run: 호출하지 않았습니다)")
        return 0
    if not groups["candidates"]:
        print("토론할 건이 없습니다.")
        return 0
    if not args.yes:
        try:
            ok = input("계속할까요? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            ok = False
        if not ok:
            print("취소했습니다. 아무것도 호출하지 않았습니다.")
            return 1
    workdir = resolve_workdir(os.environ.get("JUDGE_WORKDIR"))
    secrets: list = []
    try:
        need = list(names)
        for extra in [arb[0]] + ([cmp_[0]] if cmp_ else []):
            if extra == "gemini" and "gemini" not in need:
                need.append("gemini")
        specs, secrets = _build_specs(need, workdir, rpm)
        by_name = {sp.name: sp for sp in specs}
        bad = [n for n in need if by_name[n].unavailable]
        if bad:
            print("쓸 수 없는 면접관: " + ", ".join(f"{n} ({by_name[n].unavailable})" for n in bad), file=sys.stderr)
            return 1
        judges = {n: by_name[n].make(models.get(n)) for n in names}

        def make_arb(cfg):
            name, model, eff = cfg
            if name == "claude":
                return ClaudeJudge(workdir, model=model or "sonnet")
            if name == "codex":
                return CodexJudge(workdir, str(model), eff)
            return by_name["gemini"].make(model)

        stop = threading.Event()
        ids = ensure_blind_map(out_dir, items)
        run_state = dict(state)
        run_state["blind"] = bool(args.blind or state.get("blind", True))

        def page() -> None:
            write_debate_page(out_dir, items, ids, run_state, running=True)

        result = run_debate(out_dir, items, state, judges=judges, arbiter=(arb[0], make_arb(arb)),
                            compare=((cmp_[0], make_arb(cmp_)) if cmp_ else None), stop=stop, blind=run_state["blind"], page=page,
                            estimate_info=est)
        write_debate_page(out_dir, items, ids, run_state, running=False)
        if result["interrupted"]:
            print(f"\n중단했습니다. 쓴 줄은 남아 있습니다. 이어서 하려면:\n  python -m src.scripts.eval_judge --debate {out_dir}")
            return 130
        write_report(out_dir, items, names)
        rebuild(out_dir)  # review.html, 사람이 볼 목록, progress.html에 토론 결과를 반영한다
        final = result["final"]
        print(f"토론이 끝났습니다. 소수가 이긴 건 {sum(1 for f in final if f['minority_won'])}, 끝까지 갈린 건 {sum(1 for f in final if f['unresolved'])}")
        print(f"보고서: {out_dir / 'debate' / 'report.md'}\n결과 보기 화면: {out_dir / 'review.html'}")
        return 0
    except Exception as exc:  # 어떤 오류든 키가 섞여 나가지 않게 한 번 더 거른다
        print(f"오류: {redact(f'{type(exc).__name__}: {exc}', *secrets)}", file=sys.stderr)
        return 1


def folder_problem(raw: str, *, need_run_files: bool = True) -> str | None:
    """실행 폴더로 쓸 수 없으면 짧은 안내 문구, 쓸 수 있으면 None (OSError 대신 보여 준다)."""
    p = Path(raw)
    if not p.is_dir():
        return f"폴더가 없습니다: {raw}"
    if need_run_files:
        missing = [n for n in ("inputs.json", "run.json") if not (p / n).is_file()]
        if missing:
            return f"실행 폴더가 아닙니다 ({', '.join(missing)}이 없음): {raw}"
    return None


def _open_page(path: Path) -> None:
    """progress.html을 기본 브라우저로 연다. 실패해도 실행은 계속한다."""
    try:
        import webbrowser

        webbrowser.open(path.resolve().as_uri())
    except Exception:  # noqa: BLE001 - 브라우저가 없어도 판정은 해야 한다
        print("브라우저를 열지 못했습니다. 직접 여세요:", path, flush=True)


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
    ap.add_argument("--blind", action="store_true", help="진행 줄에서 판정과 (갈림)을 숨기고 진행 수와 예상 시간만 보여 준다")
    ap.add_argument("--open", action="store_true", help="시작할 때 progress.html을 기본 브라우저로 연다 (실행 중 진행 상황, 5초마다 새로 고침)")
    ap.add_argument("--debate", default=None, metavar="실행폴더", help="갈리거나 보류가 있는 건만 토론한다 (2라운드 + 중재). 그 폴더의 판정이 1라운드")
    ap.add_argument("--dry-run", action="store_true", help="--debate: 호출하지 않고 대상 건 수와 예상 호출 수, 토큰만 보여 준다")
    ap.add_argument("--yes", action="store_true", help="--debate: 시작 확인 질문을 생략한다")
    ap.add_argument("--arbiter", default=None, metavar="이름[:모델]", help="--debate: 중재 면접관 (기본 claude:sonnet, 또는 .env의 ARBITER_JUDGE, ARBITER_MODEL)")
    ap.add_argument("--arbiter-compare", action="store_true", help="--debate: 다른 계열 중재자(claude↔codex medium)로도 돌려 결정이 달라지는지 비교한다 (결정에는 안 씀)")
    ap.add_argument("--rebuild", default=None, metavar="실행폴더", help="판정 호출 없이 review.md, review.html, summary.md를 다시 만든다")
    ap.add_argument("--import-human", nargs=2, default=None, metavar=("실행폴더", "내보낸.json"),
                    help="review.html에서 내보낸 내 판정을 human.jsonl에 합치고 요약을 다시 만든다")
    args = ap.parse_args(argv)
    quiet_http_logs()

    problem = None
    if args.rebuild:
        problem = folder_problem(args.rebuild)
    elif args.import_human:
        problem = folder_problem(args.import_human[0], need_run_files=False)
        if problem is None and not Path(args.import_human[1]).is_file():
            problem = f"파일이 없습니다: {args.import_human[1]}"
    elif args.resume:
        problem = folder_problem(args.resume)
    elif args.debate:
        problem = folder_problem(args.debate)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    if args.debate:
        return debate_main(args)

    if args.rebuild or args.import_human:  # 면접관을 부르지 않는 작업: 작업 폴더, 키가 필요 없다
        try:
            if args.import_human:
                folder, export = Path(args.import_human[0]), args.import_human[1]
                count = import_human(folder, export)
                print(f"사람 판정 {count}건을 합쳤습니다.")
            else:
                folder = Path(args.rebuild)
            summary = rebuild(folder)
            if not summary:
                print(f"이 실행은 끝나지 않았습니다 (강제 종료로 보임). progress.html만 고쳤습니다: {folder / 'progress.html'}\n"
                      f"이어서 돌리려면:\n  python -m src.scripts.eval_judge --resume {folder}")
                return 0
            print(f"다시 만들었습니다: {folder / 'summary.md'}, {folder / 'review.html'}, {folder / 'progress.html'}")
            return 0
        except HumanImportError as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"오류: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    load_dotenv(_ROOT / ".env")
    workdir = resolve_workdir(os.environ.get("JUDGE_WORKDIR"))  # 아무것도 만들기 전에 확인
    secrets: list = []
    try:
        if args.resume:
            out_dir = Path(args.resume)
            meta = json.loads((out_dir / "inputs.json").read_text(encoding="utf-8"))
            _check_inputs(meta)  # 키를 꺼내거나 아무것도 쓰기 전에 (다르면 멈춤)
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

        # 안전장치: 키를 꺼내거나 폴더를 만들기 전에 입력의 출처를 본다
        check_external_judges(list(files), names, _ROOT)

        out_dir.mkdir(parents=True, exist_ok=True)
        if args.resume:  # 키 입력을 기다리는 동안 남아 있던 '실행 중' 화면부터 지금 상태로 정리한다
            old = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
            write_static(out_dir, items, ensure_blind_map(out_dir, items), old)
        if not args.resume:
            atomic_write_text(out_dir / "inputs.json", json.dumps(
                {"files": list(files), "judges": names, "seed": seed, "limit": limit, "questions": qpath,
                 **input_fingerprint(qpath, list(files))}, ensure_ascii=False, indent=1))

        # 면접관 실행은 레포 밖 폴더(JUDGE_WORKDIR)에서 한다 (CLAUDE.md, 설정 파일이 섞이지 않게)
        specs, secrets = _build_specs(names, workdir, resolve_gemini_rpm(args.gemini_rpm, os.environ.get("GEMINI_JUDGE_RPM")))
        print(f"대상 {len(items)}건, 면접관 {', '.join(names)}, 결과 폴더 {out_dir}", flush=True)
        stop = threading.Event()
        ids = ensure_blind_map(out_dir, items)
        gemini_rpm = resolve_gemini_rpm(args.gemini_rpm, os.environ.get("GEMINI_JUDGE_RPM"))
        progress = Progress(
            items, ids, names, blind=args.blind,
            expect=load_history(JUDGE_DIR, out_dir, names),
            min_sec={"gemini": 60.0 / gemini_rpm} if gemini_rpm else None,
        )
        print(progress.start_line(pending_counts(out_dir, items, names)), flush=True)
        summary = execute(specs, items, out_dir, seed=seed, resume=bool(args.resume), secrets=tuple(secrets), stop=stop, progress=progress,
                          on_page=(lambda: _open_page(out_dir / "progress.html")) if args.open else None)
        print(summary)
        if stop.is_set():
            print(f"\n중단했습니다. 판정한 건은 저장했습니다. 이어서 돌리려면:\n  python -m src.scripts.eval_judge --resume {out_dir}")
            return 130
        print(f"\n사람이 볼 목록: {out_dir / 'review.md'}\n결과 보기 화면: {out_dir / 'review.html'}")
        return 0
    except Exception as exc:  # 어떤 오류든 키가 섞여 나가지 않게 한 번 더 거른다
        print(f"오류: {redact(f'{type(exc).__name__}: {exc}', *secrets)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

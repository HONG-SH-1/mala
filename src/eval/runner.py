"""0단계 평가 러너 — 지금 코드를 고치지 않고 바깥에서 감싸서 잰다.

study 모드(--inline)와 같은 경로로 질문을 보내고, Ollama 호출만 가로채
토큰과 시간을 기록한다. src 아래 기존 파일은 한 줄도 바꾸지 않는다.
그래야 이 결과를 '고치기 전' 기준선으로 쓸 수 있다.
"""

from __future__ import annotations

import json
import platform
import re
import statistics
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import yaml

from src.agents import nodes as _nodes
from src.config import Settings

QUESTION_TYPES = ("in_notes", "not_in_notes")

# 노트에 없는 질문에 "모른다"고 답했는지 보는 표시어. 자동 판정용이라 거칠다.
DONT_KNOW_MARKERS = (
    "모르",
    "알 수 없",
    "찾을 수 없",
    "나와 있지 않",
    "언급되어 있지 않",
    "언급되지 않",
    "정보가 없",
    "내용이 없",
    "not in the notes",
    "not mentioned",
    "do not know",
    "don't know",
    "no information",
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class Question:
    id: str
    question: str
    type: str
    expected_sources: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)


def load_questions(path: str | Path) -> list[Question]:
    """YAML 질문 파일을 읽고 형식을 검사한다. 문제가 있으면 전부 모아서 한 번에 알린다."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("질문 파일은 비어 있지 않은 목록이어야 합니다.")

    errors: list[str] = []
    questions: list[Question] = []
    seen: set[str] = set()
    for i, item in enumerate(raw, 1):
        where = f"{i}번째 항목"
        if not isinstance(item, dict):
            errors.append(f"{where}: 키-값 형식이 아닙니다.")
            continue
        qid = str(item.get("id", "")).strip()
        text = str(item.get("question", "")).strip()
        qtype = str(item.get("type", "")).strip()
        sources = [str(s) for s in item.get("expected_sources") or []]
        keywords = [str(k) for k in item.get("must_include") or []]

        if not qid:
            errors.append(f"{where}: id가 없습니다.")
        elif qid in seen:
            errors.append(f"{where}: id '{qid}'가 중복입니다.")
        seen.add(qid)
        if not text:
            errors.append(f"{where} ({qid}): question이 없습니다.")
        if qtype not in QUESTION_TYPES:
            errors.append(
                f"{where} ({qid}): type은 {QUESTION_TYPES} 중 하나여야 합니다."
            )
        if qtype == "in_notes" and not sources:
            errors.append(
                f"{where} ({qid}): in_notes 질문은 expected_sources가 필요합니다."
            )
        questions.append(Question(qid, text, qtype, sources, keywords))

    if errors:
        raise ValueError("질문 파일 오류:\n- " + "\n- ".join(errors))
    return questions


def strip_think(text: str) -> str:
    """qwen3 thinking 블록을 빼고 실제 답만 남긴다 (fix-later 7번 관련)."""
    return _THINK_RE.sub("", text or "").strip()


def _norm_path(p: str) -> str:
    return p.replace("\\", "/").strip().lstrip("./").lower()


def source_hit(expected: list[str], retrieved: list[str]) -> bool:
    """기대한 노트 중 하나라도 검색 결과에 들어왔는지. 경로 끝부분이 맞으면 같다고 본다."""
    got = [_norm_path(r) for r in retrieved]
    for e in expected:
        want = _norm_path(e)
        if any(g == want or g.endswith("/" + want) for g in got):
            return True
    return False


def auto_verdict(q: Question, answer: str) -> bool | None:
    """키워드로 정답 여부를 자동 판정한다. 판정 기준이 없으면 None(사람이 봐야 함)."""
    text = answer.lower()
    if q.type == "not_in_notes":
        return any(m.lower() in text for m in DONT_KNOW_MARKERS)
    if not q.must_include:
        return None
    return all(k.lower() in text for k in q.must_include)


class OllamaRecorder:
    """call_ollama를 감싸서 호출마다 시간과 토큰을 남긴다. 응답은 그대로 돌려준다."""

    def __init__(self, inner: Callable[..., dict]) -> None:
        self._inner = inner
        self.calls: list[dict] = []

    def reset(self) -> None:
        self.calls = []

    def __call__(self, prompt: str, settings: Settings) -> dict:
        start = time.perf_counter()
        try:
            result = self._inner(prompt, settings)
        except Exception as exc:
            self.calls.append(
                {
                    "wall_ms": round((time.perf_counter() - start) * 1000),
                    "error": str(exc),
                }
            )
            raise
        self.calls.append(
            {
                "wall_ms": round((time.perf_counter() - start) * 1000),
                "prompt_tokens": result.get("prompt_eval_count"),
                "output_tokens": result.get("eval_count"),
                "total_ms": _ns_to_ms(result.get("total_duration")),
                "load_ms": _ns_to_ms(result.get("load_duration")),
            }
        )
        return result


def _ns_to_ms(value) -> int | None:
    return None if value is None else round(value / 1_000_000)


@contextmanager
def recording_ollama(inner: Callable[..., dict] | None = None) -> Iterator[OllamaRecorder]:
    """nodes 모듈이 쓰는 call_ollama만 잠깐 바꿔 끼우고, 끝나면 반드시 원래대로 돌린다."""
    original = _nodes.call_ollama
    recorder = OllamaRecorder(inner or original)
    _nodes.call_ollama = recorder
    try:
        yield recorder
    finally:
        _nodes.call_ollama = original


def default_run_fn(settings: Settings) -> Callable[[str], dict]:
    """study_once --inline과 같은 경로: 항상 노트 검색, worker 없이 직접 호출."""
    from src.agents.graph import run_task

    def _run(text: str) -> dict:
        return run_task(
            text,
            use_queue=False,
            settings=settings,
            use_hermes_router=False,
            force_vault_rag=True,
        )

    return _run


def _sum(calls: list[dict], key: str) -> int | None:
    values = [c[key] for c in calls if c.get(key) is not None]
    return sum(values) if values else None


def run_one(
    q: Question,
    run_fn: Callable[[str], dict],
    recorder: OllamaRecorder,
    *,
    label: str,
    repeat_idx: int,
) -> dict:
    recorder.reset()
    start = time.perf_counter()
    error = None
    try:
        final = run_fn(q.question)
    except Exception as exc:  # 한 문항이 실패해도 나머지는 계속 잰다
        final = {}
        error = str(exc)
    wall_ms = round((time.perf_counter() - start) * 1000)

    raw_answer = final.get("answer") or ""
    answer = strip_think(raw_answer)
    sources = [c.get("source", "") for c in final.get("retrieved_chunks") or []]
    calls = list(recorder.calls)

    return {
        "label": label,
        "repeat": repeat_idx,
        "id": q.id,
        "type": q.type,
        "question": q.question,
        "answer": answer,
        "raw_answer_chars": len(raw_answer),
        "had_think_block": answer != raw_answer.strip(),
        "valid": bool(final.get("valid")),
        "history": final.get("history", []),
        "retrieved_sources": sources,
        "source_hit": source_hit(q.expected_sources, sources)
        if q.type == "in_notes"
        else None,
        "auto_correct": auto_verdict(q, answer),
        "manual_correct": None,  # 사람이 나중에 채우는 칸
        "ollama_calls": len(calls),
        "prompt_tokens": _sum(calls, "prompt_tokens"),
        "output_tokens": _sum(calls, "output_tokens"),
        "ollama_total_ms": _sum(calls, "total_ms"),
        "load_ms": _sum(calls, "load_ms"),
        "wall_ms": wall_ms,
        "error": error or (None if final.get("valid") else final.get("last_error")),
    }


def run_eval(
    questions: list[Question],
    *,
    run_fn: Callable[[str], dict],
    label: str,
    repeat: int = 1,
    inner_ollama: Callable[..., dict] | None = None,
    on_record: Callable[[dict], None] | None = None,
) -> list[dict]:
    records: list[dict] = []
    with recording_ollama(inner_ollama) as recorder:
        for r in range(1, repeat + 1):
            for q in questions:
                rec = run_one(q, run_fn, recorder, label=label, repeat_idx=r)
                records.append(rec)
                if on_record:
                    on_record(rec)
    return records


def _rate(values: list[bool | None]) -> tuple[float | None, int]:
    judged = [v for v in values if v is not None]
    if not judged:
        return None, 0
    return sum(judged) / len(judged), len(judged)


def summarize(records: list[dict]) -> dict:
    first = [r for r in records if r["repeat"] == 1]
    in_notes = [r for r in first if r["type"] == "in_notes"]
    not_in = [r for r in first if r["type"] == "not_in_notes"]

    correct, judged = _rate([r["auto_correct"] for r in first])
    in_correct, _ = _rate([r["auto_correct"] for r in in_notes])
    out_correct, _ = _rate([r["auto_correct"] for r in not_in])
    hit, _ = _rate([r["source_hit"] for r in in_notes])

    walls = [r["wall_ms"] for r in first]
    prompt_t = [r["prompt_tokens"] for r in first if r["prompt_tokens"] is not None]
    out_t = [r["output_tokens"] for r in first if r["output_tokens"] is not None]

    summary = {
        "questions": len(first),
        "repeats": max((r["repeat"] for r in records), default=0),
        "auto_correct_rate": correct,
        "auto_judged": judged,
        "needs_manual": len(first) - judged,
        "in_notes_correct_rate": in_correct,
        "not_in_notes_correct_rate": out_correct,
        "source_hit_rate": hit,
        "wall_ms_median": statistics.median(walls) if walls else None,
        "wall_ms_max": max(walls) if walls else None,
        "prompt_tokens_mean": statistics.mean(prompt_t) if prompt_t else None,
        "output_tokens_mean": statistics.mean(out_t) if out_t else None,
        "retried_questions": sum(1 for r in first if r["ollama_calls"] > 1),
        "failed_questions": sum(1 for r in first if not r["valid"]),
        "think_block_questions": sum(1 for r in first if r["had_think_block"]),
    }

    if summary["repeats"] >= 2:
        by_id: dict[str, list[dict]] = {}
        for r in records:
            by_id.setdefault(r["id"], []).append(r)
        same_verdict = [
            len({r["auto_correct"] for r in rs}) == 1 for rs in by_id.values()
        ]
        same_text = [len({r["answer"] for r in rs}) == 1 for rs in by_id.values()]
        summary["same_verdict_rate"] = sum(same_verdict) / len(same_verdict)
        summary["same_answer_text_rate"] = sum(same_text) / len(same_text)

    return summary


def run_meta(settings: Settings, *, label: str, questions_path: str) -> dict:
    root = settings.project_root
    return {
        "label": label,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": _git(root, "rev-parse", "--short", "HEAD"),
        "git_dirty_src": bool(_git(root, "status", "--porcelain", "--", "src")),
        "answer_model": settings.ollama_model,
        "embed_model": settings.ollama_embed_model,
        "rag_top_k": settings.rag_top_k,
        "graph_max_retries": settings.graph_max_retries,
        "questions_file": questions_path,
        "python": platform.python_version(),
    }


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


def _num(v: float | None, unit: str = "") -> str:
    return "-" if v is None else f"{v:,.0f}{unit}"


def render_markdown(meta: dict, summary: dict, records: list[dict]) -> str:
    lines = [
        f"# 평가 결과: {meta['label']}",
        "",
        f"- 시각: {meta['started_at']}",
        f"- 커밋: {meta['git_commit']}"
        + (" (src에 커밋 안 된 변경 있음)" if meta["git_dirty_src"] else ""),
        f"- 답변 모델: {meta['answer_model']}, 임베딩: {meta['embed_model']}, "
        f"TOP_K: {meta['rag_top_k']}",
        f"- 질문 {summary['questions']}개 x {summary['repeats']}회",
        "",
        "| 지표 | 값 |",
        "| --- | --- |",
        f"| 정답률 (자동 판정) | {_pct(summary['auto_correct_rate'])} "
        f"({summary['auto_judged']}개 판정, {summary['needs_manual']}개는 수동 확인 필요) |",
        f"| 노트에 있는 질문 정답률 | {_pct(summary['in_notes_correct_rate'])} |",
        f"| 노트에 없는 질문에 '모른다' | {_pct(summary['not_in_notes_correct_rate'])} |",
        f"| 출처 일치율 | {_pct(summary['source_hit_rate'])} |",
        f"| 응답 시간 중앙값 | {_num(summary['wall_ms_median'], 'ms')} |",
        f"| 응답 시간 최대 | {_num(summary['wall_ms_max'], 'ms')} |",
        f"| 입력 토큰 평균 | {_num(summary['prompt_tokens_mean'])} |",
        f"| 출력 토큰 평균 | {_num(summary['output_tokens_mean'])} |",
        f"| 재시도가 일어난 질문 | {summary['retried_questions']}개 |",
        f"| 검증 실패로 끝난 질문 | {summary['failed_questions']}개 |",
        f"| thinking 블록이 섞인 답 | {summary['think_block_questions']}개 |",
    ]
    if "same_verdict_rate" in summary:
        lines += [
            f"| 반복 시 판정이 같은 비율 | {_pct(summary['same_verdict_rate'])} |",
            f"| 반복 시 답이 글자까지 같은 비율 | {_pct(summary['same_answer_text_rate'])} |",
        ]
    lines += [
        "",
        "## 문항별 (1회차)",
        "",
        "| id | 유형 | 자동 판정 | 출처 | 시간 | 출력 토큰 | 호출 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    mark = {True: "O", False: "X", None: "?"}
    for r in records:
        if r["repeat"] != 1:
            continue
        lines.append(
            f"| {r['id']} | {r['type']} | {mark[r['auto_correct']]} | "
            f"{mark[r['source_hit']] if r['type'] == 'in_notes' else '-'} | "
            f"{_num(r['wall_ms'], 'ms')} | {_num(r['output_tokens'])} | {r['ollama_calls']} |"
        )
    lines += [
        "",
        "첫 문항은 모델 로드 시간이 섞일 수 있습니다 (load_ms 확인).",
        "자동 판정은 키워드 기준이라 거칩니다. jsonl의 manual_correct 칸으로 직접 확인하세요.",
    ]
    return "\n".join(lines) + "\n"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

"""progress.html — 서버 없이 브라우저로 보는 실행 진행 상황.

- 실행 중에 결과 폴더의 progress.html을 몇 초마다 새로 쓴다. 임시 파일에 쓰고 os.replace로 바꿔 끼워서 반쯤 쓴 파일이 보이지 않는다.
- 페이지는 <meta http-equiv="refresh">로 스스로 새로 고친다 (실행 중일 때만). 스크립트, 서버, 포트, 외부 요청 없음.
  CSP는 review.html과 같은 수준: default-src 'none', 인라인 스타일은 해시로만.
- 맨 위에 "마지막 갱신 시각"을 크게 보여 준다. 창을 닫아 강제로 끝난 실행은 '실행 중'으로 남아 계속 새로 고칠 수 있는데,
  스크립트가 없어 화면이 스스로 알 수 없다. 사람이 시각이 멈춘 것을 보고 알아채게 한다.
- 답 본문, 이유 글, 질문 본문, 결과 라벨, 파일 이름은 넣지 않는다 (번호, 질문 id, 회차만). blind면 판정과 갈림은 데이터 자체를 넣지 않는다.
- 모든 글자는 html.escape로 이스케이프한다.

judge.py를 가져오지 않는다 (순환 방지). 판정 파일(judge_*.jsonl)을 직접 읽는다.
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.eval.judge_human import atomic_write_text
from src.eval.judge_report import csp_hash
from src.eval.md_mini import parse_markdown

PAGE_NAME = "progress.html"
SUMMARY_HTML = "summary.html"
NAV = (("progress.html", "진행 화면"), ("review.html", "결과 보기"), ("summary.html", "요약"))
TEMPLATE = Path(__file__).parent / "templates" / "progress.html"
PROGRESS_PAGE_SECONDS = 5.0  # 실행 중 새로 쓰는 간격이자 브라우저가 새로 고치는 간격
RECENT_COUNT = 10
UNAVAILABLE = "판정불가"
MAX_NOTE = 90

_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.S)


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def read_rows(path: Path) -> dict[str, dict]:
    """judge_*.jsonl을 키마다 마지막 줄만. 쓰는 중인 반쪽 줄이나 깨진 줄은 건너뛴다."""
    rows: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and isinstance(r.get("key"), str) and "verdict" in r:
                rows[r["key"]] = r
    return rows


def snapshot(out_dir: Path, items, ids: dict[str, str], names: list[str], inactive: set[str],
             order: list[str] | None = None) -> dict:
    """판정 파일에서 지금 상태를 모은다. order는 건이 끝난 순서(없으면 실행 순서)."""
    rows = {n: read_rows(out_dir / f"judge_{n}.jsonl") for n in names}
    keys = [it.key for it in items]
    info = {it.key: (ids[it.key], it.qid, it.repeat) for it in items}
    judges = []
    for n in names:
        rs = rows[n]
        mine = [k for k in keys if k in rs]
        secs = [float(rs[k]["sec"]) for k in mine
                if isinstance(rs[k].get("sec"), (int, float)) and rs[k]["verdict"] != UNAVAILABLE]
        judges.append({"name": n, "done": len(mine), "unavailable": sum(1 for k in mine if rs[k]["verdict"] == UNAVAILABLE),
                       "avg": (sum(secs) / len(secs)) if secs else None})
    active = [n for n in names if n not in inactive]
    done_keys = {k for k in keys if active and all(k in rows[n] for n in active)}
    seq = [k for k in (order if order is not None else keys) if k in done_keys]
    recent = []
    for k in reversed(seq[-RECENT_COUNT:]):
        vs = {n: rows[n][k]["verdict"] for n in active if k in rows[n]}
        recent.append({"bid": info[k][0], "qid": info[k][1], "repeat": info[k][2], "verdicts": vs,
                       "split": "합격" in vs.values() and "불합격" in vs.values()})
    return {"total": len(keys), "completed": len(done_keys), "judges": judges, "recent": recent}


def overall_status(phase: str, infos: dict[str, dict], names: list[str], *, interrupted: bool, killed: bool,
                   completed: int, total: int) -> tuple[str, str]:
    """(상태 문구, 종류). 종류: running | done | stopped"""
    if phase == "running":
        return "실행 중", "running"
    if interrupted:
        return "멈춤 (Ctrl+C)", "stopped"
    if killed:
        return "멈춤 (강제 종료로 보임)", "stopped"
    stopped = [infos[n] for n in names if infos.get(n, {}).get("status") == "stopped"]
    if stopped:
        why = str(stopped[0].get("stopped") or "")
        return ("멈춤 (하루 한도)" if "하루 한도" in why else f"멈춤 ({why[:MAX_NOTE]})"), "stopped"
    if names and all(infos.get(n, {}).get("status") == "skipped" for n in names):
        return "멈춤 (쓸 수 있는 면접관 없음)", "stopped"
    if completed >= total:
        return "끝남", "done"
    return "끝남 (판정 불가 있음)", "done"


def judge_label(info: dict | None) -> str:
    if not info:
        return "진행 중"
    st = info.get("status")
    if st == "skipped":
        return "건너뜀: " + str(info.get("reason") or "")[:MAX_NOTE]
    if st == "stopped":
        return "멈춤: " + str(info.get("stopped") or "")[:MAX_NOTE]
    return "끝남"


def _vcls(v: str) -> str:
    return "pass" if v == "합격" else "fail" if v == "불합격" else "hold"


def nav_html(current: str, available: set[str] | None = None) -> str:
    """세 화면 맨 위의 이동 줄. 같은 폴더 상대 링크. 아직 없는 파일은 링크 없이 흐리게."""
    parts = []
    for fname, label in NAV:
        if fname == current:
            parts.append(f"<b>{esc(label)}</b>")
        elif available is None or fname in available:
            parts.append(f'<a href="{fname}">{esc(label)}</a>')
        else:
            parts.append(f'<span class="off">{esc(label)}</span>')
    return '<nav class="nav">' + "".join(parts) + "</nav>"


def render(data: dict) -> str:
    """data: run, phase, status, kind, stamp, total, completed, eta, retries, judges, recent, blind, started, links.
    judges[i]에는 name, done, unavailable, avg, label."""
    total, completed = data["total"], data["completed"]
    pct = int(completed * 100 / total) if total else 0
    body: list[str] = []
    avail = {"progress.html"} | ({"review.html", "summary.html"} if data["links"] else set())
    body.append(nav_html("progress.html", avail))
    body.append(f'<div class="stamp"><small>마지막 갱신</small>{esc(data["stamp"])}</div>')
    if data["kind"] == "running":
        body.append('<div class="note">이 시각이 한참 지났는데도 \'실행 중\'이면, 창을 닫아 강제로 끝난 실행일 수 있습니다. '
                    '화면은 스스로 알 수 없어서 시각을 보고 판단해야 합니다.</div>')
    body.append('<div class="card">')
    cls = "running" if data["kind"] == "running" else "done"
    eta = data["eta"] if data["kind"] == "running" else "-"
    body.append(f'<div class="summary"><span class="badge {cls}">{esc(data["status"])}</span> {completed}/{total} ({pct}%)'
                f' · 남은 예상 {esc(eta)} · 재시도 {int(data["retries"])}회</div>')
    body.append(f'<progress value="{completed}" max="{max(total, 1)}"></progress>')
    if data["kind"] != "running":
        body.append('<div class="note">새로 고침을 멈췄습니다.</div>')
        if data["links"]:
            body.append('<div class="links"><a href="review.html">결과 보기 (review.html)</a><a href="summary.html">요약 (summary.html)</a></div>')
    body.append("</div>")

    body.append('<div class="card"><h2>면접관별</h2><table><tr><th>면접관</th><th>끝난 수</th><th>건당 평균</th><th>상태</th></tr>')
    for j in data["judges"]:
        avg = f'{j["avg"]:.1f}초' if j["avg"] is not None else "-"
        un = f' <span class="muted">(판정불가 {j["unavailable"]})</span>' if j["unavailable"] else ""
        body.append(f'<tr><td>{esc(j["name"])}</td><td>{j["done"]}/{total}{un}</td><td>{avg}</td><td>{esc(j["label"])}</td></tr>')
    body.append("</table></div>")

    names = [j["name"] for j in data["judges"]]
    body.append(f'<div class="card"><h2>최근 {RECENT_COUNT}건 (면접관이 모두 끝낸 순)</h2>')
    if not data["recent"]:
        body.append('<div class="muted">아직 없음</div>')
    else:
        head = "<th>번호</th><th>질문</th><th>회차</th>"
        if not data["blind"]:
            head += "".join(f"<th>{esc(n)}</th>" for n in names) + "<th>갈림</th>"
        body.append(f"<table><tr>{head}</tr>")
        for r in data["recent"]:
            row = f'<td>{esc(r["bid"])}</td><td>{esc(r["qid"])}</td><td>{int(r["repeat"])}회차</td>'
            if not data["blind"]:
                for n in names:
                    v = r["verdicts"].get(n)
                    row += f'<td class="{_vcls(v)}">{esc(v)}</td>' if v else '<td class="muted">-</td>'
                row += "<td>갈림</td>" if r["split"] else "<td></td>"
            body.append(f"<tr>{row}</tr>")
        body.append("</table>")
        if data["blind"]:
            body.append('<div class="note">--blind: 면접관별 결과는 이 화면에 넣지 않았습니다.</div>')
    body.append("</div>")
    body.append(f'<div class="foot">결과 폴더 {esc(data["run"])} · 시작 {esc(data["started"])}</div>')

    tpl = TEMPLATE.read_text(encoding="utf-8")
    style = _STYLE_RE.search(tpl)
    if not style:
        raise ValueError("progress 템플릿에 <style> 블록이 없습니다.")
    refresh = f'<meta http-equiv="refresh" content="{int(PROGRESS_PAGE_SECONDS)}">\n' if data["kind"] == "running" else ""
    return (tpl.replace("__STYLE_HASH__", csp_hash(style.group(1))).replace("__REFRESH__", refresh)
            .replace("__TITLE__", "면접관 진행 상황").replace("__BODY__", "\n".join(body)))


def _mtime_text(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def build_data(out_dir: Path, items, ids: dict[str, str], names: list[str], infos: dict[str, dict], *, phase: str,
               interrupted: bool, killed: bool, blind: bool, retries: int, started: str, stamp: datetime,
               eta: str = "계산 중", order: list[str] | None = None, expect_outputs: bool = False) -> dict:
    # 건너뜀은 시작도 못 한 면접관에게만 쓴다. 판정 줄이 있으면 멈춤으로 본다 (예전 기록 보정)
    infos = {n: dict(i) for n, i in infos.items()}
    for n, i in infos.items():
        if i.get("status") == "skipped" and read_rows(out_dir / f"judge_{n}.jsonl"):
            i["status"] = "stopped"
            i["stopped"] = i.get("reason") or ""
    # 멈춘 면접관도 그동안 낸 판정으로 끝난 건을 센다. 건너뛴(시작도 못 한) 면접관만 뺀다
    inactive = {n for n, i in infos.items() if i.get("status") == "skipped"}
    if phase == "ended":
        # 끝난(강제 종료 포함) 화면에서 기록도 판정 줄도 없는 면접관은 시작하지 않은 것이다: 끝난 건 세기에서 뺀다
        inactive |= {n for n in names if n not in infos and not read_rows(out_dir / f"judge_{n}.jsonl")}
    snap = snapshot(out_dir, items, ids, names, inactive, order)
    status, kind = overall_status(phase, infos, names, interrupted=interrupted, killed=killed,
                                  completed=snap["completed"], total=snap["total"])
    for j in snap["judges"]:
        n = j["name"]
        if phase == "ended" and n not in infos:  # 창을 닫아 run.json에 기록이 남지 않은 면접관
            j["label"] = "멈춤 (강제 종료)" if j["done"] else "시작 기록 없음"
        else:
            j["label"] = judge_label(infos.get(n))
    links = kind != "running" and (expect_outputs or ((out_dir / "review.html").is_file() and (out_dir / SUMMARY_HTML).is_file()))
    return {"run": out_dir.name, "phase": phase, "status": status, "kind": kind, "stamp": _mtime_text(stamp),
            "total": snap["total"], "completed": snap["completed"], "eta": eta, "retries": retries, "judges": snap["judges"],
            "recent": snap["recent"], "blind": blind, "started": started or "-", "links": links}


def write_page(out_dir: Path, data: dict) -> Path:
    path = out_dir / PAGE_NAME
    atomic_write_text(path, render(data))
    return path


def count_retries(out_dir: Path) -> int:
    p = out_dir / "retries.log"
    return len(p.read_text(encoding="utf-8", errors="replace").splitlines()) if p.is_file() else 0


def discover_judges(out_dir: Path, known: list[str]) -> list[str]:
    """화면에 올릴 면접관 이름. run.json의 기록 + inputs.json에 적힌 면접관 + 판정 파일(judge_*.jsonl)이 있는 면접관.

    창을 닫아 강제로 끝난 실행은 run.json의 judges가 비어 있다. 판정 줄은 한 건마다 파일에 바로 남으므로 거기서 읽는다."""
    names = list(known)
    try:
        meta = json.loads((out_dir / "inputs.json").read_text(encoding="utf-8"))
        extra = [str(n) for n in meta.get("judges", [])]
    except (OSError, ValueError, AttributeError):
        extra = []
    extra += sorted(p.stem[len("judge_"):] for p in out_dir.glob("judge_*.jsonl"))
    for n in extra:
        if n not in names:
            names.append(n)
    return names


def write_static(out_dir: Path, items, ids: dict[str, str], state: dict, *, now: Callable[[], datetime] = datetime.now) -> Path:
    """실행하지 않는 쪽(--rebuild, --resume 시작 전)이 지금 상태로 다시 쓴다. 항상 '끝난' 상태라 새로 고침이 없다.

    blind 기록이 없는 예전 실행은 숨기는 쪽으로 본다 (판정이 새는 것보다 안전).
    """
    infos = {n: dict(i) for n, i in (state.get("judges") or {}).items()}
    names = discover_judges(out_dir, list(infos))
    data = build_data(out_dir, items, ids, names, infos, phase="ended", interrupted=bool(state.get("interrupted")),
                      killed=state.get("ended") is False, blind=bool(state.get("blind", True)),
                      retries=count_retries(out_dir), started=str(state.get("started") or ""), stamp=now())
    return write_page(out_dir, data)


class ProgressPage:
    """실행 중 progress.html을 interval초마다 새로 쓴다. 메인 대기 루프에서 tick()을 부른다."""

    def __init__(self, out_dir: Path, items, ids: dict[str, str], names: list[str], *, blind: bool,
                 infos: Callable[[], dict[str, dict]], retries: Callable[[], int], started: str,
                 progress=None, now: Callable[[], datetime] = datetime.now,
                 clock: Callable[[], float] = time.monotonic, interval: float = PROGRESS_PAGE_SECONDS) -> None:
        self.out_dir, self.items, self.ids, self.names = out_dir, items, ids, names
        self.blind, self.infos, self.retries, self.started = blind, infos, retries, started
        self.progress, self.now, self.clock, self.interval = progress, now, clock, interval
        self._last = float("-inf")

    def tick(self) -> None:
        if self.clock() - self._last >= self.interval:
            self.write("running")

    def write(self, phase: str = "running", *, interrupted: bool = False, expect_outputs: bool = False) -> None:
        """파일 쓰기 실패(디스크, 권한)가 판정 실행을 멈추지 않게 오류는 삼킨다."""
        self._last = self.clock()
        try:
            eta, order = "계산 중", None
            if self.progress is not None:
                eta, order = self.progress.eta_text(), self.progress.completed_order()
            data = build_data(self.out_dir, self.items, self.ids, self.names, self.infos(), phase=phase, interrupted=interrupted,
                              killed=False, blind=self.blind, retries=self.retries(), started=self.started, stamp=self.now(),
                              eta=eta, order=order, expect_outputs=expect_outputs)
            write_page(self.out_dir, data)
        except OSError:
            pass


# ---- summary.html: summary.md와 같은 내용을 브라우저용으로 (md는 그대로 둔다) ----------------------------------------


def _inline(segs) -> str:
    out = []
    for sg in segs:
        if sg[0] == "t":
            out.append(esc(sg[1]))
        elif sg[0] == "b":
            out.append(f"<strong>{esc(sg[1])}</strong>")
        elif sg[0] == "c":
            out.append(f"<code>{esc(sg[1])}</code>")
        else:
            out.append(f'{esc(sg[1])}<span class="muted"> ({esc(sg[2])})</span>')
    return "".join(out)


def markdown_to_html(text: str) -> str:
    """md_mini의 블록을 HTML로. 모든 글자는 이스케이프하고, 원문의 HTML은 해석하지 않는다."""
    out: list[str] = []
    for b in parse_markdown(text):
        t = b["t"]
        if t == "gap":
            out.append('<div class="gap"></div>')
        elif t == "hr":
            out.append("<hr>")
        elif t == "code":
            out.append(f"<pre>{esc(b['x'])}</pre>")
        elif t == "h":
            out.append(f"<h{b['l']}>{_inline(b['c'])}</h{b['l']}>")
        elif t == "quote":
            out.append('<div class="quote">' + "<br>".join(_inline(c) for c in b["c"]) + "</div>")
        elif t == "table":
            rows = ["<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in b["h"]) + "</tr>"]
            rows += ["<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in b["r"]]
            out.append('<div class="tablewrap"><table>' + "".join(rows) + "</table></div>")
        elif t == "li":
            out.append(f'<div class="li d{b["d"]}">{esc(b["m"])} {_inline(b["c"])}</div>')
        else:
            out.append(f'<p class="d{b["d"]}">{_inline(b["c"])}</p>' if b["d"] else f"<p>{_inline(b['c'])}</p>")
    return "\n".join(out)


def render_summary_html(md_text: str, out_dir: Path) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    style = _STYLE_RE.search(tpl)
    if not style:
        raise ValueError("템플릿에 <style> 블록이 없습니다.")
    avail = {n for n, _ in NAV if n == SUMMARY_HTML or (out_dir / n).is_file() or n == "review.html"}
    body = nav_html(SUMMARY_HTML, avail) + '\n<div class="md">\n' + markdown_to_html(md_text) + "\n</div>"
    return (tpl.replace("__STYLE_HASH__", csp_hash(style.group(1))).replace("__REFRESH__", "")
            .replace("__TITLE__", "면접관 요약").replace("__BODY__", body))


def write_summary_html(out_dir: Path, md_text: str) -> Path:
    path = out_dir / SUMMARY_HTML
    atomic_write_text(path, render_summary_html(md_text, out_dir))
    return path

"""토론 측정 보고서 (debate/report.md, report.html).

기준은 둘을 따로 본다: (가) 사람 블라인드 판정(human.jsonl의 blind=true), (나) 최종 판정(correct).
건수가 작아서(ADR-006) 건수와 분모를 먼저 보여 주고, 퍼센트는 분모가 30 이상일 때만 참고로 붙인다.
사람 "보류"는 다수결이 낼 수 없는 값이라 일치율의 정답으로 쓰지 않고 따로 센다.
"""

from __future__ import annotations

from pathlib import Path

from src.eval import debate_store as store
from src.eval.citations import STATUS_TEXT
from src.eval.judge import decide, load_rows
from src.eval.judge_human import atomic_write_text, load_human
from src.eval.judge_web import markdown_to_html, nav_html, render_page


def frac(a: int, b: int) -> str:
    if b == 0:
        return "-"
    return f"{a}/{b}" + (f" ({a / b:.0%})" if b >= 30 else "")


def _refs(out_dir: Path, items) -> dict[str, dict]:
    human = load_human(out_dir)
    h = {k: r["human_verdict"] for k, r in human.items() if r.get("blind") is True}
    c = {it.key: ("합격" if it.correct else "불합격") for it in items if it.correct is not None}
    return {"사람 블라인드 판정": h, "최종 판정(correct)": c}


def compute(out_dir: Path, items, judges: list[str]) -> dict:
    r1 = {j: load_rows(out_dir / f"judge_{j}.jsonl") for j in judges}
    r2 = store.load_round2(out_dir)
    final = store.load_final(out_dir)
    cfg = store.load_config(out_dir) or {}
    cands = set(cfg.get("candidates") or [])
    maj: dict[str, str] = {}
    for it in items:
        vs = {j: r1[j][it.key]["verdict"] for j in judges if it.key in r1[j]}
        maj[it.key] = decide(vs)[0] if vs else "미정"
    fin = {it.key: ((final.get(it.key) or {}).get("final") or maj[it.key]) for it in items}
    out = {"r1": r1, "r2": r2, "final": final, "cfg": cfg, "cands": cands, "maj": maj, "fin": fin, "refs": _refs(out_dir, items)}
    return out


def _change_stats(judges: list[str], data: dict, ref: dict[str, str]) -> dict[str, dict]:
    """면접관별: 바꾼 횟수와 방향, 따라감, 동조, 소수 지킴. ref는 {key: 합격/불합격/보류}."""
    stats = {}
    for j in judges:
        s = dict(changed=0, toward=0, away=0, unknown=0, follow_cited=0, conform=0, kept_minority=0, ignored=0, rows=0)
        for key, row in (data["r2"].get(j) or {}).items():
            if key not in data["cands"] or row.get("status") != "ok":
                continue
            s["rows"] += 1
            v1, v2 = row["r1_verdict"], row["verdict"]
            others = [data["r1"][x][key]["verdict"] for x in judges if x != j]
            both_same = len(set(others)) == 1
            ncit = sum(1 for c in row.get("citations") or [] if c.get("valid"))
            if v1 != v2:
                s["changed"] += 1
                r = ref.get(key)
                if r not in ("합격", "불합격"):
                    s["unknown"] += 1
                elif v2 == r:
                    s["toward"] += 1
                elif v1 == r:
                    s["away"] += 1
                else:
                    s["unknown"] += 1
                if both_same and v2 == others[0]:
                    s["follow_cited" if ncit else "conform"] += 1
                if row.get("qtype") == "in_notes" and ncit == 0:
                    s["ignored"] += 1
            elif both_same and others[0] != v1:
                s["kept_minority"] += 1
        stats[j] = s
    return stats


def build_report(out_dir: Path, items, judges: list[str]) -> str:
    data = compute(out_dir, items, judges)
    cfg, cands, final = data["cfg"], data["cands"], data["final"]
    by_key = {it.key: it for it in items}
    lines = ["# 토론 보고서", "",
             "ADR-006. 갈리거나 보류가 있는 건에만 2라운드와 중재를 했다. 건수가 작아서 건수와 분모를 먼저 보고, 퍼센트는 분모 30 이상일 때만 참고로 붙인다.", "",
             "## 대상", "",
             f"- 토론 대상: {len(cands)}건 (셋이 같아 건너뜀 {sum(1 for f in final.values() if f.get('path') == 'unanimous_r1')}, "
             f"판정 불가가 있어 뺌 {len(cfg.get('excluded') or [])}, 아직 안 돌린 건 {len(cfg.get('unrun') or [])})",
             f"- 면접관: {', '.join(judges)} / 모델: {', '.join(f'{k} {v}' for k, v in (cfg.get('models') or {}).items())}",
             f"- 중재: {(cfg.get('arbiter') or {}).get('judge')} {(cfg.get('arbiter') or {}).get('model')}"
             + (f" / 비교 중재: {(cfg['compare'] or {}).get('judge')} {(cfg['compare'] or {}).get('model')} (effort {(cfg['compare'] or {}).get('effort')})" if cfg.get("compare") else ""),
             ""]
    paths: dict[str, int] = {}
    for key in cands:
        p = (final.get(key) or {}).get("path", "pending")
        paths[p] = paths.get(p, 0) + 1
    lines += ["### 결과 경로", "", "| 경로 | 건수 |", "|---|---|"]
    from src.eval.debate import PATHS

    for p, n in sorted(paths.items()):
        lines.append(f"| {PATHS.get(p, p)} | {n} |")
    lines.append("")

    for name, ref in data["refs"].items():
        scope_all = [k for k in by_key if ref.get(k) in ("합격", "불합격")]
        scope_deb = [k for k in scope_all if k in cands]
        hold_ref = [k for k, v in ref.items() if v == "보류" and k in by_key]
        lines += [f"## 기준: {name}", ""]
        lines += ["| 범위 | 기준 건수 | 1라운드 다수결 일치 | 토론 후 일치 | 구함(틀림→맞음) | 해침(맞음→틀림) | 해침(맞음→보류) |", "|---|---|---|---|---|---|---|"]
        for label, scope in (("전체", scope_all), ("토론 대상만", scope_deb)):
            r1ok = sum(1 for k in scope if data["maj"][k] == ref[k])
            fok = sum(1 for k in scope if data["fin"][k] == ref[k])
            rescued = sum(1 for k in scope if data["maj"][k] != ref[k] and data["fin"][k] == ref[k])
            harmed = sum(1 for k in scope if data["maj"][k] == ref[k] and data["fin"][k] not in (ref[k], "보류"))
            harmed_hold = sum(1 for k in scope if data["maj"][k] == ref[k] and data["fin"][k] == "보류")
            lines.append(f"| {label} | {len(scope)} | {frac(r1ok, len(scope))} | {frac(fok, len(scope))} | {rescued} | {harmed} | {harmed_hold} |")
        if hold_ref:
            lines += ["", f"- 기준이 \"보류\"인 건 {len(hold_ref)}건은 일치율에서 뺐다 (그중 토론 대상 {sum(1 for k in hold_ref if k in cands)}건)."]
        lines += ["", "면접관 판정 변화 (토론 대상 건만, 2라운드를 정상으로 받은 줄):", "",
                  "| 면접관 | 2라운드 줄 | 바꿈 | 기준 쪽으로 | 기준 반대로 | 기준 없음/보류 | 근거 있는 따라감 | 동조(근거 없는 따라감) | 소수 지킴 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for j, s in _change_stats(judges, data, ref).items():
            lines.append(f"| {j} | {s['rows']} | {s['changed']} | {s['toward']} | {s['away']} | {s['unknown']} | {s['follow_cited']} | {s['conform']} | {s['kept_minority']} |")
        lines.append("")

    lines += ["## 인용 확인", "", "| 면접관 | 인용 수 | " + " | ".join(STATUS_TEXT[k] for k in STATUS_TEXT) + " |", "|---|---|" + "---|" * len(STATUS_TEXT)]
    for j in judges:
        counts = {k: 0 for k in STATUS_TEXT}
        total = 0
        for row in (data["r2"].get(j) or {}).values():
            for c in row.get("citations") or []:
                total += 1
                counts[c.get("status") if c.get("status") in counts else "bad_format"] += 1
        lines.append(f"| {j} | {total} | " + " | ".join(str(counts[k]) for k in STATUS_TEXT) + " |")
    lines += ["", "\"줄 번호만 틀림\"은 인용한 문장이 문서의 다른 줄에는 있는 경우다. 이 규칙이 너무 엄한지 보려고 따로 센다 (무효로 계산한다).", ""]

    ignored = [(k, j) for j in judges for k, r in (data["r2"].get(j) or {}).items()
               if k in cands and r.get("status") == "ok" and r["r1_verdict"] != r["verdict"] and r.get("qtype") == "in_notes"
               and not any(c.get("valid") for c in r.get("citations") or [])]
    lines += ["## 확인된 인용 없이 판정을 바꾼 경우 (in_notes: 결정에 반영하지 않음)", ""]
    lines += [f"- {j}: {by_key[k].qid} · {by_key[k].repeat}회차" for k, j in ignored] or ["(없음)"]
    conform = [(k, j) for j in judges for k, r in (data["r2"].get(j) or {}).items()
               if k in cands and r.get("status") == "ok" and r["r1_verdict"] != r["verdict"]
               and len({data["r1"][x][k]["verdict"] for x in judges if x != j}) == 1
               and r["verdict"] == data["r1"][next(x for x in judges if x != j)][k]["verdict"]
               and not any(c.get("valid") for c in r.get("citations") or [])]
    lines += ["", "## 동조 의심 (바꿨고, 다른 두 면접관의 1라운드 판정과 같고, 확인된 인용이 없음)", ""]
    lines += [f"- {j}: {by_key[k].qid} · {by_key[k].repeat}회차" + (" (not_in_notes: 근거 없음)" if by_key[k].qtype == "not_in_notes" else "")
              for k, j in conform] or ["(없음)"]

    arb = store.read_rows(store.ddir(out_dir) / store.ARBITER_FILE)
    cmp_ = store.read_rows(store.ddir(out_dir) / store.COMPARE_FILE)
    lines += ["", "## 중재", ""]
    if not arb:
        lines.append("(중재한 건 없음)")
    else:
        mw = sum(1 for f in final.values() if f.get("minority_won"))
        lines.append(f"- 중재한 건 {len(arb)}, 소수 의견이 이긴 건 {mw}, 끝까지 갈린 건 {sum(1 for f in final.values() if f.get('unresolved'))}")
    if cmp_:
        same = [k for k, r in cmp_.items() if r.get("status") == "ok" and arb.get(k, {}).get("verdict") == r.get("verdict")]
        diff = [k for k, r in cmp_.items() if r.get("status") == "ok" and k in arb and arb[k].get("verdict") != r.get("verdict")]
        lines += ["", "### 비교 중재 (계열 편향 확인용, 최종 결정에는 쓰지 않음)", "",
                  f"- 같은 결정 {len(same)}건, 다른 결정 {len(diff)}건, 비교 중재 실패 {sum(1 for r in cmp_.values() if r.get('status') != 'ok')}건"]
        lines += [f"- {by_key[k].qid} · {by_key[k].repeat}회차: 기본 중재 {arb[k].get('verdict')} / 비교 중재 {cmp_[k].get('verdict')}" for k in diff]

    calls = sum(len(v) for v in data["r2"].values())
    toks = sum(r.get("tokens") for v in data["r2"].values() for r in v.values() if isinstance(r.get("tokens"), int))
    secs = sum(r.get("sec") or 0 for v in data["r2"].values() for r in v.values())
    lines += ["", "## 비용", "", f"- 2라운드 줄 {calls}, 중재 줄 {len(arb)}" + (f", 비교 중재 줄 {len(cmp_)}" if cmp_ else ""),
              f"- 읽은 토큰 합계(2라운드): {toks if toks else '알 수 없음'}", f"- 호출 시간 합계(2라운드): {secs:.0f}초", ""]
    return "\n".join(lines)


def write_report(out_dir: Path, items, judges: list[str]) -> Path:
    md = build_report(out_dir, items, judges)
    d = store.ddir(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_text(d / store.REPORT_MD, md)
    nav = nav_html("", None, prefix="../")
    atomic_write_text(d / store.REPORT_HTML, render_page("토론 보고서", nav + '\n<div class="md">\n' + markdown_to_html(md) + "\n</div>"))
    return d / store.REPORT_MD

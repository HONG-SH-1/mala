"""사람 판정 합치기. review.html에서 내보낸 JSON을 검증하고 실행 폴더의 human.jsonl에 합친다.
기준 의견("이 기준이 이상함" 체크와 한 줄 메모)은 판정과 섞지 않고 criteria.jsonl에 따로 합친다.

검증이 하나라도 틀리면 아무것도 쓰지 않는다. 같은 건은 마지막 값이 이긴다.
파일 전체를 다시 쓰므로 같은 파일을 두 번 합쳐도 결과가 같다.
judge.py를 가져오지 않는다 (순환 방지).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

HUMAN_VERDICTS = ("합격", "불합격", "보류")
MAX_FILE_BYTES = 1_000_000
MAX_ITEMS = 5000
MAX_REASON = 500
MAX_NOTE = 500
_BID_RE = re.compile(r"^[A-Za-z#]\d{1,6}$")


class HumanImportError(ValueError):
    pass


def next_blind(prev: dict | None, verdict: str, visible_now: bool) -> bool:
    """판정을 저장할 때의 blind 값 (review.html의 decideBlind와 같은 규칙이다).

    - 처음 저장: 저장하는 순간 면접관 판정이 가려져 있었으면 true (visible_now가 false).
    - 이미 블라인드로 저장한 건을 다시 저장: 판정(합격/불합격/보류)이 그대로면 true를 유지한다 (이유 글만 고친 경우).
      판정이 바뀌면 false.
    - 이미 블라인드가 아닌 건은 계속 false.
    """
    if prev is not None and prev.get("blind") is True and prev.get("verdict") == verdict:
        return True
    return not visible_now


def human_path(out_dir: Path) -> Path:
    return out_dir / "human.jsonl"


def criteria_path(out_dir: Path) -> Path:
    return out_dir / "criteria.jsonl"


def load_criteria(out_dir: Path) -> dict[str, dict]:
    """{key: 행}. 기준 의견은 판정과 따로 저장한다."""
    out: dict[str, dict] = {}
    p = criteria_path(out_dir)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def load_human(out_dir: Path) -> dict[str, dict]:
    """{key: 행}. 같은 key가 여러 줄이면 마지막 줄."""
    out: dict[str, dict] = {}
    p = human_path(out_dir)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def parse_export(text: str, run_name: str, valid_bids: set[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    """내보낸 JSON을 검사해 ({bid: {verdict, reason, at}}, {bid: {odd, note, at}})를 돌려준다.
    criteria는 없어도 된다 (예전 내보내기 파일). 틀리면 HumanImportError."""
    try:
        data = json.loads(text)
    except ValueError:
        raise HumanImportError("JSON 형식이 아닙니다.") from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise HumanImportError("최상위가 {run, items:[...]} 형식이 아닙니다.")
    if data.get("run") != run_name:
        raise HumanImportError("이 파일은 다른 실행 폴더에서 내보낸 것입니다 (run 이름이 다름).")
    if len(data["items"]) > MAX_ITEMS:
        raise HumanImportError(f"항목이 너무 많습니다 (최대 {MAX_ITEMS}).")
    errors: list[str] = []
    out: dict[str, dict] = {}
    crit: dict[str, dict] = {}
    raw_crit = data.get("criteria", [])
    if not isinstance(raw_crit, list) or len(raw_crit) > MAX_ITEMS:
        raise HumanImportError("criteria는 목록이어야 합니다.")
    for i, it in enumerate(raw_crit, 1):
        where = f"기준 의견 {i}번째"
        if not isinstance(it, dict):
            errors.append(f"{where}: 객체가 아님")
            continue
        bid, odd, note, at = it.get("bid"), it.get("odd"), it.get("note", ""), it.get("at", "")
        if not isinstance(bid, str) or not _BID_RE.match(bid) or bid not in valid_bids:
            errors.append(f"{where}: 번호가 이 실행에 없음")
        elif not isinstance(odd, bool):
            errors.append(f"{where} ({bid}): odd는 true/false여야 함")
        elif not isinstance(note, str) or len(note) > MAX_NOTE:
            errors.append(f"{where} ({bid}): note는 {MAX_NOTE}자 이하 글이어야 함")
        elif not isinstance(at, str) or len(at) > 40:
            errors.append(f"{where} ({bid}): at 형식 오류")
        elif bid in crit:
            errors.append(f"{where} ({bid}): 같은 번호가 한 파일에 두 번 있음")
        else:
            crit[bid] = {"odd": odd, "note": " ".join(note.split()), "at": at}
    for i, it in enumerate(data["items"], 1):
        where = f"{i}번째 항목"
        if not isinstance(it, dict):
            errors.append(f"{where}: 객체가 아님")
            continue
        bid, verdict, reason, at = it.get("bid"), it.get("verdict"), it.get("reason"), it.get("at", "")
        blind = it.get("blind", False)  # 없으면(예전 파일) 블라인드가 아닌 것으로 본다 (안전한 쪽)
        if not isinstance(bid, str) or not _BID_RE.match(bid) or bid not in valid_bids:
            errors.append(f"{where}: 번호가 이 실행에 없음")
            continue
        if verdict not in HUMAN_VERDICTS:
            errors.append(f"{where} ({bid}): verdict는 {'/'.join(HUMAN_VERDICTS)} 중 하나여야 함")
            continue
        if not isinstance(reason, str) or len(reason) > MAX_REASON:
            errors.append(f"{where} ({bid}): reason은 {MAX_REASON}자 이하 글이어야 함")
            continue
        if not isinstance(at, str) or len(at) > 40:
            errors.append(f"{where} ({bid}): at 형식 오류")
            continue
        if not isinstance(blind, bool):
            errors.append(f"{where} ({bid}): blind는 true/false여야 함")
            continue
        if bid in out:
            errors.append(f"{where} ({bid}): 같은 번호가 한 파일에 두 번 있음")
            continue
        out[bid] = {"verdict": verdict, "reason": reason.strip(), "at": at, "blind": blind}
    if errors:
        shown = errors[:20] + ([f"... 외 {len(errors) - 20}개"] if len(errors) > 20 else [])
        raise HumanImportError("받아들이지 않았습니다 (아무것도 쓰지 않음):\n  " + "\n  ".join(shown))
    return out, crit


def import_human(out_dir: Path, export_file: str | Path) -> int:
    """검증 후 human.jsonl에 합친다. 합친 건 수를 돌려준다."""
    p = Path(export_file)
    if p.stat().st_size > MAX_FILE_BYTES:
        raise HumanImportError("파일이 너무 큽니다.")
    bmap_path = out_dir / "blind_map.json"
    if not bmap_path.exists():
        raise HumanImportError("blind_map.json이 없습니다. --rebuild를 먼저 하세요.")
    bmap = json.loads(bmap_path.read_text(encoding="utf-8"))
    parsed, crit = parse_export(p.read_text(encoding="utf-8"), out_dir.name, set(bmap))
    merged = load_human(out_dir)
    for bid, v in parsed.items():
        info = bmap[bid]
        merged[info["key"]] = {
            "key": info["key"], "label": info["label"], "id": info["id"], "repeat": info["repeat"],
            "bid": bid, "human_verdict": v["verdict"], "human_reason": v["reason"], "at": v["at"], "blind": v["blind"],
        }
    crit_merged = load_criteria(out_dir)
    for bid, v in crit.items():
        info = bmap[bid]
        if not v["odd"] and not v["note"]:  # 체크도 메모도 없으면 기준 의견을 지운 것
            crit_merged.pop(info["key"], None)
            continue
        crit_merged[info["key"]] = {
            "key": info["key"], "label": info["label"], "id": info["id"], "repeat": info["repeat"],
            "bid": bid, "odd": v["odd"], "note": v["note"], "at": v["at"],
        }
    _write_rows(human_path(out_dir), merged, only_if=bool(parsed) or human_path(out_dir).exists())
    _write_rows(criteria_path(out_dir), crit_merged, only_if=bool(crit) or criteria_path(out_dir).exists())
    return len(parsed)


def atomic_write_text(path: Path, text: str) -> None:
    """임시 파일에 쓴 뒤 os.replace로 바꿔 끼운다. 쓰다 멈춰도 원래 파일이 반쪽이 되지 않는다."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_rows(path: Path, rows: dict[str, dict], only_if: bool) -> None:
    if not only_if:
        return
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows.values()))


def criteria_section(criteria: dict[str, dict]) -> list[str]:
    """summary.md의 '기준 의견(v3 후보)' 절. 기준 의견이 없으면 빈 목록."""
    if not criteria:
        return []
    rows = sorted(criteria.values(), key=lambda r: (str(r["id"]), r["repeat"], str(r["bid"])))
    out = ["", "## 기준 의견(v3 후보)", "",
           "- 정답 기준(라벨 v2)이 이상하다고 본 건입니다. 1단계 중에는 라벨을 바꾸지 않고, v3를 만들 때 봅니다.",
           "- 판정과는 따로 적은 의견이라 위의 일치율에 들어가지 않습니다.",
           f"- 건 수: {len(rows)} (질문 {len({r['id'] for r in rows})}개)", ""]
    for r in rows:
        mark = "이상함 체크" if r["odd"] else "메모만"
        note = " ".join(str(r.get("note") or "").split()) or "(메모 없음)"
        out.append(f"- {r['id']} · {r['repeat']}회차 · {r['bid']} — {mark}: {note}")
    return out


def human_section(human: dict[str, dict], rows: dict[str, dict], maj: list[dict], active: list[str], pct: Callable[[int, int], str]) -> list[str]:
    """summary.md의 '사람 판정과의 일치율' 절. 사람 판정이 없으면 빈 목록.

    일치율은 저장할 때 면접관 판정이 가려져 있던(blind=true) 판정만으로 계산한다.
    면접관 판정을 본 뒤에 저장한 판정(blind=false)은 '임원 판정'으로 따로 개수와 목록만 보여 준다.
    """
    if not human:
        return []
    blind_rows = {k: r for k, r in human.items() if r.get("blind") is True}
    seen_rows = [r for r in human.values() if r.get("blind") is not True]  # 필드가 없는 예전 행도 여기
    held = sum(1 for r in blind_rows.values() if r["human_verdict"] == "보류")
    out = ["", "## 사람 판정과의 일치율", "",
           f"- 블라인드 판정(면접관 판정이 가려진 상태에서 저장): {len(blind_rows)}건 (보류 {held}건은 분모에서 뺍니다)",
           f"- 임원 판정(면접관 판정을 본 상태에서 저장): {len(seen_rows)}건 — 일치율에 넣지 않았습니다",
           "- 사람이 본 건은 '사람이 볼 건'만이라 전체를 대표하지 않습니다.", "",
           "| 판정자 | 일치 | 사람이 합격 준 건에서 | 사람이 불합격 준 건에서 |", "|---|---|---|---|"]
    majority = {m["key"]: m["majority"] for m in maj}

    def verdict_of(who: str, key: str) -> str | None:
        if who == "다수결":
            return majority.get(key)
        r = rows.get(who, {}).get(key)
        return r["verdict"] if r else None

    for who in list(active) + ["다수결"]:
        total = agree = 0
        by = {"합격": [0, 0], "불합격": [0, 0]}
        for key, h in blind_rows.items():
            hv, v = h["human_verdict"], verdict_of(who, key)
            if hv not in by or v not in ("합격", "불합격"):
                continue
            total += 1
            hit = v == hv
            agree += hit
            by[hv][0] += hit
            by[hv][1] += 1
        out.append(f"| {who} | {pct(agree, total)} | {pct(*by['합격'])} | {pct(*by['불합격'])} |")
    if seen_rows:
        out += ["", "### 임원 판정 목록", ""]
        for r in sorted(seen_rows, key=lambda r: (str(r["id"]), r["repeat"], str(r["bid"]))):
            out.append(f"- {r['id']} · {r['repeat']}회차 · {r['bid']} — {r['human_verdict']}")
    return out

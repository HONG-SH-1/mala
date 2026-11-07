"""안전장치 — 공개 문서 컬렉션(mala_eval_docs...)에서 나온 결과만 외부 면접관(codex, gemini)에 보낸다.

허용 목록 방식이다: 컬렉션 이름이 mala_eval_docs로 시작해야 통과하고, 그 밖의 이름(볼트 포함)이나
이름을 알 수 없는 경우는 모두 거부한다.

컬렉션 이름이 남는 곳: 평가 실행이 쓰는 원래 결과 `.md`의 "컬렉션: <이름>" 줄.
`.jsonl` 안에는 없다. 재채점 파일(`_rescored-v2.jsonl`)의 짝은 같은 이름에서 `_rescored...`를 뗀 `.md`다.
이름을 알 수 없으면(10-28 이전 형식은 줄이 없음) 안전한 쪽으로 보고 멈춘다.

예외: 짝 .md에 컬렉션 줄이 없을 때만 `eval/results/source_overrides.yaml`(또는 결과 파일과 같은 폴더의 같은 이름 파일)에
사후 확인으로 적어 둔 이름을 쓴다. 거기 적힌 이름에도 허용 목록 규칙이 똑같이 적용된다. .md는 고치지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

EXTERNAL_JUDGES = ("codex", "gemini")
OVERRIDES_NAME = "source_overrides.yaml"
ALLOWED_PREFIX = "mala_eval_docs"  # 공개 docs 사본으로 만든 평가 컬렉션
_COLLECTION_RE = re.compile(r"컬렉션:\s*([^\s,]+)")
_RESCORED_SUFFIX = re.compile(r"(_rescored(-v\d+)?)+$")


def result_md_candidates(jsonl_path: str | Path, root: Path | None = None) -> list[Path]:
    """결과 .jsonl의 짝 .md 후보. 같은 폴더와 data/eval/ 에서 찾는다."""
    p = Path(jsonl_path)
    stem = _RESCORED_SUFFIX.sub("", p.stem)
    dirs = [p.parent]
    if root is not None:
        dirs.append(root / "data" / "eval")
    seen: list[Path] = []
    for d in dirs:
        c = d / f"{stem}.md"
        if c not in seen:
            seen.append(c)
    return seen


def override_collection(jsonl_path: str | Path, root: Path | None = None) -> str | None:
    """source_overrides.yaml에 사후 확인으로 적힌 컬렉션 이름. 없거나 형식이 틀리면 None (안전한 쪽)."""
    p = Path(jsonl_path)
    stem = _RESCORED_SUFFIX.sub("", p.stem)
    candidates = [p.parent / OVERRIDES_NAME]
    if root is not None:
        candidates.append(root / "eval" / "results" / OVERRIDES_NAME)
    for c in candidates:
        if not c.is_file():
            continue
        try:
            data = yaml.safe_load(c.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        entry = data.get(stem) if isinstance(data, dict) else None
        name = entry.get("collection") if isinstance(entry, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def collections_of(jsonl_path: str | Path, root: Path | None = None) -> list[str]:
    """짝 .md에서 찾은 컬렉션 이름들. .md에 줄이 없을 때만 사후 확인 파일을 본다 (둘 다 없으면 빈 목록)."""
    found: list[str] = []
    for md in result_md_candidates(jsonl_path, root):
        if not md.is_file():
            continue
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
            m = _COLLECTION_RE.search(line)
            if m:
                found.append(m.group(1))
                break
    if not found:
        name = override_collection(jsonl_path, root)
        if name:
            found.append(name)
    return found


def check_external_judges(files: list[str], judge_names: list[str], root: Path | None = None) -> None:
    """codex나 gemini를 쓰려는데 입력이 볼트 컬렉션이거나 컬렉션을 알 수 없으면 SystemExit."""
    external = [n for n in judge_names if n in EXTERNAL_JUDGES]
    if not external:
        return
    problems: list[str] = []
    for f in files:
        names = collections_of(f, root)
        if not names:
            problems.append(f"{Path(f).name}: 컬렉션 이름을 찾지 못함 (짝 .md에 '컬렉션:' 줄이 없음)")
        elif not all(n.startswith(ALLOWED_PREFIX) for n in names):
            problems.append(f"{Path(f).name}: 컬렉션 {', '.join(names)} (허용: {ALLOWED_PREFIX}...)")
    if problems:
        raise SystemExit(
            f"{', '.join(external)} 실행을 거부합니다. 공개 문서 컬렉션이 아니거나 출처를 확인할 수 없는 결과가 있습니다:\n  "
            + "\n  ".join(problems)
            + "\n공개 문서(docs) 기준 결과만 외부 면접관에 보낼 수 있습니다. claude만 쓰려면 --judges claude."
        )

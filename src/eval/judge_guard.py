"""안전장치 — 공개 문서 컬렉션(mala_eval_docs...)에서 나온 결과만 면접관(claude, codex, gemini)에 보낸다.

`claude -p`도 글을 밖으로 보내는 것이라 codex, gemini와 같은 검사를 받는다. 1라운드 면접관뿐 아니라
토론 중재자(비교 중재자 포함)도 같다. 검사를 면제할 이름만 EXEMPT_JUDGES에 적고(지금은 비어 있음),
그 밖의 이름은 처음 보는 것이라도 전부 외부로 본다.

허용 목록 방식이다: 컬렉션 이름이 mala_eval_docs로 시작해야 통과하고, 그 밖의 이름(볼트 포함)이나
이름을 알 수 없는 경우는 모두 거부한다. 결과 .md에 "볼트:" 줄이 있으면 그 경로도 data/eval_corpus/ 안이어야 한다
(컬렉션 이름만 맞고 볼트가 진짜 볼트인 결과를 막는다).

컬렉션 이름이 남는 곳: 평가 실행이 쓰는 원래 결과 `.md`의 "컬렉션: <이름>" 줄.
`.jsonl` 안에는 없다. 재채점 파일(`_rescored-v2.jsonl`)의 짝은 같은 이름에서 `_rescored...`를 뗀 `.md`다.
이름을 알 수 없으면(10-28 이전 형식은 줄이 없음) 안전한 쪽으로 보고 멈춘다.

예외: 짝 .md에 컬렉션 줄이 없을 때만, 그리고 입력이 레포의 eval/results/ 안에 있을 때만 그 폴더의
`source_overrides.yaml`(이 한 곳)에 사후 확인으로 적어 둔 이름을 쓴다. 같은 키가 두 번 있으면 파일 전체를 거부한다. 거기 적힌 이름에도 허용 목록 규칙이 똑같이 적용된다. .md는 고치지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

EXEMPT_JUDGES: tuple[str, ...] = ()  # 검사를 면제할 면접관 이름. 비어 있으면 모든 면접관이 검사를 받는다
OVERRIDES_NAME = "source_overrides.yaml"
ALLOWED_PREFIX = "mala_eval_docs"  # 공개 docs 사본으로 만든 평가 컬렉션
ALLOWED_VAULT_DIR = "data/eval_corpus"  # 평가용 공개 문서 사본이 있는 폴더 (레포 기준)
_COLLECTION_RE = re.compile(r"컬렉션:\s*([^\s,]+)")
_VAULT_RE = re.compile(r"볼트:\s*(.*?)\s*(?:,\s*컬렉션:|$)")
_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:/|/)")
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


class _UniqueKeyLoader(yaml.SafeLoader):
    """safe_load와 같은 안전한 로더인데, 같은 키가 두 번 나오면 거부한다 (뒤의 값이 앞의 값을 조용히 덮는 것을 막는다)."""


def _no_duplicate_keys(loader, node, deep=False):
    seen = set()
    for key_node, _value in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.YAMLError(f"같은 키가 두 번 있음: {key}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def override_collection(jsonl_path: str | Path, root: Path | None = None) -> str | None:
    """레포의 eval/results/source_overrides.yaml(한 곳)에 사후 확인으로 적힌 컬렉션 이름.

    - 읽는 곳은 root/eval/results/source_overrides.yaml 하나뿐이다. 입력 파일 옆 폴더는 보지 않는다.
    - 입력 파일이 root/eval/results/ 안에 있을 때만 적용한다.
    - 없거나, 형식이 틀리거나, 같은 키가 두 번 있으면 None (안전한 쪽).
    """
    if root is None:
        return None
    results = root / "eval" / "results"
    p = Path(jsonl_path)
    if not _inside(p, results):
        return None
    c = results / OVERRIDES_NAME
    if not c.is_file():
        return None
    try:
        data = yaml.load(c.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader 하위 클래스
    except (yaml.YAMLError, OSError):
        return None
    stem = _RESCORED_SUFFIX.sub("", p.stem)
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


def vaults_of(jsonl_path: str | Path, root: Path | None = None) -> list[str]:
    """짝 .md의 "볼트: <경로>" 줄에서 읽은 경로들 (줄이 없으면 빈 목록)."""
    found: list[str] = []
    for md in result_md_candidates(jsonl_path, root):
        if not md.is_file():
            continue
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
            m = _VAULT_RE.search(line)
            if m and "볼트:" in line:
                found.append(m.group(1))
                break
    return found


def vault_is_allowed(raw: str, root: Path | None = None) -> bool:
    """볼트 경로가 레포의 data/eval_corpus/ 안인가. 모르거나 "-"이거나 ".."로 빠져나가면 False."""
    s = (raw or "").strip().strip("\"'").replace("\\", "/")
    if not s or s == "-" or ".." in s.split("/"):
        return False
    if _ABSOLUTE_RE.match(s):
        if root is None:
            return False
        corpus = (root / ALLOWED_VAULT_DIR).resolve()
        target = Path(s).resolve()
        return target != corpus and _inside(target, corpus)
    while s.startswith("./"):
        s = s[2:]
    prefix = ALLOWED_VAULT_DIR + "/"
    return s.startswith(prefix) and len(s) > len(prefix)


def check_external_judges(files: list[str], judge_names: list[str], root: Path | None = None) -> None:
    """면접관(1라운드, 토론 중재자 모두)이 하나라도 있는데 입력이 볼트 결과이거나 출처를 알 수 없으면 SystemExit."""
    external = list(dict.fromkeys(n for n in judge_names if n not in EXEMPT_JUDGES))
    if not external:
        return
    problems: list[str] = []
    for f in files:
        names = collections_of(f, root)
        if not names:
            problems.append(f"{Path(f).name}: 컬렉션 이름을 찾지 못함 (짝 .md에 '컬렉션:' 줄이 없음)")
        elif not all(n.startswith(ALLOWED_PREFIX) for n in names):
            problems.append(f"{Path(f).name}: 컬렉션 {', '.join(names)} (허용: {ALLOWED_PREFIX}...)")
        if any(not vault_is_allowed(v, root) for v in vaults_of(f, root)):
            # 경로 원문은 메시지에 넣지 않는다 (진짜 볼트의 위치가 터미널, 로그에 남지 않게). 파일 이름과 이유만
            problems.append(f"{Path(f).name}: 볼트 경로가 {ALLOWED_VAULT_DIR}/ 밖이거나 확인할 수 없음")
    if problems:
        raise SystemExit(
            f"{', '.join(external)} 실행을 거부합니다. 공개 문서 컬렉션이 아니거나 출처를 확인할 수 없는 결과가 있습니다:\n  "
            + "\n  ".join(problems)
            + "\n공개 문서(docs) 기준 결과만 면접관(claude 포함)에 보낼 수 있습니다. claude -p도 외부 전송입니다."
        )

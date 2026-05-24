from __future__ import annotations

import json
import re
import tomllib
from functools import lru_cache
from pathlib import Path

ROOT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Gemfile",
)


def find_project_root(start: Path) -> Path | None:
    start = start.resolve()
    candidates = [start] + list(start.parents)
    for d in candidates:
        for marker in ROOT_MARKERS:
            if (d / marker).exists():
                return d
    return None


def detect_stacks(path: Path) -> set[str]:
    root = find_project_root(path)
    if root is None:
        return set()
    return _detect_at_root(root)


@lru_cache(maxsize=64)
def _detect_at_root(root: Path) -> frozenset[str]:
    stacks: set[str] = set()
    _from_pyproject(root, stacks)
    if (root / "requirements.txt").exists():
        stacks.add("python")
    _from_package_json(root, stacks)
    if (root / "tsconfig.json").exists():
        stacks.add("typescript")
    if (root / "go.mod").exists():
        stacks.add("go")
    if (root / "Cargo.toml").exists():
        stacks.add("rust")
    _from_maven_gradle(root, stacks)
    _from_gemfile(root, stacks)
    if any(root.glob("*.tf")):
        stacks.add("terraform")
    if (root / "Dockerfile").exists():
        stacks.add("docker")
    if (root / ".github" / "workflows").is_dir():
        stacks.add("github-actions")
    return frozenset(stacks)


def _from_pyproject(root: Path, stacks: set[str]) -> None:
    p = root / "pyproject.toml"
    if not p.exists():
        return
    stacks.add("python")
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return
    deps_blob = " ".join(
        str(x).lower()
        for x in (data.get("project", {}).get("dependencies") or [])
    )
    for name, stack in (("django", "django"), ("fastapi", "fastapi"), ("flask", "flask")):
        if re.search(rf"\b{name}\b", deps_blob):
            stacks.add(stack)


def _from_package_json(root: Path, stacks: set[str]) -> None:
    p = root / "package.json"
    if not p.exists():
        return
    stacks.add("node")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    deps = {}
    for key in ("dependencies", "devDependencies"):
        deps.update(data.get(key) or {})
    names = {n.lower() for n in deps}
    for name, stack in (
        ("react", "react"),
        ("vue", "vue"),
        ("svelte", "svelte"),
        ("next", "nextjs"),
        ("typescript", "typescript"),
    ):
        if name in names:
            stacks.add(stack)


def _from_maven_gradle(root: Path, stacks: set[str]) -> None:
    for fname in ("pom.xml", "build.gradle", "build.gradle.kts"):
        p = root / fname
        if not p.exists():
            continue
        stacks.add("java")
        try:
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if "springframework" in text or "spring-boot" in text:
            stacks.add("spring")


def _from_gemfile(root: Path, stacks: set[str]) -> None:
    p = root / "Gemfile"
    if not p.exists():
        return
    stacks.add("ruby")
    try:
        if "rails" in p.read_text(encoding="utf-8", errors="ignore").lower():
            stacks.add("rails")
    except OSError:
        pass

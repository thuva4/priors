from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from priors.paths import config_path

DEFAULT_CONFIG: dict[str, Any] = {
    "retrieval": {"mode": "naive"},
    "adapters": {"enabled": ""},
    "editor": {"command": ""},
}


def load() -> dict[str, Any]:
    p = config_path()
    if not p.exists():
        return _deep_copy(DEFAULT_CONFIG)
    with p.open("rb") as f:
        data = tomllib.load(f)
    return _merge(_deep_copy(DEFAULT_CONFIG), data)


def save(cfg: dict[str, Any]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump_toml(cfg), encoding="utf-8")


def get(key: str) -> Any:
    cfg = load()
    cur: Any = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_(key: str, value: str) -> None:
    cfg = load()
    parts = key.split(".")
    cur = cfg
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = _coerce(value)
    save(cfg)


def write_default_if_missing() -> bool:
    p = config_path()
    if p.exists():
        return False
    save(_deep_copy(DEFAULT_CONFIG))
    return True


def _coerce(value: str) -> Any:
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _deep_copy(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        out[k] = _deep_copy(v) if isinstance(v, dict) else v
    return out


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _merge(base[k], v)
        else:
            base[k] = v
    return base


def _dump_toml(cfg: dict[str, Any]) -> str:
    lines: list[str] = []
    scalars = {k: v for k, v in cfg.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in cfg.items() if isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")
    for name, table in tables.items():
        lines.append("")
        lines.append(f"[{name}]")
        for k, v in table.items():
            lines.append(f"{k} = {_toml_value(v)}")
    return "\n".join(lines).lstrip("\n") + "\n"


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'

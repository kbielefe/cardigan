"""Read keys from the repo-root `.env` file."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_env(path: Path | None = None) -> dict[str, str]:
    env = ROOT / ".env" if path is None else path
    if not env.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if name and value:
            values[name] = value
    return values


def env_value(name: str, path: Path | None = None) -> str | None:
    value = read_env(path).get(name)
    return value or None


def apply_env(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Copy `.env` keys into `os.environ`. Existing process values win unless override."""
    values = read_env(path)
    for name, value in values.items():
        if override or name not in os.environ:
            os.environ[name] = value
    return values

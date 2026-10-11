"""Explicit harness selection and runtime-only credential loading."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from arw.kernel.core.canonical import strict_json_loads
from arw.kernel.state.harness_models import (
    NAME,
    HarnessConfigError,
    HarnessConfiguration,
    HarnessEntry,
)


def load_harness_configuration(path: Path) -> HarnessConfiguration:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise HarnessConfigError(
            "harness configuration must be a regular file <=256 KiB"
        )
    try:
        raw = path.read_bytes()
        strict_json_loads(raw)
        return HarnessConfiguration.model_validate_json(raw, strict=True)
    except (ValueError, OSError):
        # Pydantic diagnostics can include supplied values, including a rejected secret.
        raise HarnessConfigError("invalid harness configuration") from None


def runtime_credentials(
    entry: HarnessEntry, base: Path, environment: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Load only explicitly selected variable names; never interpolate or execute .env."""
    names = set(entry.credential_env)
    if entry.api_key_env:
        names.add(entry.api_key_env)
    source = environment if environment is not None else os.environ
    values = {name: source[name] for name in names if name in source}
    if entry.env_file and names:
        path = Path(entry.env_file)
        if not path.is_absolute():
            path = base / path
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise HarnessConfigError("selected .env must be a regular file <=64 KiB")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeError, OSError):
            raise HarnessConfigError("selected .env cannot be decoded") from None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.removeprefix("export ")
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator or name not in names or name in values:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
                value = value[1:-1]
            values[name] = value
    missing = sorted(name for name in names if not values.get(name))
    if missing:
        raise HarnessConfigError(
            "missing credential environment: " + ", ".join(missing)
        )
    selected = {name: values[name] for name in names}
    if any(
        "\x00" in value or "\r" in value or "\n" in value for value in selected.values()
    ):
        raise HarnessConfigError("invalid runtime credential value")
    return selected


class HarnessRegistry:
    """Application extension point; registration is explicit and never imports config code."""

    def __init__(self):
        self._factories: dict[str, Callable] = {}

    def register(self, kind: str, factory: Callable) -> None:
        if (
            not re.fullmatch(NAME, kind)
            or kind in self._factories
            or not callable(factory)
        ):
            raise HarnessConfigError("invalid or duplicate harness registration")
        self._factories[kind] = factory

    def build(self, entry: HarnessEntry, **context):
        factory = self._factories.get(entry.kind)
        if factory is None:
            raise HarnessConfigError("unregistered harness kind: " + entry.kind)
        return factory(entry, **context)

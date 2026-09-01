"""Normalization helpers for the v2 compatibility baseline.

Golden fixtures pin *structure*, not prose: timestamps, absolute paths, and
other environment-specific bytes are normalized before comparison so the
fixtures survive module moves and machine differences, while any change to
command shape, exit codes, error classes, digests, or event bytes still fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def normalize_text(text: str, *, replacements: dict[str, str] | None = None) -> str:
    """Replace environment-specific substrings with stable placeholders.

    ``replacements`` maps concrete strings (e.g. a tmp_path) to placeholders
    (e.g. ``<RUN_ROOT>``). RFC-3339 timestamps are replaced with ``<TS>``.
    """
    for concrete, placeholder in (replacements or {}).items():
        text = text.replace(concrete, placeholder)
    return _RFC3339.sub("<TS>", text)


def path_replacements(**named_paths: Path) -> dict[str, str]:
    """Build replacements from named paths: ``run_root=Path(...)`` ->
    ``{str(path): "<RUN_ROOT>"}``. Longest first so nested paths win."""
    items = sorted(
        ((str(path), f"<{name.upper()}>") for name, path in named_paths.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    return dict(items)


def read_golden_json(path: Path) -> dict:
    """Read a checked-in golden fixture, failing with a named assertion."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise AssertionError(
            f"golden fixture {path.name} is unreadable: {error}"
        ) from error
    assert isinstance(payload, dict), (
        f"golden fixture {path.name} must be a JSON object"
    )
    return payload

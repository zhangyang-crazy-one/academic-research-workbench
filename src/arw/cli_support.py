"""CLI input/output plumbing shared by the parser layer and host dispatch.

Moved verbatim from cli.py during the v2 thin-kernel extraction; this module
is a leaf (stdlib + kernel/core only) so both cli.py and
kernel/execution/host_dispatch.py can import it without cycles.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads

RequestModel = TypeVar("RequestModel", bound=BaseModel)

class CLIInputError(ValueError):
    """A CLI-only envelope or evidence input is invalid."""

def _load_request(path: Path, model: type[RequestModel]) -> RequestModel:
    try:
        raw = path.read_bytes()
        payload = strict_json_loads(raw)
        return model.model_validate(payload)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise CLIInputError(f"request is missing or invalid: {error}") from error

def _canonical_object_from_bytes(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        value = strict_json_loads(raw)
    except (UnicodeError, ValueError) as error:
        raise CLIInputError(f"{label} is invalid: {error}") from error
    if not isinstance(value, dict):
        raise CLIInputError(f"{label} must be a JSON object")
    if canonical_json_bytes(value) != raw:
        raise CLIInputError(f"{label} bytes are not canonical")
    return value

def _load_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CLIInputError(f"{label} is missing or invalid: {error}") from error
    return _canonical_object_from_bytes(raw, label=label)

def _is_sha256_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )

def _identity_receipt_reference(value: object, *, label: str) -> dict[str, str]:
    digest = value.get("identity_receipt_sha256") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"identity_receipt_sha256"}
        or not _is_sha256_text(digest)
    ):
        raise CLIInputError(f"{label} must contain one exact identity receipt digest")
    return {"identity_receipt_sha256": str(digest)}

def _write_json(payload: object) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(payload))

def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise CLIInputError(
            "--at must be an exact UTC YYYY-MM-DDTHH:MM:SSZ timestamp"
        ) from error


"""Deterministic canonical JSON bytes and SHA-256 helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json_bytes(value: object) -> bytes:
    """Serialize one compact sorted UTF-8 JSON value with one trailing newline."""

    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_event_bytes(event: Mapping[str, object]) -> bytes:
    """Return the exact unsigned bytes covered by an event's hash."""

    unsigned = dict(event)
    unsigned.pop("event_sha256", None)
    return canonical_json_bytes(unsigned)


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def seal_event(event: Mapping[str, object]) -> dict[str, object]:
    """Attach the digest of the exact canonical unsigned event bytes."""

    sealed = dict(event)
    sealed.pop("event_sha256", None)
    sealed["event_sha256"] = sha256_hex(canonical_event_bytes(sealed))
    return sealed


def strict_json_loads(value: bytes | str) -> Any:
    """Parse JSON while rejecting JavaScript non-finite numeric extensions."""

    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite JSON number rejected: {token}")

    return json.loads(value, parse_constant=reject_constant)

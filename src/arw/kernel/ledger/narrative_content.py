"""Verify retained paper text and paragraph spans without policy dependencies."""

from __future__ import annotations

import re
from pathlib import Path

from arw.kernel.core.canonical import sha256_hex
from arw.kernel.ledger.source_locations import MAX_SOURCE_BYTES, read_retained_bytes
from arw.kernel.state.narrative_realization import NarrativeRealization


class NarrativeRealizationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def paragraph_bounds(raw: bytes) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    cursor = 0
    for match in re.finditer(rb"(?:\r?\n){2,}", raw):
        fragment = raw[cursor:match.start()]
        left = len(fragment) - len(fragment.lstrip())
        right = len(fragment.rstrip())
        if right > left:
            result.add((cursor + left, cursor + right))
        cursor = match.end()
    fragment = raw[cursor:]
    left = len(fragment) - len(fragment.lstrip())
    right = len(fragment.rstrip())
    if right > left:
        result.add((cursor + left, cursor + right))
    return result


def verify_realization_source(
    root: Path, value: NarrativeRealization, *, source_bytes: bytes | None = None
) -> bytes:
    """Recheck real UTF-8 bytes and paragraph locators, including on replay."""
    try:
        if source_bytes is not None:
            if len(source_bytes) > MAX_SOURCE_BYTES:
                raise NarrativeRealizationError("narrative_source_invalid", "supplied source exceeds the retained source budget")
            cursor = Path(root)
            if any(path.is_symlink() for path in (cursor, *cursor.parents)):
                raise NarrativeRealizationError("narrative_source_invalid", "source root contains a symlink")
            for part in value.source_path.split("/"):
                cursor /= part
                if cursor.is_symlink():
                    raise NarrativeRealizationError("narrative_source_invalid", "source path contains a symlink")
            if cursor.exists() and read_retained_bytes(root, value.source_path, max_bytes=8_388_608) != source_bytes:
                raise NarrativeRealizationError("narrative_source_digest_mismatch", "retained source differs from supplied bytes")
        raw = source_bytes if source_bytes is not None else read_retained_bytes(
            root, value.source_path, max_bytes=8_388_608
        )
        raw.decode("utf-8")
    except NarrativeRealizationError:
        raise
    except (UnicodeError, ValueError, OSError) as error:
        raise NarrativeRealizationError("narrative_source_invalid", "source is not retained UTF-8 text") from error
    if sha256_hex(raw) != value.source_sha256:
        raise NarrativeRealizationError("narrative_source_digest_mismatch", "source bytes differ from declared digest")
    paragraphs = paragraph_bounds(raw)
    for node in value.nodes:
        span = node.span
        if (span.start, span.end) not in paragraphs or sha256_hex(raw[span.start:span.end]) != span.sha256:
            raise NarrativeRealizationError("narrative_span_invalid", f"node {node.node_id} does not bind a current paragraph")
    return raw

"""Versioned semantic normalization and equivalence receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from arw.canonical import canonical_json_bytes
from arw.graph_models import GRAPH_NORMALIZATION_ORACLE, GraphOracleComparison


class GraphEquivalenceError(ValueError):
    """Two projection/query results differ under the declared oracle."""


_NON_SEMANTIC_KEYS = frozenset(
    {
        "backend_row_id",
        "planner_time_ms",
        "elapsed_ms",
        "process_id",
        "temporary_path",
        # Generation identity is a disposable backend coordinate.  The
        # canonical watermark, source/payload/evidence digests remain in the
        # normalized record and are the semantic equivalence boundary.
        "projection_generation_id",
        "projection_manifest_sha256",
    }
)


def normalize_for_oracle(value: Any) -> Any:
    """Remove only backend nondeterminism and recursively sort semantic records."""

    if isinstance(value, Mapping):
        return {
            key: normalize_for_oracle(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            if key not in _NON_SEMANTIC_KEYS
        }
    if isinstance(value, (list, tuple)):
        normalized = [normalize_for_oracle(item) for item in value]
        if all(isinstance(item, Mapping) for item in normalized):
            normalized.sort(key=lambda item: canonical_json_bytes(item))
        return normalized
    return value


def normalized_bytes(value: Any) -> bytes:
    return canonical_json_bytes(normalize_for_oracle(value))


def normalized_sha256(value: Any) -> str:
    return hashlib.sha256(normalized_bytes(value)).hexdigest()


def compare_normalized(
    left: Any,
    right: Any,
    *,
    left_label: str,
    right_label: str,
) -> GraphOracleComparison:
    left_raw = normalized_bytes(left)
    right_raw = normalized_bytes(right)
    left_digest = hashlib.sha256(left_raw).hexdigest()
    right_digest = hashlib.sha256(right_raw).hexdigest()
    pair_digest = hashlib.sha256(left_raw + b"\0" + right_raw).hexdigest()
    diff_digest = None if left_raw == right_raw else pair_digest
    return GraphOracleComparison(
        schema_version="1.0.0",
        oracle_version=GRAPH_NORMALIZATION_ORACLE,
        left_label=left_label,
        right_label=right_label,
        left_normalized_sha256=left_digest,
        right_normalized_sha256=right_digest,
        equal=left_raw == right_raw,
        diff_sha256=diff_digest,
        normalized_bytes_sha256=pair_digest,
    )


def assert_equivalent(left: Any, right: Any, *, left_label: str, right_label: str) -> GraphOracleComparison:
    comparison = compare_normalized(left, right, left_label=left_label, right_label=right_label)
    if not comparison.equal:
        raise GraphEquivalenceError(
            f"{left_label} and {right_label} differ: "
            f"{comparison.left_normalized_sha256} != {comparison.right_normalized_sha256}"
        )
    return comparison


def normalize_query_page(operation: str, rows: Sequence[Mapping[str, Any]], *, cursor: str | None = None) -> dict[str, Any]:
    """Normalize query rows by semantic identity, retaining evidence digests."""

    normalized_rows = [normalize_for_oracle(row) for row in rows]
    normalized_rows.sort(key=lambda row: canonical_json_bytes(row))
    return {"operation": operation, "rows": normalized_rows, "cursor": cursor}

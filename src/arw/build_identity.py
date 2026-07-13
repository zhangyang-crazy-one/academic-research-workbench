"""Load the stage-relative, digest-checked packaged build identity."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arw.schema_registry import (
    SchemaRegistryError,
    aggregate_schema_sha256,
    validate_phase1_instance,
)


class BuildIdentityError(ValueError):
    """Raised when installed build identity bytes are absent, unsafe, or invalid."""


def load_packaged_build_identity() -> tuple[dict[str, Any], str]:
    root_value = os.environ.get("ARW_PLUGIN_ROOT")
    identity_value = os.environ.get("ARW_BUILD_IDENTITY")
    if not root_value or not identity_value:
        raise BuildIdentityError("stage-relative build identity configuration is required")

    root = Path(root_value).resolve()
    raw_identity = Path(identity_value)
    identity_path = raw_identity.resolve()
    if (
        raw_identity.is_symlink()
        or not root.is_dir()
        or not identity_path.is_relative_to(root)
        or identity_path.name != "build-identity.json"
        or not identity_path.is_file()
    ):
        raise BuildIdentityError("build identity must be a regular file inside the plugin root")
    try:
        raw = identity_path.read_bytes()
        identity = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BuildIdentityError(f"build identity is unreadable: {error}") from error
    if not isinstance(identity, dict):
        raise BuildIdentityError("build identity must be a JSON object")
    try:
        validate_phase1_instance("build-identity.schema.json", identity)
    except SchemaRegistryError as error:
        raise BuildIdentityError(f"build identity is invalid: {error}") from error
    schema_entries: list[tuple[str, str]] = []
    schema_root = Path(os.environ.get("ARW_SCHEMA_ROOT", "")).resolve()
    if not schema_root.is_dir() or not schema_root.is_relative_to(root):
        raise BuildIdentityError("packaged schema root must be inside the plugin root")
    for entry in identity["schemas"]["files"]:
        relative = entry["path"]
        expected = entry["sha256"]
        candidate = (root / relative).resolve()
        if (
            not relative.startswith("share/arw/schemas/")
            or not candidate.is_relative_to(schema_root)
            or not candidate.is_file()
            or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected
        ):
            raise BuildIdentityError(f"packaged schema digest mismatch: {relative}")
        schema_entries.append((relative, expected))
    if aggregate_schema_sha256(schema_entries) != identity["schemas"]["aggregate_sha256"]:
        raise BuildIdentityError("packaged schema aggregate digest mismatch")
    return identity, hashlib.sha256(raw).hexdigest()

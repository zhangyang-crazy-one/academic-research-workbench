"""Load the stage-relative, digest-checked packaged build identity."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arw.schema_registry import SchemaRegistryError, validate_phase1_instance


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
    return identity, hashlib.sha256(raw).hexdigest()

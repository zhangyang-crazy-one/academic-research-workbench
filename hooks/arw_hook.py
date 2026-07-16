#!/usr/bin/env python3
"""Adapt Codex lifecycle hook wire events into bounded ARW observations.

Codex owns stdin/stdout for lifecycle hooks.  This executable therefore emits
only the official Codex output shape on stdout.  A redacted, immutable receipt
is written below ``PLUGIN_DATA`` for later parent-side consumption; the receipt
is observational and cannot mutate a run, admit evidence, retry work, or decide
a gate.  Hook absence, distrust, timeout, or failure consequently leaves every
canonical control with the parent.

The module deliberately has no import from ``arw``.  In particular it never
opens a workspace journal, state projection, assignment, proposal, transcript,
or credential store.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


MAX_INPUT_BYTES = 64 * 1024
MAX_DEFINITION_BYTES = 256 * 1024
RECEIPT_SCHEMA = "arw.codex-hook-observation.v1"
PERMISSION_MODES = frozenset(
    {"default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"}
)
PARENT_CONTROLS = ("runtime", "mcp", "integrity", "gate", "provenance")

_COMMON_FIELDS = {
    "session_id",
    "transcript_path",
    "cwd",
    "hook_event_name",
    "model",
    "permission_mode",
}
_EVENT_FIELDS = {
    "SessionStart": _COMMON_FIELDS | {"source"},
    "SubagentStop": _COMMON_FIELDS
    | {
        "turn_id",
        "agent_id",
        "agent_type",
        "agent_transcript_path",
        "last_assistant_message",
        "stop_hook_active",
    },
    "Stop": _COMMON_FIELDS
    | {"turn_id", "last_assistant_message", "stop_hook_active"},
}
_SESSION_SOURCES = frozenset({"startup", "resume", "clear", "compact"})


class HookWireError(ValueError):
    """A hook input or installed-plugin boundary failed closed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DuplicateKey(ValueError):
    pass


def _reject_json_constant(token: str) -> None:
    raise ValueError(token)


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _bounded_string(value: object, *, nullable: bool = False, limit: int = 4096) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, str) or "\x00" in value:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return 0 < len(encoded) <= limit


def _read_input() -> tuple[bytes, Mapping[str, Any]]:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise HookWireError("input-too-large")
    if not raw.strip():
        raise HookWireError("empty-input")
    try:
        value = json.loads(
            raw,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_object_pairs,
        )
    except _DuplicateKey:
        raise HookWireError("duplicate-input-key") from None
    except (RecursionError, TypeError, UnicodeDecodeError, ValueError):
        raise HookWireError("invalid-json") from None
    if not isinstance(value, Mapping):
        raise HookWireError("input-not-object")
    return raw, value


def _validate_official_input(value: Mapping[str, Any]) -> str:
    event = value.get("hook_event_name")
    if not isinstance(event, str) or event not in _EVENT_FIELDS:
        raise HookWireError("unsupported-hook-event")
    if set(value) != _EVENT_FIELDS[event]:
        raise HookWireError("official-schema-field-mismatch")

    if not _bounded_string(value["session_id"], limit=512):
        raise HookWireError("invalid-session-id")
    if not _bounded_string(value["cwd"], limit=4096):
        raise HookWireError("invalid-cwd")
    if not _bounded_string(value["model"], limit=512):
        raise HookWireError("invalid-model")
    if not _bounded_string(value["transcript_path"], nullable=True, limit=4096):
        raise HookWireError("invalid-transcript-path")
    if (
        not isinstance(value["permission_mode"], str)
        or value["permission_mode"] not in PERMISSION_MODES
    ):
        raise HookWireError("invalid-permission-mode")

    if event == "SessionStart":
        if not isinstance(value["source"], str) or value["source"] not in _SESSION_SOURCES:
            raise HookWireError("invalid-session-source")
        return event

    if not _bounded_string(value["turn_id"], limit=512):
        raise HookWireError("invalid-turn-id")
    if not _bounded_string(value["last_assistant_message"], nullable=True, limit=48 * 1024):
        raise HookWireError("invalid-last-message")
    if type(value["stop_hook_active"]) is not bool:
        raise HookWireError("invalid-stop-hook-active")

    if event == "SubagentStop":
        if not _bounded_string(value["agent_id"], limit=512):
            raise HookWireError("invalid-agent-id")
        if not _bounded_string(value["agent_type"], limit=512):
            raise HookWireError("invalid-agent-type")
        if not _bounded_string(value["agent_transcript_path"], nullable=True, limit=4096):
            raise HookWireError("invalid-agent-transcript-path")
    return event


def _installed_definition_digest() -> tuple[str, str]:
    root_value = os.environ.get("PLUGIN_ROOT")
    if not root_value or not os.path.isabs(root_value) or "\x00" in root_value:
        raise HookWireError("plugin-root-missing")
    try:
        root = Path(root_value).resolve(strict=True)
    except (OSError, RuntimeError):
        raise HookWireError("plugin-root-invalid") from None
    if not root.is_dir():
        raise HookWireError("plugin-root-invalid")

    components: list[bytes] = []
    for relative in ("hooks/hooks.json", "hooks/arw_hook.py"):
        candidate = root / relative
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            metadata = resolved.stat()
        except (OSError, RuntimeError, ValueError):
            raise HookWireError("hook-definition-missing") from None
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_DEFINITION_BYTES:
            raise HookWireError("hook-definition-invalid")
        try:
            body = resolved.read_bytes()
        except OSError:
            raise HookWireError("hook-definition-unreadable") from None
        components.extend((relative.encode("utf-8"), b"\x00", body, b"\x00"))
    return _digest(b"".join(components)), _digest(str(root))


def _redacted_receipt(
    raw: bytes,
    value: Mapping[str, Any],
    event: str,
    *,
    definition_sha256: str,
    plugin_root_sha256: str,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "authority": "observational",
        "hook_event_name": event,
        "input_sha256": _digest(raw),
        "hook_definition_sha256": definition_sha256,
        "plugin_root_sha256": plugin_root_sha256,
        "session_id_sha256": _digest(value["session_id"]),
        "turn_id_sha256": _digest(value["turn_id"]) if "turn_id" in value else None,
        "subject_id_sha256": _digest(value["agent_id"]) if "agent_id" in value else None,
        "agent_type_sha256": _digest(value["agent_type"]) if "agent_type" in value else None,
        "model_sha256": _digest(value["model"]),
        "cwd_sha256": _digest(value["cwd"]),
        "permission_mode": value["permission_mode"],
        "source": value.get("source"),
        "stop_hook_active": value.get("stop_hook_active"),
        "status": "observed",
        "redacted_error_code": None,
        "parent_controls": [
            {"surface": surface, "parent_enforced": True, "hook_bypass_safe": True}
            for surface in PARENT_CONTROLS
        ],
        "receipt_sha256": "0" * 64,
    }
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256")
    receipt["receipt_sha256"] = _digest(_canonical_bytes(unsigned))
    return receipt


def _receipt_directory() -> Path:
    data_value = os.environ.get("PLUGIN_DATA")
    if not data_value or not os.path.isabs(data_value) or "\x00" in data_value:
        raise HookWireError("plugin-data-missing")
    data_path = Path(data_value)
    try:
        data_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = data_path.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise HookWireError("plugin-data-invalid")
        root = data_path.resolve(strict=True)
    except HookWireError:
        raise
    except (OSError, RuntimeError):
        raise HookWireError("plugin-data-invalid") from None
    if not root.is_dir():
        raise HookWireError("plugin-data-invalid")
    directory = root
    for component in ("hook-observations", "v1"):
        candidate = directory / component
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError:
            raise HookWireError("plugin-data-boundary") from None
        try:
            metadata = candidate.lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise HookWireError("plugin-data-boundary")
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except HookWireError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise HookWireError("plugin-data-boundary") from None
        directory = resolved
    return directory


def _persist_receipt(receipt: Mapping[str, Any]) -> None:
    body = _canonical_bytes(receipt)
    digest = receipt["receipt_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise HookWireError("receipt-digest-invalid")
    directory = _receipt_directory()
    path = directory / f"{digest}.json"
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=directory,
            prefix=f".{digest}.",
            suffix=".tmp",
        )
    except OSError:
        raise HookWireError("receipt-write-failed") from None
    temporary = Path(temporary_name)
    try:
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise HookWireError("receipt-write-failed") from None
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or path.read_bytes() != body:
                    raise HookWireError("receipt-collision") from None
            except HookWireError:
                raise
            except OSError:
                raise HookWireError("receipt-unreadable") from None
        except OSError:
            raise HookWireError("receipt-write-failed") from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _official_output(event: str | None, *, failed: bool = False) -> dict[str, Any]:
    if failed:
        return {
            "continue": True,
            "systemMessage": (
                "ARW observational hook failed closed; parent-owned runtime, evidence, "
                "provenance, and gate controls remain authoritative."
            ),
        }
    if event == "SessionStart":
        return {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "ARW hook context is observational only. Canonical state, evidence "
                    "admission, retries, provenance, and gates remain parent-owned."
                ),
            },
        }
    return {"continue": True}


def _emit(output: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(_canonical_bytes(output))
    sys.stdout.buffer.flush()


def main() -> int:
    event: str | None = None
    try:
        raw, value = _read_input()
        event = _validate_official_input(value)
        definition_sha256, plugin_root_sha256 = _installed_definition_digest()
        receipt = _redacted_receipt(
            raw,
            value,
            event,
            definition_sha256=definition_sha256,
            plugin_root_sha256=plugin_root_sha256,
        )
        _persist_receipt(receipt)
    except HookWireError as error:
        _emit(_official_output(event, failed=True))
        sys.stderr.write(f"arw_hook: {error.code}\n")
        return 1
    _emit(_official_output(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

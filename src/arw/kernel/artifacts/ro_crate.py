"""Bounded, read-only RO-Crate export over one replayed canonical run."""

from __future__ import annotations

import base64
import ctypes
import errno
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
import zlib
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

import portalocker
from portalocker.exceptions import LockException

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.core.privacy import SecretRejected, reject_secret_shapes
from arw.kernel.ledger.execution_provenance import (
    ExecutionProvenanceError,
    project_execution_provenance,
)
from arw.kernel.ledger.journal import (
    JournalError,
    _discover_segments,
    _read_lock,
    _read_manifest,
    _replay_unlocked,
    require_existing_run_root,
)
from arw.kernel.ledger.manifests import ManifestError, load_artifact_manifest
from arw.kernel.ledger.source_locations import SourceLocatorError, read_retained_bytes
from arw.kernel.state.models import ArtifactAcceptedPayload

RO_CONTEXT = "https://w3id.org/ro/crate/1.3/context"
RO_PROFILE = "https://w3id.org/ro/crate/1.3"
PROVENANCE_PROFILE = "https://w3id.org/ro/wfrun/provenance/0.6"
WORKFLOW_PROFILE = "https://w3id.org/ro/wfrun/workflow/0.6"
PROCESS_PROFILE = "https://w3id.org/ro/wfrun/process/0.6"
WORKFLOW_RO_PROFILE = "https://w3id.org/workflowhub/workflow-ro-crate/1.1"
WORKFLOW_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"
PROFILE_ENTITIES = (
    (PROCESS_PROFILE, "Process Run Crate", "0.6"),
    (WORKFLOW_PROFILE, "Workflow Run Crate", "0.6"),
    (WORKFLOW_RO_PROFILE, "Workflow RO-Crate", "1.1"),
    (PROVENANCE_PROFILE, "Provenance Run Crate", "0.6"),
)
METADATA_NAME = "ro-crate-metadata.json"
BINDING_NAME = "arw-source-binding.json"
MAX_EVENTS = 4096
MAX_ENTRIES = 512
MAX_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
NORMALIZED_MTIME = 315532800  # 1980-01-01T00:00:00Z, the earliest ZIP timestamp.
_PRIVATE = re.compile(
    r"(?i)(?:^|[./_-])(?:private|sensitive|secret|credential|token|key|password|restricted|raw|scratch)(?:$|[./_-])"
)
_WINDOWS_DEVICE = re.compile(r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)")
_JSON_SECRET_KEY_SUFFIXES = (
    "password",
    "passwd",
    "passphrase",
    "apikey",
    "accesskey",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "secret",
    "authorization",
    "privatekey",
    "credential",
    "cookie",
    "bearer",
    "token",
)


class CrateError(ValueError):
    """The requested snapshot or crate is unsafe, incomplete, or over budget."""


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or path.as_posix() != name
        or ":" in name.split("/", 1)[0]
        or any(
            part.endswith((".", " ")) or _WINDOWS_DEVICE.match(part)
            for part in path.parts
        )
    ):
        raise CrateError("unsafe crate entry path")
    return name


def _budget(entries: dict[str, bytes], *, max_entries: int, max_bytes: int) -> None:
    if not 1 <= max_entries <= MAX_ENTRIES or not 1 <= max_bytes <= MAX_BYTES:
        raise CrateError("export budget exceeds supported bounds")
    if len(entries) > max_entries:
        raise CrateError("crate entry limit exceeded")
    if any(len(value) > MAX_FILE_BYTES for value in entries.values()):
        raise CrateError("crate member exceeds per-file byte limit")
    if sum(len(value) for value in entries.values()) > max_bytes:
        raise CrateError("crate byte limit exceeded")


def _private_text(value: str) -> bool:
    if _PRIVATE.search(value):
        return True
    try:
        reject_secret_shapes(value)
    except SecretRejected:
        return True
    return False


def _language_identity(source: dict[str, Any]) -> dict[str, str] | None:
    """Admit only the complete identity in a parent-accepted workflow source."""
    if not isinstance(source, dict):
        return None
    candidate = source.get("programming_language")
    if not isinstance(candidate, dict):
        return None
    fields = ("uri", "name", "url", "version")
    if set(candidate) != set(fields) or any(
        not isinstance(candidate[field], str)
        or not candidate[field].strip()
        or (
            field in {"uri", "url"}
            and any(character.isspace() for character in candidate[field])
        )
        or _private_text(candidate[field])
        for field in fields
    ):
        return None
    try:
        identity_uri = urlsplit(candidate["uri"])
        language_url = urlsplit(candidate["url"])
    except ValueError:
        return None
    if (
        not identity_uri.scheme
        or identity_uri.scheme.lower() in {"javascript", "data", "file"}
        or (identity_uri.scheme in {"http", "https"} and not identity_uri.netloc)
        or identity_uri.username
        or identity_uri.password
        or language_url.scheme not in {"http", "https"}
        or not language_url.netloc
        or language_url.username
        or language_url.password
    ):
        return None
    return {field: candidate[field] for field in fields}


def _is_lock_contention(error: BaseException) -> bool:
    if isinstance(error, LockException):
        return True
    if isinstance(error, OSError):
        return error.errno in {errno.EAGAIN, errno.EACCES}
    return False

def _event_fact(event: Any) -> dict[str, Any]:
    payload = event.payload.model_dump(mode="json")
    if event.event_type == "execution_provenance.context_accepted":
        payload.pop("runtime", None)
        source = payload["workflow_source"]
        source.pop("content_base64", None)
        source["programming_language"] = _language_identity(source)
        if _private_text(source["relative_path"]):
            source["relative_path_sha256"] = sha256_hex(
                source["relative_path"].encode()
            )
            source["relative_path"] = None
        for tool in payload["tools"]:
            if _private_text(tool["name"]):
                tool["name"] = tool["tool_id"]
            if tool.get("version") and _private_text(tool["version"]):
                tool["version"] = None
    elif event.event_type == "execution_provenance.dataset_metadata_accepted":
        for field in ("name", "description", "license"):
            try:
                reject_secret_shapes(payload[field])
            except SecretRejected as error:
                raise CrateError(
                    "owner metadata contains secret-shaped data"
                ) from error
        payload = {
            key: payload[key]
            for key in ("name", "description", "date_published", "license")
        }
    elif event.event_type == "execution_provenance.action_finished":
        payload = {key: payload[key] for key in ("action_id", "ended_at", "outcome")}
    elif event.event_type == "execution_provenance.artifact_bound":
        if _private_text(payload["relative_path"]):
            payload["relative_path_sha256"] = sha256_hex(
                payload["relative_path"].encode()
            )
            payload["relative_path"] = None
    return {
        "event_id": event.event_id,
        "event_sha256": event.event_sha256,
        "payload": payload,
    }


def _execution_facts(events: Any) -> dict[str, Any]:
    state = project_execution_provenance(events)
    context = _event_fact(state.context) if state.context else None
    gaps = list(state.coverage_gaps)
    if context and context["payload"]["workflow_source"]["relative_path"] is None:
        gaps.append("workflow_source_path_private")
    tools = getattr(state.context.payload, "tools", ()) if state.context else ()
    if any(
        _private_text(tool.name)
        or (tool.version is not None and _private_text(tool.version))
        for tool in tools
    ):
        gaps.append("private_tool_identity")
    if (
        context
        and context["payload"]["workflow_source"]["programming_language"] is None
    ):
        gaps.append("workflow_language_private_or_unknown")
    if any(_private_text(getattr(event.payload, "relative_path", "")) for event in state.bindings):
        gaps.append("private_action_path")
    return {
        "context": context,
        "dataset_metadata": _event_fact(state.dataset_metadata)
        if state.dataset_metadata
        else None,
        "actions": [
            {
                "started": _event_fact(action.started),
                "finished": _event_fact(action.finished) if action.finished else None,
            }
            for action in state.actions
        ],
        "bindings": [_event_fact(event) for event in state.bindings],
        "intent_only_attempt_ids": list(state.intent_only_attempt_ids),
        "coverage_gaps": gaps,
    }


def _packaged_data_ref(
    event: dict[str, Any], included: list[dict[str, Any]]
) -> str | None:
    payload = event["payload"]
    if payload["source_kind"] != "artifact":
        return None
    for item in included:
        if (
            item.get("source_event_id") == payload["source_event_id"]
            and item.get("source_relative_path") == payload["relative_path"]
            and item.get("source_event_sha256") == payload["source_event_sha256"]
            and item.get("source_manifest_sha256") == payload["source_manifest_sha256"]
            and item.get("source_content_sha256") == payload["content_sha256"]
            and item.get("contentSize") == payload["byte_count"]
            and item.get("sha256") == payload["content_sha256"]
        ):
            return item["path"]
    return None


def _profile_missing(facts: dict[str, Any], workflow_file: str | None) -> list[str]:
    missing = list(facts["coverage_gaps"])
    if facts["context"] is None:
        missing.append("workflow_context")
    if workflow_file is None:
        missing.append("workflow_source_file")
    if facts["context"] is not None and not _language_identity(
        facts["context"]["payload"]["workflow_source"]
    ):
        missing.append("workflow_language_identity")
    if facts["dataset_metadata"] is None:
        missing.append("dataset_metadata")
    actions = facts["actions"]
    if not any(a["started"]["payload"]["kind"] == "workflow" for a in actions):
        missing.append("workflow_action")
    if not any(a["started"]["payload"]["kind"] == "tool" for a in actions):
        missing.append("tool_action")
    if any(a["finished"] is None for a in actions):
        missing.append("unfinished_action")
    if any(
        a["finished"] is not None and a["finished"]["payload"]["outcome"] == "cancelled"
        for a in actions
    ):
        missing.append("cancelled_action_status")
    return sorted(set(missing))


def _arw_missing(
    facts: dict[str, Any], workflow_file: str | None, included: list[dict[str, Any]]
) -> list[str]:
    missing = _profile_missing(facts, workflow_file)
    if any(_packaged_data_ref(event, included) is None for event in facts["bindings"]):
        missing.append("digest_only_action_data")
    return sorted(set(missing))


def _should_warnings(
    facts: dict[str, Any], included: list[dict[str, Any]]
) -> list[str]:
    warnings: list[str] = []
    if any(
        event["payload"]["direction"] == "output"
        and _packaged_data_ref(event, included) is None
        for event in facts["bindings"]
    ):
        warnings.append("action_result_body_omitted")
    return warnings


def _ref(identifier: str) -> dict[str, str]:
    return {"@id": identifier}


def _execution_graph(
    root: dict[str, Any], graph: list[dict[str, Any]], binding: dict[str, Any]
) -> list[dict[str, Any]]:
    facts = binding["execution_facts"]
    workflow = binding.get("workflow_file")
    context = facts["context"]
    if not workflow or not context:
        return []
    extra: list[dict[str, Any]] = []
    workflow_node = next(node for node in graph if node["@id"] == workflow)
    steps = context["payload"]["steps"]
    tools = context["payload"]["tools"]
    language = _language_identity(context["payload"]["workflow_source"])
    if language is not None:
        workflow_node["programmingLanguage"] = _ref(language["uri"])
        extra.append(
            {
                "@id": language["uri"],
                "@type": "ComputerLanguage",
                "name": language["name"],
                "url": _ref(language["url"]),
                "version": language["version"],
            }
        )
    workflow_node["hasPart"] = [_ref(f"#tool/{tool['tool_id']}") for tool in tools]
    workflow_node["step"] = [_ref(f"#step/{step['step_id']}") for step in steps]
    for tool in tools:
        extra.append(
            {
                "@id": f"#tool/{tool['tool_id']}",
                "@type": "SoftwareApplication",
                "name": tool["name"],
                **({"softwareVersion": tool["version"]} if tool.get("version") else {}),
            }
        )
    for step in steps:
        extra.append(
            {
                "@id": f"#step/{step['step_id']}",
                "@type": "HowToStep",
                "position": step["position"],
                "workExample": _ref(f"#tool/{step['tool_id']}"),
            }
        )
    actions = facts["actions"]
    workflows = [a for a in actions if a["started"]["payload"]["kind"] == "workflow"]
    root["mainEntity"] = _ref(workflow)
    root["mentions"] = [
        _ref(f"#action/{a['started']['payload']['action_id']}") for a in workflows
    ]
    for action in actions:
        start = action["started"]["payload"]
        finish = action["finished"]["payload"] if action["finished"] else None
        is_tool = start["kind"] == "tool"
        action_id = f"#action/{start['action_id']}"
        node: dict[str, Any] = {
            "@id": action_id,
            "@type": "CreateAction",
            "instrument": _ref(f"#tool/{start['tool_id']}" if is_tool else workflow),
            "startTime": start["started_at"],
        }
        if finish:
            node["endTime"] = finish["ended_at"]
            if finish["outcome"] in {"succeeded", "failed"}:
                node["actionStatus"] = _ref(
                    "https://schema.org/CompletedActionStatus"
                    if finish["outcome"] == "succeeded"
                    else "https://schema.org/FailedActionStatus"
                )
        input_ids = [
            path
            for event in facts["bindings"]
            if event["payload"]["action_id"] == start["action_id"]
            and event["payload"]["direction"] == "input"
            if (path := _packaged_data_ref(event, binding["included"])) is not None
        ]
        output_ids = [
            path
            for event in facts["bindings"]
            if event["payload"]["action_id"] == start["action_id"]
            and event["payload"]["direction"] == "output"
            if (path := _packaged_data_ref(event, binding["included"])) is not None
        ]
        if input_ids:
            node["object"] = [_ref(value) for value in input_ids]
        if output_ids:
            node["result"] = [_ref(value) for value in output_ids]
        extra.append(node)
        if is_tool:
            extra.append(
                {
                    "@id": f"#control/{start['action_id']}",
                    "@type": "ControlAction",
                    "instrument": _ref(f"#step/{start['step_id']}"),
                    "object": _ref(action_id),
                }
            )
    return extra


def _metadata_bytes(
    files: dict[str, bytes],
    *,
    binding: dict[str, Any],
) -> bytes:
    descriptor = {
        "@id": METADATA_NAME,
        "@type": "CreativeWork",
        "about": {"@id": "./"},
        "conformsTo": {"@id": RO_PROFILE},
    }
    root = {
        "@id": "./",
        "@type": "Dataset",
        "hasPart": [{"@id": name} for name in sorted(files)],
    }
    owner = binding.get("dataset_metadata")
    if owner is not None:
        payload = owner["payload"]
        root.update(
            name=payload["name"],
            description=payload["description"],
            datePublished=payload["date_published"],
            license=payload["license"],
        )
    if binding["profile_status"] == "pass":
        root["conformsTo"] = [_ref(uri) for uri, _, _ in PROFILE_ENTITIES]
    included = binding["included"]
    media = {item["path"]: item["encodingFormat"] for item in included}
    if len(media) != len(included) or set(media) != set(files) - {
        BINDING_NAME,
        binding.get("workflow_file"),
    }:
        raise CrateError("included artifact paths do not match crate files")
    graph: list[dict[str, Any]] = [descriptor, root]
    for name, raw in sorted(files.items()):
        if (
            name not in {BINDING_NAME, binding.get("workflow_file")}
            and name not in media
        ):
            raise CrateError("artifact file has no accepted media type")
        node = {
            "@id": name,
            "@type": "File",
            "sha256": sha256_hex(raw),
            "contentSize": len(raw),
            "encodingFormat": (
                "application/json"
                if name == BINDING_NAME
                else media.get(name, binding.get("workflow_media_type", "text/plain"))
            ),
        }
        if name == binding.get("workflow_file"):
            node.update(
                **{
                    "@type": [
                        "File",
                        "SoftwareSourceCode",
                        "ComputationalWorkflow",
                        "HowTo",
                    ],
                    "name": binding["execution_facts"]["context"]["payload"][
                        "workflow_source"
                    ]["relative_path"],
                }
            )
        graph.append(node)
    graph.extend(_execution_graph(root, graph, binding))
    if binding["profile_status"] == "pass":
        graph.extend(
            {"@id": uri, "@type": "CreativeWork", "name": label, "version": version}
            for uri, label, version in PROFILE_ENTITIES
        )
    context = (
        [RO_CONTEXT, WORKFLOW_CONTEXT] if binding.get("workflow_file") else RO_CONTEXT
    )
    return canonical_json_bytes({"@context": context, "@graph": graph})


def _classified_private(raw: bytes, media_type: str) -> bool:
    if media_type != "application/json" and not media_type.endswith("+json"):
        return False
    try:
        value = strict_json_loads(raw)
    except (RecursionError, UnicodeError, ValueError) as error:
        raise CrateError(
            "selected JSON body is invalid; privacy cannot be evaluated"
        ) from error
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                reject_secret_shapes(item)
            except SecretRejected as error:
                raise CrateError(
                    "selected JSON body contains a secret-shaped value"
                ) from error
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
                if any(
                    normalized_key.endswith(suffix)
                    for suffix in _JSON_SECRET_KEY_SUFFIXES
                ):
                    raise CrateError(
                        "selected JSON body contains a sensitive credential field"
                    )
                if key == "privacy_classification" and child != "shareable":
                    return True
                if key == "access_state" and child != "publicly_verified":
                    return True
                if key == "license_status" and child != "clear":
                    return True
                pending.append(child)
    return False


def _snapshot(
    run_root: Path,
    *,
    include_artifact_ids: tuple[str, ...],
    max_events: int,
    max_entries: int,
    max_bytes: int,
    lock_timeout: float,
) -> dict[str, bytes]:
    if not 1 <= max_events <= MAX_EVENTS:
        raise CrateError("event limit exceeds supported bounds")
    if len(include_artifact_ids) != len(set(include_artifact_ids)):
        raise CrateError("duplicate artifact selection")
    root = require_existing_run_root(run_root)
    try:
        with _read_lock(root, lock_timeout):
            run_manifest_info = (root / "run-manifest.json").lstat()
            if (
                not stat.S_ISREG(run_manifest_info.st_mode)
                or run_manifest_info.st_size > MAX_FILE_BYTES
            ):
                raise CrateError("run manifest is unsafe or exceeds the read budget")
            manifest, manifest_bytes = _read_manifest(root)
            segments = _discover_segments(root, manifest)
            if len(segments) > max_events:
                raise CrateError("event limit exceeded by journal segments")
            journal_bytes = 0
            for segment in segments:
                info = segment.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise CrateError("unsafe journal segment")
                journal_bytes += info.st_size
                if journal_bytes > max_bytes:
                    raise CrateError("journal byte limit exceeded")
            replay = _replay_unlocked(root)
            if replay.recovery_health != "healthy" or any(
                part.accepted_byte_end != part.byte_count for part in replay.segments
            ):
                raise CrateError("journal has an unaccepted or damaged tail")
            if replay.event_count > max_events:
                raise CrateError("event limit exceeded; complete history is required")
            accepted = [
                event
                for event in replay.events
                if event.event_type
                in {"artifact.accepted", "research_artifact_accepted"}
            ]
            if len(accepted) + 2 > max_entries:
                raise CrateError("crate entry limit exceeded")
            ids = {
                event.payload.artifact_id
                for event in accepted
                if isinstance(event.payload, ArtifactAcceptedPayload)
            }
            if set(include_artifact_ids) - ids:
                raise CrateError("selected artifact is not accepted by this run")
            files: dict[str, bytes] = {}
            included: list[dict[str, Any]] = []
            omissions: list[dict[str, str]] = []
            for event in accepted:
                assert isinstance(event.payload, ArtifactAcceptedPayload)
                source = load_artifact_manifest(root, event.payload.manifest_sha256)
                record = {
                    "source_event_id": event.event_id,
                    "source_manifest_sha256": event.payload.manifest_sha256,
                    "source_event_sha256": event.event_sha256,
                    "source_content_sha256": source.content_sha256,
                }
                if source.artifact_id not in include_artifact_ids:
                    omissions.append({**record, "reason": "body_not_selected"})
                    continue
                if _PRIVATE.search(source.artifact_kind) or _private_text(
                    source.content_path
                ):
                    omissions.append(
                        {**record, "reason": "sensitive_or_project_private"}
                    )
                    continue
                if len(files) + 3 > max_entries:
                    raise CrateError("crate entry limit exceeded")
                raw = read_retained_bytes(
                    root, source.content_path, max_bytes=MAX_FILE_BYTES
                )
                if sha256_hex(raw) != source.content_sha256:
                    raise CrateError(
                        "accepted artifact body differs from source digest"
                    )
                if _classified_private(raw, source.media_type):
                    omissions.append(
                        {**record, "reason": "sensitive_or_project_private"}
                    )
                    continue
                try:
                    reject_secret_shapes(raw)
                except SecretRejected as error:
                    raise CrateError(
                        "selected body contains secret-shaped data"
                    ) from error
                name = _safe_name(f"artifacts/{event.payload.manifest_sha256}")
                files[name] = raw
                included.append(
                    {
                        **record,
                        "source_relative_path": source.content_path,
                        "path": name,
                        "sha256": sha256_hex(raw),
                        "contentSize": len(raw),
                        "encodingFormat": source.media_type,
                    }
                )
                _budget(files, max_entries=max_entries, max_bytes=max_bytes)
            facts = _execution_facts(replay.events)
            workflow_file = None
            workflow_media_type = None
            context_event = project_execution_provenance(replay.events).context
            if context_event is not None:
                source = getattr(context_event.payload, "workflow_source", None)
                if source is not None and getattr(source, "content_base64", None) is not None:
                    raw_source = base64.b64decode(source.content_base64, validate=True)
                    rel_path = getattr(source, "relative_path", "") or ""
                    workflow_media_type = (
                        "application/json"
                        if rel_path.lower().endswith(".json")
                        else "text/plain"
                    )
                    if not _private_text(rel_path):
                        try:
                            reject_secret_shapes(raw_source)
                            if not _classified_private(raw_source, workflow_media_type):
                                workflow_file = _safe_name(f"workflow/{source.sha256}")
                                files[workflow_file] = raw_source
                        except (CrateError, SecretRejected):
                            pass
            missing = _profile_missing(facts, workflow_file)
            arw_missing = _arw_missing(facts, workflow_file, included)
            binding = {
                "schema_version": "arw.ro-crate-source-binding.v3",
                "run_id": replay.run_id,
                "created_at": manifest.created_at,
                "dataset_metadata": facts["dataset_metadata"],
                "execution_facts": facts,
                "workflow_file": workflow_file,
                "workflow_media_type": workflow_media_type if workflow_file else None,
                "run_manifest_sha256": sha256_hex(manifest_bytes),
                "ledger_head_sha256": replay.last_event_sha256,
                "event_count": replay.event_count,
                "event_sha256": [event.event_sha256 for event in replay.events],
                "included": included,
                "omissions": omissions,
                "disclosure_policy": "explicit-artifact-selection-v1",
                "target_profile": PROVENANCE_PROFILE,
                "profile_status": "pass" if not missing else "incomplete",
                "profile_missing": missing,
                "arw_completeness_status": "pass" if not arw_missing else "incomplete",
                "arw_completeness_missing": arw_missing,
                "should_warnings": _should_warnings(facts, included),
            }
            files[BINDING_NAME] = canonical_json_bytes(binding)
            files[METADATA_NAME] = _metadata_bytes(
                files,
                binding=binding,
            )
            _budget(files, max_entries=max_entries, max_bytes=max_bytes)
            # A second full replay catches out-of-band source changes while the writer lock is held.
            again = _replay_unlocked(root)
            if (
                again.recovery_health != "healthy"
                or any(
                    part.accepted_byte_end != part.byte_count for part in again.segments
                )
                or again.last_event_sha256 != replay.last_event_sha256
                or again.event_count != replay.event_count
                or again.journal_layout != replay.journal_layout
                or _read_manifest(root)[1] != manifest_bytes
            ):
                raise CrateError("source run changed during export")
            for item in included:
                source = load_artifact_manifest(root, item["source_manifest_sha256"])
                if (
                    read_retained_bytes(
                        root, source.content_path, max_bytes=MAX_FILE_BYTES
                    )
                    != files[item["path"]]
                ):
                    raise CrateError("source artifact changed during export")
            return files
    except (
        ExecutionProvenanceError,
        JournalError,
        ManifestError,
        SourceLocatorError,
        OSError,
        LockException,
    ) as error:
        if _is_lock_contention(error):
            raise CrateError(
                "read-only snapshot failed: canonical writer lock is held"
            ) from error
        raise CrateError(f"read-only snapshot failed: {error}") from error


def export_ro_crate(
    run_root: Path,
    output: Path,
    *,
    format: Literal["zip", "directory"] = "zip",
    include_artifact_ids: tuple[str, ...] = (),
    max_events: int = MAX_EVENTS,
    max_entries: int = MAX_ENTRIES,
    max_bytes: int = MAX_BYTES,
    lock_timeout: float = 0.2,
) -> dict[str, Any]:
    """Publish a complete, deterministic crate only after snapshot validation."""
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise CrateError("output already exists")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise CrateError("output parent must be an existing real directory")
    if output.resolve().is_relative_to(Path(run_root).resolve()):
        raise CrateError("output must be outside the canonical run")
    files = _snapshot(
        Path(run_root),
        include_artifact_ids=include_artifact_ids,
        max_events=max_events,
        max_entries=max_entries,
        max_bytes=max_bytes,
        lock_timeout=lock_timeout,
    )
    if format not in {"zip", "directory"}:
        raise CrateError("unsupported crate format")
    if format == "directory":
        stage = Path(tempfile.mkdtemp(prefix=".arw-crate-", dir=output.parent))
        try:
            for name, raw in sorted(files.items()):
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                target.chmod(0o644)
                os.utime(target, (NORMALIZED_MTIME, NORMALIZED_MTIME))
            directories = [stage, *(item for item in stage.rglob("*") if item.is_dir())]
            for directory in sorted(
                directories, key=lambda item: len(item.parts), reverse=True
            ):
                directory.chmod(0o755)
                os.utime(directory, (NORMALIZED_MTIME, NORMALIZED_MTIME))
            try:
                _install_directory_noreplace(stage, output)
            except FileExistsError as error:
                raise CrateError("output appeared during export") from error
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    else:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".arw-crate-", suffix=".zip", dir=output.parent
        )
        os.close(descriptor)
        stage_file = Path(temporary)
        try:
            with zipfile.ZipFile(
                stage_file, "w", compression=zipfile.ZIP_STORED
            ) as archive:
                for name, raw in sorted(files.items()):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    archive.writestr(info, raw)
            os.utime(stage_file, (NORMALIZED_MTIME, NORMALIZED_MTIME))
            os.link(stage_file, output, follow_symlinks=False)
        except FileExistsError as error:
            raise CrateError("output appeared during export") from error
        finally:
            stage_file.unlink(missing_ok=True)
    binding = strict_json_loads(files[BINDING_NAME])
    return {
        "status": "exported",
        "path": str(output),
        "entry_count": len(files),
        "profile": {
            "target": PROVENANCE_PROFILE,
            "status": binding["profile_status"],
            "missing": binding["profile_missing"],
        },
        "arw_completeness": {
            "status": binding["arw_completeness_status"],
            "missing": binding["arw_completeness_missing"],
        },
        "should_warnings": binding["should_warnings"],
    }


def _install_directory_noreplace(stage: Path, output: Path) -> None:
    """Atomically rename one complete directory without replacing any target."""
    if os.name == "nt":
        # Windows os.rename is documented to fail when dst already exists.
        try:
            os.rename(stage, output)
        except OSError as error:
            raise FileExistsError(str(error)) from error
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise CrateError("atomic no-replace directory install is unavailable")
        result = rename(
            -100, os.fsencode(stage), -100, os.fsencode(output), 1
        )  # AT_FDCWD, RENAME_NOREPLACE
    elif sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is None:
            raise CrateError("atomic no-replace directory install is unavailable")
        result = rename(os.fsencode(stage), os.fsencode(output), 4)  # RENAME_EXCL
    else:
        raise CrateError("atomic no-replace directory install is unsupported here")
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(code, os.strerror(code), output)
    raise OSError(code, os.strerror(code), output)


def _read_crate(path: Path, *, max_entries: int, max_bytes: int) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    _budget(entries, max_entries=max_entries, max_bytes=max_bytes)
    try:
        root_info = path.lstat()
    except OSError as error:
        raise CrateError(f"crate input is unavailable: {error}") from error
    if stat.S_ISDIR(root_info.st_mode):
        _read_directory(path, entries, max_entries=max_entries, max_bytes=max_bytes)
    elif stat.S_ISREG(root_info.st_mode):
        _read_zip(path, entries, max_entries=max_entries, max_bytes=max_bytes)
    else:
        raise CrateError("crate root must be a regular ZIP file or a directory")
    _check_entry_collisions(entries)
    return entries


def _read_directory(
    root: Path,
    entries: dict[str, bytes],
    *,
    max_entries: int,
    max_bytes: int,
) -> None:
    pending: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath())]
    seen_count = 0
    while pending:
        directory, relative_dir = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                seen_count += 1
                if seen_count > max_entries:
                    raise CrateError("directory entry limit exceeded")
                relative = relative_dir / child.name
                name = _safe_name(relative.as_posix())
                info = child.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append((Path(child.path), relative))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise CrateError("unsafe directory entry")
                remaining = max_bytes - sum(len(value) for value in entries.values())
                if (
                    len(entries) >= max_entries
                    or info.st_nlink != 1
                    or info.st_size > min(remaining, MAX_FILE_BYTES)
                ):
                    raise CrateError("duplicate or over-budget crate entry")
                entries[name] = read_retained_bytes(
                    root, name, max_bytes=max(1, min(remaining, MAX_FILE_BYTES))
                )
                _budget(entries, max_entries=max_entries, max_bytes=max_bytes)


def _read_at(descriptor: int, size: int, offset: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        if hasattr(os, "pread"):
            chunk = os.pread(descriptor, remaining, offset + size - remaining)
        else:
            current = os.lseek(descriptor, 0, os.SEEK_CUR)
            try:
                os.lseek(descriptor, offset + size - remaining, os.SEEK_SET)
                chunk = os.read(descriptor, remaining)
            finally:
                os.lseek(descriptor, current, os.SEEK_SET)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _preflight_zip(
    descriptor: int, archive_size: int, *, max_entries: int, max_bytes: int
) -> int:
    """Bound central-directory records before ZipFile allocates ZipInfo objects."""
    eocd_size = 22
    tail_size = min(archive_size, eocd_size + 65_535)
    tail_offset = archive_size - tail_size
    tail = _read_at(descriptor, tail_size, tail_offset)
    search_end = len(tail)
    eocd_offset = -1
    while True:
        position = tail.rfind(b"PK\x05\x06", 0, search_end)
        if position < 0 or position + eocd_size > len(tail):
            break
        comment_length = struct.unpack_from("<H", tail, position + 20)[0]
        if position + eocd_size + comment_length == len(tail):
            eocd_offset = position
            break
        search_end = position
    if eocd_offset < 0:
        raise CrateError("ZIP end-of-central-directory record is missing or invalid")
    (
        _signature,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        _comment_length,
    ) = struct.unpack_from("<4s4H2LH", tail, eocd_offset)
    absolute_eocd = tail_offset + eocd_offset
    if (
        disk_number != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or central_size > max_bytes
        or central_offset + central_size != absolute_eocd
    ):
        raise CrateError("multi-disk, ZIP64, or inconsistent ZIP layout is unsupported")
    if total_entries > max_entries:
        raise CrateError("ZIP entry limit exceeded")
    if (
        absolute_eocd >= 20
        and _read_at(descriptor, 4, absolute_eocd - 20) == b"PK\x06\x07"
    ):
        raise CrateError("ZIP64 archives are unsupported")

    directory_end = central_offset + central_size
    cursor = central_offset
    count = 0
    expanded_total = 0
    while cursor < directory_end:
        if count >= max_entries:
            raise CrateError("ZIP entry limit exceeded")
        header = _read_at(descriptor, 46, cursor)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise CrateError("invalid ZIP central-directory record")
        flags = struct.unpack_from("<H", header, 8)[0]
        compression = struct.unpack_from("<H", header, 10)[0]
        compressed_size = struct.unpack_from("<L", header, 20)[0]
        file_size = struct.unpack_from("<L", header, 24)[0]
        name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
        disk_start = struct.unpack_from("<H", header, 34)[0]
        local_offset = struct.unpack_from("<L", header, 42)[0]
        if (
            flags & (0x0001 | 0x0040)
            or compression not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            or disk_start != 0
            or compressed_size == 0xFFFFFFFF
            or file_size == 0xFFFFFFFF
            or local_offset == 0xFFFFFFFF
        ):
            raise CrateError("encrypted, ZIP64, or unsupported ZIP member")
        cursor += 46 + name_size + extra_size + comment_size
        if cursor > directory_end:
            raise CrateError("truncated ZIP central-directory record")
        count += 1
        expanded_total += file_size
        if expanded_total > max_bytes:
            raise CrateError("ZIP expanded bytes exceed limit")
    if cursor != directory_end or count != total_entries:
        raise CrateError("ZIP central-directory entry count differs from EOCD")
    return count


def _read_zip(
    path: Path,
    entries: dict[str, bytes],
    *,
    max_entries: int,
    max_bytes: int,
) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise CrateError("safe ZIP verification requires O_NOFOLLOW")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CrateError(f"ZIP input could not be opened safely: {error}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CrateError("ZIP input must be a regular file")
        if before.st_size > max_bytes:
            raise CrateError("ZIP archive exceeds byte limit")
        expected_entries = _preflight_zip(
            descriptor,
            before.st_size,
            max_entries=max_entries,
            max_bytes=max_bytes,
        )
        with (
            os.fdopen(descriptor, "rb", closefd=False) as handle,
            zipfile.ZipFile(handle) as archive,
        ):
            infos = archive.infolist()
            if len(infos) != expected_entries or len(infos) > max_entries:
                raise CrateError("ZIP entry count differs from bounded preflight")
            names: list[str] = []
            expanded_total = 0
            for info in infos:
                name = _safe_name(info.filename)
                mode = info.external_attr >> 16
                if (
                    name in names
                    or info.is_dir()
                    or info.flag_bits & 1
                    or (mode and not stat.S_ISREG(mode))
                ):
                    raise CrateError("duplicate or unsafe ZIP entry")
                if info.file_size > min(max_bytes, MAX_FILE_BYTES):
                    raise CrateError("ZIP entry exceeds verification bound")
                expanded_total += info.file_size
                if expanded_total > max_bytes:
                    raise CrateError("ZIP expanded bytes exceed limit")
                names.append(name)
            _check_name_collisions(names)
            for info, name in zip(infos, names, strict=True):
                with archive.open(info) as member:
                    raw = member.read(min(max_bytes, MAX_FILE_BYTES) + 1)
                if len(raw) != info.file_size:
                    raise CrateError("ZIP size differs from actual entry bytes")
                entries[name] = raw
        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise CrateError("ZIP input changed during verification")
    finally:
        os.close(descriptor)


def _check_name_collisions(names: list[str]) -> None:
    folded = [name.casefold() for name in names]
    if len(folded) != len(set(folded)):
        raise CrateError("crate contains case-colliding paths")
    name_set = set(names)
    for name in names:
        parts = name.split("/")
        if any("/".join(parts[:index]) in name_set for index in range(1, len(parts))):
            raise CrateError("crate file conflicts with an ancestor path")


def _check_entry_collisions(entries: dict[str, bytes]) -> None:
    _check_name_collisions(list(entries))


def _valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return len(value) == 10 and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _graph_profile_issues(
    nodes: dict[str, dict[str, Any]], binding: dict[str, Any]
) -> list[str]:
    facts = binding["execution_facts"]
    workflow = binding.get("workflow_file")
    missing = _profile_missing(facts, workflow)
    if workflow is None or facts["context"] is None:
        return missing
    root = nodes["./"]
    context = facts["context"]["payload"]
    source = context["workflow_source"]
    language = _language_identity(source)
    expected_workflow = nodes.get(workflow)
    if (
        root.get("mainEntity") != _ref(workflow)
        or expected_workflow is None
        or not {"File", "SoftwareSourceCode", "ComputationalWorkflow", "HowTo"}
        <= set(expected_workflow.get("@type", []))
        or expected_workflow.get("sha256") != source["sha256"]
        or expected_workflow.get("name") != source["relative_path"]
        or expected_workflow.get("programmingLanguage")
        != (_ref(language["uri"]) if language else None)
    ):
        missing.append("workflow_entity")
        return sorted(set(missing))
    if language is not None:
        language_node = nodes.get(language["uri"], {})
        if language_node != {
            "@id": language["uri"],
            "@type": "ComputerLanguage",
            "name": language["name"],
            "url": _ref(language["url"]),
            "version": language["version"],
        }:
            missing.append("workflow_language_entity")
    workflows = [
        a for a in facts["actions"] if a["started"]["payload"]["kind"] == "workflow"
    ]
    if root.get("mentions") != [
        _ref(f"#action/{a['started']['payload']['action_id']}") for a in workflows
    ]:
        missing.append("root_mentions")
    if expected_workflow.get("hasPart") != [
        _ref(f"#tool/{tool['tool_id']}") for tool in context["tools"]
    ]:
        missing.append("workflow_hasPart")
    if expected_workflow.get("step") != [
        _ref(f"#step/{step['step_id']}") for step in context["steps"]
    ]:
        missing.append("workflow_step")
    for step in context["steps"]:
        node = nodes.get(f"#step/{step['step_id']}", {})
        if node.get("@type") != "HowToStep" or node.get("workExample") != _ref(
            f"#tool/{step['tool_id']}"
        ):
            missing.append(f"step:{step['step_id']}")
    for tool in context["tools"]:
        if (
            nodes.get(f"#tool/{tool['tool_id']}", {}).get("@type")
            != "SoftwareApplication"
        ):
            missing.append(f"tool:{tool['tool_id']}")
    for action in facts["actions"]:
        start = action["started"]["payload"]
        finish = action["finished"]["payload"] if action["finished"] else None
        node = nodes.get(f"#action/{start['action_id']}", {})
        instrument = (
            f"#tool/{start['tool_id']}" if start["kind"] == "tool" else workflow
        )
        if (
            node.get("@type") != "CreateAction"
            or node.get("instrument") != _ref(instrument)
            or node.get("startTime") != start["started_at"]
        ):
            missing.append(f"action_instrument:{start['action_id']}")
        if (
            finish is None
            or node.get("endTime") != finish["ended_at"]
            or node.get("actionStatus")
            != _ref(
                "https://schema.org/CompletedActionStatus"
                if finish["outcome"] == "succeeded"
                else "https://schema.org/FailedActionStatus"
            )
        ):
            missing.append(f"action_outcome:{start['action_id']}")
        if start["kind"] == "tool":
            control = nodes.get(f"#control/{start['action_id']}", {})
            if (
                control.get("@type") != "ControlAction"
                or control.get("instrument") != _ref(f"#step/{start['step_id']}")
                or control.get("object") != _ref(f"#action/{start['action_id']}")
            ):
                missing.append(f"control:{start['action_id']}")
        for direction, property_name in (("input", "object"), ("output", "result")):
            expected = [
                _ref(path)
                for event in facts["bindings"]
                if event["payload"]["action_id"] == start["action_id"]
                and event["payload"]["direction"] == direction
                if (path := _packaged_data_ref(event, binding["included"])) is not None
            ]
            if node.get(property_name, []) != expected:
                missing.append(f"action_{property_name}:{start['action_id']}")
            for reference in expected:
                path = reference["@id"]
                file_node = nodes.get(path, {})
                copied = next(
                    (item for item in binding["included"] if item.get("path") == path),
                    None,
                )
                if (
                    copied is None
                    or file_node.get("@type") != "File"
                    or file_node.get("sha256") != copied["sha256"]
                    or file_node.get("contentSize") != copied["contentSize"]
                ):
                    missing.append(f"action_file:{start['action_id']}:{path}")
    return sorted(set(missing))


def verify_ro_crate(
    crate: Path,
    *,
    run_root: Path | None = None,
    max_entries: int = MAX_ENTRIES,
    max_bytes: int = MAX_BYTES,
) -> dict[str, Any]:
    """Report structural, byte and optional live-source checks independently."""
    report: dict[str, Any] = {
        "structure": {"status": "fail", "issues": []},
        "profile": {
            "target": PROVENANCE_PROFILE,
            "status": "unverified",
            "missing": [],
        },
        "base_profile": {
            "target": RO_PROFILE,
            "status": "unverified",
            "missing": [],
        },
        "metadata_completeness": {"status": "unverified", "missing": []},
        "arw_completeness": {"status": "unverified", "missing": []},
        "should_warnings": [],
        "byte_integrity": {"status": "unverified", "issues": []},
        "source_run_binding": {"status": "unverified", "issues": []},
        "digest_is_signature": False,
    }
    try:
        entries = _read_crate(Path(crate), max_entries=max_entries, max_bytes=max_bytes)
        metadata = strict_json_loads(entries[METADATA_NAME])
        binding = strict_json_loads(entries[BINDING_NAME])
        if not isinstance(binding, dict):
            raise CrateError("invalid source binding")
        expected_context = (
            [RO_CONTEXT, WORKFLOW_CONTEXT]
            if binding.get("workflow_file")
            else RO_CONTEXT
        )
        if (
            not isinstance(metadata, dict)
            or metadata.get("@context") != expected_context
        ):
            raise CrateError("wrong RO-Crate context")
        graph = metadata.get("@graph")
        if not isinstance(graph, list) or any(
            not isinstance(node, dict) for node in graph
        ):
            raise CrateError("invalid JSON-LD graph")
        if any(not isinstance(node.get("@id"), str) for node in graph):
            raise CrateError("graph entity lacks a string ID")
        nodes = {node["@id"]: node for node in graph}
        if (
            len(nodes) != len(graph)
            or not {"./", METADATA_NAME, BINDING_NAME} <= nodes.keys()
        ):
            raise CrateError("missing or duplicate crate entities")
        root = nodes["./"]
        descriptor = nodes[METADATA_NAME]
        if (
            root.get("@type") != "Dataset"
            or descriptor.get("@type") != "CreativeWork"
            or descriptor.get("about") != {"@id": "./"}
            or descriptor.get("conformsTo") != {"@id": RO_PROFILE}
        ):
            raise CrateError("invalid RO-Crate root or descriptor")
        parts = root.get("hasPart")
        if parts != [
            {"@id": name} for name in sorted(entries) if name != METADATA_NAME
        ]:
            raise CrateError("root does not enumerate all crate files")
        facts_value = binding.get("execution_facts")
        context_value = (
            facts_value.get("context") if isinstance(facts_value, dict) else None
        )
        source_value = (
            context_value.get("payload", {}).get("workflow_source", {})
            if isinstance(context_value, dict)
            else {}
        )
        language = _language_identity(source_value)
        contextual_ids = {uri for uri, _, _ in PROFILE_ENTITIES}
        if language is not None:
            contextual_ids.add(language["uri"])
        if not set(entries) <= set(nodes) or any(
            name not in entries
            and not name.startswith("#")
            and name != "./"
            and name not in contextual_ids
            for name in nodes
        ):
            raise CrateError("graph file entities do not match entries")
        if (
            not isinstance(binding, dict)
            or binding.get("schema_version") != "arw.ro-crate-source-binding.v3"
            or not isinstance(binding.get("created_at"), str)
            or not isinstance(binding.get("execution_facts"), dict)
            or binding.get("dataset_metadata")
            != binding["execution_facts"].get("dataset_metadata")
            or not isinstance(binding.get("included"), list)
            or not isinstance(binding.get("omissions"), list)
            or not all(
                isinstance(item, dict)
                for item in binding["included"] + binding["omissions"]
            )
            or binding.get("disclosure_policy") != "explicit-artifact-selection-v1"
            or binding.get("target_profile") != PROVENANCE_PROFILE
        ):
            raise CrateError("invalid source binding")
        owner = binding["dataset_metadata"]
        required_root_fields = ("name", "description", "datePublished", "license")
        semantic_issues: list[str] = []
        base_missing = [
            key
            for key in required_root_fields
            if not isinstance(root.get(key), str)
            or not root[key].strip()
            or (key == "datePublished" and not _valid_iso_date(root[key]))
        ]
        report["base_profile"] = {
            "target": RO_PROFILE,
            "status": (
                "pass"
                if not base_missing
                else (
                    "incomplete"
                    if len(base_missing) == len(required_root_fields)
                    and not any(key in root for key in required_root_fields)
                    else "fail"
                )
            ),
            "missing": base_missing,
        }
        if owner is None:
            if any(key in root for key in required_root_fields):
                semantic_issues.append("root metadata lacks an owner event")
            metadata_missing = list(required_root_fields)
        else:
            payload = owner["payload"]
            expected_root = {
                "name": payload["name"],
                "description": payload["description"],
                "datePublished": payload["date_published"],
                "license": payload["license"],
            }
            metadata_missing = []
            for key, expected in expected_root.items():
                actual = root.get(key)
                if key in base_missing or actual != expected:
                    metadata_missing.append(key)
                    semantic_issues.append(f"root {key} differs from owner event")
        report["metadata_completeness"] = {
            "status": "fail"
            if owner is not None and metadata_missing
            else ("pass" if not metadata_missing else "incomplete"),
            "missing": sorted(set(metadata_missing + semantic_issues)),
        }
        report["should_warnings"] = _should_warnings(
            binding["execution_facts"], binding["included"]
        )
        report["structure"] = {
            "status": "fail"
            if semantic_issues or (owner is not None and metadata_missing)
            else ("pass" if owner is not None else "incomplete"),
            "issues": semantic_issues
            if semantic_issues
            else ([] if owner is not None else metadata_missing),
        }
        profile_issues = _graph_profile_issues(nodes, binding)
        if report["base_profile"]["status"] != "pass":
            profile_issues.append("ro_crate_base")
        expected_claim = (
            [_ref(uri) for uri, _, _ in PROFILE_ENTITIES]
            if not profile_issues
            else None
        )
        if root.get("conformsTo") != expected_claim and (
            "conformsTo" in root or expected_claim is not None
        ):
            profile_issues.append("root_conformsTo")
        if not profile_issues and any(
            nodes.get(uri, {}).get("@type") != "CreativeWork"
            for uri, _, _ in PROFILE_ENTITIES
        ):
            profile_issues.append("profile_entities")
        report["profile"]["status"] = "pass" if not profile_issues else "incomplete"
        report["profile"]["missing"] = sorted(set(profile_issues))
        arw_issues = _arw_missing(
            binding["execution_facts"],
            binding.get("workflow_file"),
            binding["included"],
        )
        if report["metadata_completeness"]["status"] != "pass":
            arw_issues.append("dataset_metadata")
        report["arw_completeness"] = {
            "status": (
                "fail"
                if report["metadata_completeness"]["status"] == "fail"
                else ("pass" if not arw_issues else "incomplete")
            ),
            "missing": sorted(set(arw_issues)),
        }
        issues = []
        for name, raw in entries.items():
            if name == METADATA_NAME:
                continue
            node = nodes[name]
            if (
                (
                    node.get("@type") != "File"
                    and not (
                        name == binding.get("workflow_file")
                        and "File" in node.get("@type", [])
                    )
                )
                or node.get("sha256") != sha256_hex(raw)
                or node.get("contentSize") != len(raw)
            ):
                issues.append(name)
        expected_metadata = _metadata_bytes(
            {name: raw for name, raw in entries.items() if name != METADATA_NAME},
            binding=binding,
        )
        if entries[METADATA_NAME] != expected_metadata:
            issues.append(METADATA_NAME)
        report["byte_integrity"] = {
            "status": "fail" if issues else "pass",
            "issues": issues,
        }
        if run_root is not None:
            try:
                root_path = require_existing_run_root(Path(run_root))
                with _read_lock(root_path, 0.2):
                    manifest_info = (root_path / "run-manifest.json").lstat()
                    if (
                        not stat.S_ISREG(manifest_info.st_mode)
                        or manifest_info.st_size > MAX_FILE_BYTES
                    ):
                        raise CrateError("source manifest exceeds verification bounds")
                    manifest, manifest_bytes = _read_manifest(root_path)
                    segments = _discover_segments(root_path, manifest)
                    if (
                        len(segments) > MAX_EVENTS
                        or sum(segment.lstat().st_size for segment in segments)
                        > MAX_BYTES
                        or any(
                            not stat.S_ISREG(segment.lstat().st_mode)
                            for segment in segments
                        )
                    ):
                        raise CrateError("source journal exceeds verification bounds")
                    replay = _replay_unlocked(root_path)
                    if (
                        replay.recovery_health != "healthy"
                        or replay.event_count > MAX_EVENTS
                        or any(
                            part.accepted_byte_end != part.byte_count
                            for part in replay.segments
                        )
                    ):
                        raise CrateError("source journal is not healthy")
                    canonical_facts = _execution_facts(replay.events)
                    if (
                        binding.get("run_id") != manifest.run_id
                        or binding.get("created_at") != manifest.created_at
                        or binding.get("execution_facts") != canonical_facts
                        or binding.get("run_manifest_sha256")
                        != sha256_hex(manifest_bytes)
                        or binding.get("ledger_head_sha256") != replay.last_event_sha256
                        or binding.get("event_count") != replay.event_count
                        or binding.get("event_sha256")
                        != [e.event_sha256 for e in replay.events]
                    ):
                        raise CrateError("source run identity or history differs")
                    canonical_owner = canonical_facts["dataset_metadata"]
                    if canonical_owner is None:
                        if any(key in root for key in required_root_fields):
                            raise CrateError(
                                "root metadata has no canonical owner event"
                            )
                    else:
                        owner_payload = canonical_owner["payload"]
                        expected_root = {
                            "name": owner_payload["name"],
                            "description": owner_payload["description"],
                            "datePublished": owner_payload["date_published"],
                            "license": owner_payload["license"],
                        }
                        if any(
                            root.get(key) != value
                            for key, value in expected_root.items()
                        ):
                            raise CrateError(
                                "root metadata differs from canonical owner event"
                            )
                    workflow_file = binding.get("workflow_file")
                    source_context = project_execution_provenance(replay.events).context
                    wf_source = getattr(source_context.payload, "workflow_source", None) if source_context else None
                    wf_b64 = getattr(wf_source, "content_base64", None) if wf_source else None
                    if workflow_file is not None and (
                        wf_b64 is None
                        or workflow_file not in entries
                        or entries[workflow_file] != base64.b64decode(wf_b64, validate=True)
                    ):
                        raise CrateError(
                            "workflow source bytes differ from canonical event"
                        )
                    accepted = {
                        e.event_sha256: e
                        for e in replay.events
                        if e.event_type
                        in {"artifact.accepted", "research_artifact_accepted"}
                    }
                    if len(binding.get("included", [])) + len(
                        binding.get("omissions", [])
                    ) != len(accepted):
                        raise CrateError("source binding omits accepted artifacts")
                    seen: set[str] = set()
                    included_paths: set[str] = set()
                    for item in binding["included"] + binding["omissions"]:
                        event = accepted.get(item.get("source_event_sha256"))
                        if (
                            event is None
                            or event.event_sha256 in seen
                            or not isinstance(event.payload, ArtifactAcceptedPayload)
                        ):
                            raise CrateError(
                                "source binding contains unknown or duplicate acceptance"
                            )
                        seen.add(event.event_sha256)
                        source = load_artifact_manifest(
                            root_path, event.payload.manifest_sha256
                        )
                        if (
                            item.get("source_event_id") != event.event_id
                            or item.get("source_manifest_sha256")
                            != event.payload.manifest_sha256
                            or item.get("source_content_sha256")
                            != source.content_sha256
                        ):
                            raise CrateError("source artifact binding differs")
                        if "path" in item:
                            artifact_path = f"artifacts/{event.payload.manifest_sha256}"
                            if (
                                item["path"] != artifact_path
                                or artifact_path not in entries
                                or artifact_path in included_paths
                                or item.get("sha256")
                                != sha256_hex(entries[artifact_path])
                                or item.get("contentSize")
                                != len(entries[artifact_path])
                                or item.get("sha256") != source.content_sha256
                                or item.get("encodingFormat") != source.media_type
                                or item.get("source_relative_path")
                                != source.content_path
                                or _PRIVATE.search(source.artifact_kind)
                                or _private_text(source.content_path)
                                or _classified_private(
                                    entries[artifact_path], source.media_type
                                )
                            ):
                                raise CrateError(
                                    "bound crate artifact differs or is private"
                                )
                            try:
                                reject_secret_shapes(entries[artifact_path])
                            except SecretRejected as error:
                                raise CrateError(
                                    "bound crate artifact contains secret-shaped data"
                                ) from error
                            included_paths.add(artifact_path)
                        elif item.get("reason") not in {
                            "body_not_selected",
                            "sensitive_or_project_private",
                        }:
                            raise CrateError("unrecognized body omission")
                    if included_paths != {
                        name for name in entries if name.startswith("artifacts/")
                    }:
                        raise CrateError("unbound crate artifact entry")
                    report["source_run_binding"] = {"status": "pass", "issues": []}
            except (
                CrateError,
                JournalError,
                ExecutionProvenanceError,
                ManifestError,
                OSError,
                LockException,
            ) as error:
                report["source_run_binding"] = {
                    "status": "fail",
                    "issues": [str(error)],
                }
    except (
        CrateError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        zipfile.BadZipFile,
        SourceLocatorError,
        EOFError,
        NotImplementedError,
        RecursionError,
        RuntimeError,
        struct.error,
        zlib.error,
    ) as error:
        report["structure"] = {"status": "fail", "issues": [str(error)]}
    return report

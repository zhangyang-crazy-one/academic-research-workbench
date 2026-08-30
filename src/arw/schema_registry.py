"""Strict, deterministic Phase 1 JSON Schema loading and validation."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from arw.audit_dossier import AUDIT_DOSSIER_SCHEMA_NAME
from arw.file_contracts import FILE_SCHEMA_NAMES
from arw.graph_models import PHASE5_SCHEMA_NAMES, generate_phase5_schema_documents
from arw.integration_lock import integration_lock_schema_document
from arw.integrity import PHASE6_SCHEMA_NAMES, generate_phase6_schema_documents
from arw.orchestration_models import (
    PHASE4_SCHEMA_NAMES,
    generate_phase4_schema_documents,
)
from arw.research_integrity import (
    ResearchIntegrityError,
    research_integrity_contracts_schema_document,
    validate_research_integrity_contract_instance,
)

PHASE1_SCHEMA_NAMES: tuple[str, ...] = (
    "build-identity.schema.json",
    "event.schema.json",
    "mcp-read-request.schema.json",
    "mcp-read-result.schema.json",
    "route-result.schema.json",
    "run-manifest.schema.json",
    "source-manifest.schema.json",
    "version-report.schema.json",
)
QUALIFICATION_SCHEMA_NAMES: tuple[str, ...] = ("integration-lock.schema.json",)
RESEARCH_INTEGRITY_SCHEMA_NAME = "research-integrity-contracts.schema.json"
RESEARCH_INTEGRITY_SCHEMA_NAMES: tuple[str, ...] = (RESEARCH_INTEGRITY_SCHEMA_NAME,)
AUDIT_SCHEMA_NAMES: tuple[str, ...] = (AUDIT_DOSSIER_SCHEMA_NAME,)
SCHEMA_NAMES: tuple[str, ...] = (
    PHASE1_SCHEMA_NAMES
    + (
        "artifact-manifest.schema.json",
        "artifact-request.schema.json",
        "attempt-request.schema.json",
        "checkpoint-request.schema.json",
        "command-outcome.schema.json",
        "decision-request.schema.json",
        "material-passport.schema.json",
        "passport-pointer.schema.json",
        "rejection.schema.json",
        "recovery-receipt.schema.json",
        "recovery-request.schema.json",
        "resume-request.schema.json",
        "status.schema.json",
        "transition-request.schema.json",
    )
    + FILE_SCHEMA_NAMES
    + PHASE4_SCHEMA_NAMES
    + PHASE5_SCHEMA_NAMES
    + PHASE6_SCHEMA_NAMES
    + QUALIFICATION_SCHEMA_NAMES
    + RESEARCH_INTEGRITY_SCHEMA_NAMES
    + AUDIT_SCHEMA_NAMES
)


def _schema_root() -> Path:
    packaged_root = os.environ.get("ARW_SCHEMA_ROOT")
    if packaged_root:
        return Path(packaged_root).resolve()
    return Path(__file__).resolve().parents[2] / "schemas" / "v1"


class SchemaRegistryError(ValueError):
    """Raised when a checked-in Phase 1 contract is invalid or incompatible."""


def _schema_path(name: str) -> Path:
    if name not in SCHEMA_NAMES:
        raise SchemaRegistryError(f"unknown schema: {name}")
    return _schema_root() / name


def _load_document(name: str) -> dict[str, Any]:
    path = _schema_path(name)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SchemaRegistryError(f"cannot load {name}: {error}") from error
    if not isinstance(document, dict):
        raise SchemaRegistryError(f"{name} must contain a JSON object")
    return document


def _canonical_schema_bytes(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")


def _resource_registry(documents: Mapping[str, Mapping[str, Any]]) -> Registry:
    resources = []
    for name, document in documents.items():
        identifier = document.get("$id")
        if identifier is None:
            continue
        if not isinstance(identifier, str):
            raise SchemaRegistryError(f"{name} has an invalid $id")
        resources.append((identifier, Resource.from_contents(document)))
    return Registry().with_resources(resources)


def validate_schema_document(name: str, document: Mapping[str, Any]) -> None:
    """Validate a document and reject Phase 1 contract-surface drift."""

    expected = _load_document(name)
    candidate = dict(document)
    try:
        jsonschema.Draft202012Validator.check_schema(candidate)
    except jsonschema.SchemaError as error:
        raise SchemaRegistryError(
            f"invalid Draft 2020-12 schema {name}: {error}"
        ) from error

    if candidate.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SchemaRegistryError(f"{name} must declare Draft 2020-12")
    if candidate.get("$id") != expected.get("$id"):
        raise SchemaRegistryError(f"{name} has an incompatible $id")
    if candidate.get("additionalProperties") != expected.get("additionalProperties"):
        raise SchemaRegistryError(
            f"{name} has an incompatible additional-properties contract"
        )
    if candidate.get("required") != expected.get("required"):
        raise SchemaRegistryError(f"{name} has an incompatible required-field contract")
    if set(candidate.get("properties", {})) != set(expected.get("properties", {})):
        raise SchemaRegistryError(f"{name} has incompatible additional properties")

    if name == "version-report.schema.json":
        command = candidate.get("properties", {}).get("command")
        if command != {"const": "version"}:
            raise SchemaRegistryError(
                "version-report.schema.json has incompatible command"
            )
    if name in PHASE4_SCHEMA_NAMES:
        generated = generate_phase4_schema_documents()[name]
        if candidate != generated:
            raise SchemaRegistryError(
                f"{name} differs from its Phase 4 model projection"
            )
    if name in PHASE5_SCHEMA_NAMES:
        generated = generate_phase5_schema_documents()[name]
        if candidate != generated:
            raise SchemaRegistryError(
                f"{name} differs from its Phase 5 model projection"
            )
    if name in PHASE6_SCHEMA_NAMES:
        generated = generate_phase6_schema_documents()[name]
        if candidate != generated:
            raise SchemaRegistryError(
                f"{name} differs from its Phase 6 model projection"
            )
    if name in AUDIT_SCHEMA_NAMES:
        generated = generate_phase6_schema_documents()[name]
        if candidate != generated:
            raise SchemaRegistryError(
                f"{name} differs from its Phase 6 audit model projection"
            )
    if name == "integration-lock.schema.json":
        generated = integration_lock_schema_document()
        if candidate != generated:
            raise SchemaRegistryError(
                "integration-lock.schema.json differs from its model projection"
            )
    if name == RESEARCH_INTEGRITY_SCHEMA_NAME:
        generated = research_integrity_contracts_schema_document()
        if candidate != generated:
            raise SchemaRegistryError(
                f"{RESEARCH_INTEGRITY_SCHEMA_NAME} differs from its model projection"
            )


def validate_checked_in_schemas() -> tuple[str, ...]:
    documents = {name: _load_document(name) for name in SCHEMA_NAMES}
    for name, document in documents.items():
        validate_schema_document(name, document)
    _resource_registry(documents)
    return SCHEMA_NAMES


def regenerate_schemas(destination: Path) -> tuple[tuple[str, str], ...]:
    """Write a deterministic checked-schema projection and return its file digests."""

    validate_checked_in_schemas()
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    generated: list[tuple[str, str]] = []
    phase4_documents = generate_phase4_schema_documents()
    phase6_documents = generate_phase6_schema_documents()
    for name in SCHEMA_NAMES:
        if name in PHASE4_SCHEMA_NAMES:
            document = phase4_documents[name]
        elif name in PHASE5_SCHEMA_NAMES:
            document = generate_phase5_schema_documents()[name]
        elif name in PHASE6_SCHEMA_NAMES:
            document = phase6_documents[name]
        elif name == "integration-lock.schema.json":
            document = integration_lock_schema_document()
        elif name == RESEARCH_INTEGRITY_SCHEMA_NAME:
            document = research_integrity_contracts_schema_document()
        else:
            document = _load_document(name)
        rendered = _canonical_schema_bytes(document)
        path = (destination / name).resolve()
        if path.parent != destination:
            raise SchemaRegistryError(f"schema output path escapes destination: {name}")
        # pi-lens-ignore: python-path-traversal
        path.write_bytes(rendered)
        generated.append((f"schemas/v1/{name}", hashlib.sha256(rendered).hexdigest()))
    return tuple(generated)


def aggregate_schema_sha256(entries: Sequence[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for path, file_digest in entries:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def validate_phase1_instance(name: str, instance: object) -> None:
    validate_instance(name, instance)


def validate_instance(name: str, instance: object) -> None:
    documents = {
        schema_name: _load_document(schema_name) for schema_name in SCHEMA_NAMES
    }
    validate_checked_in_schemas()
    try:
        validator = jsonschema.Draft202012Validator(
            documents[name], registry=_resource_registry(documents)
        )
        validator.validate(instance)
        if name == RESEARCH_INTEGRITY_SCHEMA_NAME:
            validate_research_integrity_contract_instance(instance)
    except (
        KeyError,
        jsonschema.ValidationError,
        jsonschema.SchemaError,
        ResearchIntegrityError,
    ) as error:
        raise SchemaRegistryError(
            f"{name} instance validation failed: {error}"
        ) from error

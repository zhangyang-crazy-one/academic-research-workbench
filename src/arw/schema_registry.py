"""Strict, deterministic Phase 1 JSON Schema loading and validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource


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
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v1"


class SchemaRegistryError(ValueError):
    """Raised when a checked-in Phase 1 contract is invalid or incompatible."""


def _schema_path(name: str) -> Path:
    if name not in PHASE1_SCHEMA_NAMES:
        raise SchemaRegistryError(f"unknown Phase 1 schema: {name}")
    return _SCHEMA_ROOT / name


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
        raise SchemaRegistryError(f"invalid Draft 2020-12 schema {name}: {error}") from error

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
            raise SchemaRegistryError("version-report.schema.json has incompatible command")


def validate_checked_in_schemas() -> tuple[str, ...]:
    documents = {name: _load_document(name) for name in PHASE1_SCHEMA_NAMES}
    for name, document in documents.items():
        validate_schema_document(name, document)
    _resource_registry(documents)
    return PHASE1_SCHEMA_NAMES


def regenerate_schemas(destination: Path) -> tuple[tuple[str, str], ...]:
    """Write a deterministic checked-schema projection and return its file digests."""

    validate_checked_in_schemas()
    destination.mkdir(parents=True, exist_ok=True)
    generated: list[tuple[str, str]] = []
    for name in PHASE1_SCHEMA_NAMES:
        rendered = _canonical_schema_bytes(_load_document(name))
        path = destination / name
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
    documents = {schema_name: _load_document(schema_name) for schema_name in PHASE1_SCHEMA_NAMES}
    validate_checked_in_schemas()
    try:
        validator = jsonschema.Draft202012Validator(
            documents[name], registry=_resource_registry(documents)
        )
        validator.validate(instance)
    except (KeyError, jsonschema.ValidationError, jsonschema.SchemaError) as error:
        raise SchemaRegistryError(f"{name} instance validation failed: {error}") from error

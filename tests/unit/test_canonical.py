from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED = REPOSITORY_ROOT / "tests/fixtures/recovery/seed"
SCHEMAS = REPOSITORY_ROOT / "schemas/v1"
ZERO_HASH = "0" * 64
INITIAL_EVENT_HASH = "ccaeb5835eda28b6b374a2ced8200795e5f3a2dbf236687967d2db01e00c7b9f"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(name: str) -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMAS / name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def test_checked_in_contracts_accept_only_the_seed_shapes() -> None:
    manifest = _json(SEED / "expected-run-manifest.json")
    event = json.loads((SEED / "expected-initial-event.jsonl").read_bytes())
    _validator("run-manifest.schema.json").validate(manifest)
    _validator("event.schema.json").validate(event)
    assert event["event_type"] == "run.initialized"
    assert event["prev_event_sha256"] == ZERO_HASH


@pytest.mark.parametrize(
    ("target", "mutation"),
    [
        ("manifest", lambda value: value.update({"unknown": True})),
        ("manifest", lambda value: value.update({"run_id": 1})),
        ("manifest", lambda value: value["immutable_input"].update({"path": "../escape"})),
        ("manifest", lambda value: value["immutable_input"].update({"sha256": "A" * 64})),
        ("event", lambda value: value.update({"event_type": "checkpoint.created"})),
        ("event", lambda value: value.update({"sequence": "1"})),
        ("event", lambda value: value["payload"].update({"unknown": None})),
        ("event", lambda value: value.update({"event_sha256": "not-a-hash"})),
    ],
)
def test_checked_in_contracts_reject_coercion_unknowns_and_invalid_identity(
    target: str,
    mutation: object,
) -> None:
    if target == "manifest":
        payload = _json(SEED / "expected-run-manifest.json")
        validator = _validator("run-manifest.schema.json")
    else:
        payload = json.loads((SEED / "expected-initial-event.jsonl").read_bytes())
        validator = _validator("event.schema.json")
    mutation(payload)  # type: ignore[operator]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_canonical_bytes_and_hash_are_exactly_the_checked_in_fixture() -> None:
    assert importlib.util.find_spec("arw.canonical") is not None, (
        "expected RED: canonical serializer is not implemented"
    )
    from arw.kernel.core.canonical import canonical_event_bytes, canonical_json_bytes

    manifest = _json(SEED / "expected-run-manifest.json")
    expected_manifest = (SEED / "expected-run-manifest.json").read_bytes()
    assert canonical_json_bytes(manifest) == expected_manifest

    signed = json.loads((SEED / "expected-initial-event.jsonl").read_bytes())
    assert signed.pop("event_sha256") == INITIAL_EVENT_HASH
    unsigned = canonical_event_bytes(signed)
    assert hashlib.sha256(unsigned).hexdigest() == INITIAL_EVENT_HASH
    with pytest.raises(ValueError):
        canonical_json_bytes({"not_finite": float("nan")})


def test_strict_runtime_models_reject_noncanonical_values() -> None:
    assert importlib.util.find_spec("arw.models") is not None, (
        "expected RED: strict runtime models are not implemented"
    )
    from pydantic import ValidationError

    from arw.kernel.state.models import CanonicalEvent, RunManifest

    manifest = _json(SEED / "expected-run-manifest.json")
    event = json.loads((SEED / "expected-initial-event.jsonl").read_bytes())
    RunManifest.model_validate(manifest)
    CanonicalEvent.model_validate(event)
    with pytest.raises(ValidationError):
        RunManifest.model_validate({**manifest, "run_id": 1})
    with pytest.raises(ValidationError):
        CanonicalEvent.model_validate({**event, "expected_revision": "0"})


def test_route_hook_and_evidence_code_are_not_canonical_writers() -> None:
    paths = [REPOSITORY_ROOT / "src/arw/contracts.py"]
    paths.extend(
        path
        for path in (REPOSITORY_ROOT / "hooks").rglob("*")
        if path.suffix in {".py", ".json"}
    )
    evidence = REPOSITORY_ROOT / "src/arw/evidence.py"
    if evidence.exists():
        paths.append(evidence)
    for path in paths:
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        assert "events.jsonl" not in source
        assert "append_event(" not in source

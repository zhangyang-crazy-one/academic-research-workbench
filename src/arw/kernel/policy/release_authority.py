"""Independent GitHub release authority, separate from historical declarations.

The only signature verifier is GitHub CLI. JSON returned from that subprocess
is subjected to additional policy; caller-provided PASS strings are no proof.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

PREDICATE_TYPE = "https://academic-research-workbench.dev/attestation/release-authority/v1"
AUTHORITY_WORKFLOW = ".github/workflows/release-authority.yml"
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
PositiveId = Annotated[int, Field(gt=0)]


class ReleaseAuthorityError(ValueError):
    """Missing, unverifiable or mismatched authority blocks formal release."""


class ReleaseAuthority(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    schema_version: Literal["1.0.0"]
    repository: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    source_commit: Commit
    source_ref: Literal["refs/heads/main"]
    release_tag: Annotated[str, StringConstraints(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")]
    release_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    candidate_run_id: PositiveId
    candidate_artifact_id: PositiveId
    candidate_artifact_name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]+$")]
    candidate_artifact_digest: Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
    qualification_release_id: PositiveId
    qualification_asset_id: PositiveId
    qualification_asset_name: Annotated[str, StringConstraints(pattern=r"^arw-qualified-candidate-v[0-9]+\.[0-9]+\.[0-9]+\.tar\.gz$")]
    qualification_asset_digest: Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
    bundle_manifest_sha256: Sha256
    wheel_sha256: Sha256
    sdist_sha256: Sha256
    sbom_sha256: Sha256
    source_manifest_sha256: Sha256
    intended_use: Literal["noncommercial-academic-research"]
    distribution_class: Literal["public", "private"]
    # No commercial grants have been qualified. Their absence is not a waiver.
    permission_basis: Literal["pinned-existing-component-licenses"]
    actor: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]+$")]
    actor_id: PositiveId
    authority_run_id: PositiveId
    # A rerun is not a new accountable owner workflow_dispatch declaration.
    authority_run_attempt: Annotated[int, Field(ge=1, le=1)]


def release_authority_schema_document() -> dict:
    document = ReleaseAuthority.model_json_schema(mode="validation")
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = "https://academic-research-workbench.local/schemas/v1/release-authority.schema.json"
    document["title"] = "ARW Independent Release Authority"
    return document


def validate_run_identity(run: dict, repository: str, commit: str, workflow: str) -> None:
    if (run.get("repository", {}).get("full_name") != repository
            or run.get("head_repository", {}).get("full_name") != repository
            or run.get("head_sha") != commit or run.get("head_branch") != "main"
            or run.get("path") != workflow):
        raise ReleaseAuthorityError("GitHub run repository, main source or workflow mismatch")


def validate_candidate_run(run: dict, repository: str, commit: str, run_id: int) -> None:
    validate_run_identity(run, repository, commit, ".github/workflows/ci.yml")
    if (run.get("id") != run_id or run.get("event") != "push"
            or run.get("status") != "completed" or run.get("conclusion") != "success"):
        raise ReleaseAuthorityError("candidate must be a successful main push CI run")


def validate_dispatch(run: dict, repository: str, commit: str) -> None:
    validate_run_identity(run, repository, commit, AUTHORITY_WORKFLOW)
    actor = run.get("actor", {})
    triggering_actor = run.get("triggering_actor", {})
    if (run.get("event") != "workflow_dispatch" or run.get("run_attempt") != 1
            or actor.get("login") != repository.split("/", 1)[0]
            or type(actor.get("id")) is not int or actor["id"] <= 0
            or triggering_actor.get("login") != actor.get("login")
            or triggering_actor.get("id") != actor.get("id")):
        raise ReleaseAuthorityError("authority requires an original authenticated owner dispatch")


def verify_signature(subject: Path, repository: str, commit: str) -> list:
    workflow = f"{repository}/{AUTHORITY_WORKFLOW}"
    try:
        result = subprocess.run(
            ["gh", "attestation", "verify", str(subject), "--repo", repository,
             "--signer-workflow", workflow, "--source-ref", "refs/heads/main",
             "--source-digest", commit, "--signer-digest", commit,
             "--cert-identity", f"https://github.com/{workflow}@refs/heads/main",
             "--deny-self-hosted-runners", "--predicate-type", PREDICATE_TYPE,
             "--format", "json"],
            check=True, capture_output=True, text=True,
        )
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or not rows:
            raise ValueError("no verified attestations")
        return rows
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise ReleaseAuthorityError(f"independent authority signature verification failed: {error}") from error


def validate_verified_authority(rows: list, expected: dict, authority_run: dict) -> ReleaseAuthority:
    for row in rows:
        try:
            statement = row["verificationResult"]["statement"]
            if statement["predicateType"] != PREDICATE_TYPE:
                continue
            authority = ReleaseAuthority.model_validate(statement["predicate"])
            values = authority.model_dump()
            if authority.release_tag != f"v{authority.release_version}":
                continue
            if any(values[key] != value for key, value in expected.items()):
                continue
            if not any(subject["digest"].get("sha256") == authority.bundle_manifest_sha256
                       for subject in statement["subject"]):
                continue
            validate_dispatch(authority_run, authority.repository, authority.source_commit)
            if (authority_run.get("id") != authority.authority_run_id
                    or authority_run.get("run_attempt") != authority.authority_run_attempt
                    or authority_run.get("status") != "completed"
                    or authority_run.get("conclusion") != "success"
                    or authority_run["actor"]["login"] != authority.actor
                    or authority_run["actor"]["id"] != authority.actor_id):
                continue
            return authority
        except (KeyError, TypeError, AttributeError, ValidationError, ReleaseAuthorityError):
            continue
    raise ReleaseAuthorityError("no independently verified authority matches this exact release and candidate")

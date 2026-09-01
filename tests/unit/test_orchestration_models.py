from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from arw.kernel.core.canonical import canonical_json_bytes
from arw.orchestration_models import (
    AttemptDescriptor,
    GateDecision,
    HookObservation,
    HostQualification,
    HumanAuthority,
    HumanDecisionRecord,
    ImmutableAssignment,
    Phase4EvaluationVerdict,
    ProposalValidationError,
    RoleCatalog,
    RoleDefinition,
    WorkerProposal,
    locked_role_catalog,
    validate_worker_proposal_bytes,
)


RUN_ID = "run-00000000-0000-4000-8000-000000000401"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def _assignment_payload() -> dict[str, object]:
    return {
        "schema_version": "arw.assignment.v1",
        "protocol_version": "1.0.0",
        "assignment_id": "assignment.review-001",
        "supersedes_assignment_id": None,
        "run_id": RUN_ID,
        "stage_id": "formal-review",
        "task_id": "review-task-001",
        "role_id": "methodology_reviewer",
        "worker_identity_id": "worker.methodology-001",
        "execution_mode": "assignment_injected_subagent",
        "execution_provenance": "assignment_injected_subagent",
        "independence_eligible": True,
        "base_revision": 3,
        "input_sha256": [HASH_A],
        "capability_ids": ["files.read"],
        "allowed_read_root_ids": ["research-root"],
        "scratch_path_template": "attempts/{attempt_id}/scratch",
        "result_path_template": "attempts/{attempt_id}/result",
        "output_policy": {
            "schema_id": "arw.worker-proposal.v1",
            "schema_sha256": HASH_B,
            "max_bytes": 4096,
            "max_artifacts": 1,
        },
        "policy_sha256": HASH_C,
        "context_manifest_sha256": HASH_D,
        "blind_review": {
            "required": True,
            "subject_sha256": HASH_E,
            "rubric_sha256": HASH_F,
            "forbidden_peer_role_ids": [
                "domain_reviewer",
                "perspective_reviewer",
                "devils_advocate_reviewer",
            ],
        },
        "deadline_at": "2026-07-15T12:00:00Z",
        "completion_contract": {
            "requires_completed_proposal": True,
            "required_artifact_kinds": ["review-report"],
            "requires_human_gate": False,
        },
        "acceptance_key": {
            "topological_layer": 1,
            "task_ordinal": 0,
            "assignment_id": "assignment.review-001",
        },
    }


def _attempt_payload() -> dict[str, object]:
    return {
        "schema_version": "arw.attempt-descriptor.v1",
        "assignment_id": "assignment.review-001",
        "attempt_id": "attempt.review-001",
        "attempt_number": 1,
        "proposal_nonce": "nonce.review-001",
        "status": "active",
        "retry_reason": None,
        "retry_eligible": False,
        "continuation_count": 0,
        "host_agent_id": "host-agent-001",
        "cancellation_deadline_at": None,
    }


def _proposal_payload() -> dict[str, object]:
    return {
        "schema_version": "arw.worker-proposal.v1",
        "protocol_version": "1.0.0",
        "run_id": RUN_ID,
        "assignment_id": "assignment.review-001",
        "attempt_id": "attempt.review-001",
        "role_id": "methodology_reviewer",
        "worker_identity_id": "worker.methodology-001",
        "host_agent_id": "host-agent-001",
        "execution_mode": "assignment_injected_subagent",
        "execution_provenance": "assignment_injected_subagent",
        "independence_eligible": True,
        "assignment_sha256": HASH_A,
        "context_manifest_sha256": HASH_D,
        "policy_sha256": HASH_C,
        "base_revision": 3,
        "input_sha256": [HASH_A],
        "proposal_nonce": "nonce.review-001",
        "status": "completed",
        "result_provenance_mode": "executed",
        "requested_next_action": "accept",
        "artifacts": [
            {
                "relative_path": "report.json",
                "sha256": HASH_B,
                "media_type": "application/json",
                "schema_id": "arw.review-report.v1",
                "byte_count": 128,
            }
        ],
        "evidence_sha256": [HASH_E],
        "summary": "Review completed with a bounded report artifact.",
        "unresolved": [],
    }


def test_locked_role_catalog_has_required_roles_and_rejects_deferred_executors() -> None:
    catalog = locked_role_catalog()
    role_ids = {role.role_id for role in catalog.roles}
    assert {
        "research_architect",
        "methodology_reviewer",
        "domain_reviewer",
        "perspective_reviewer",
        "devils_advocate_reviewer",
        "editorial_synthesizer",
        "experiment_designer",
    } <= role_ids
    designer = next(role for role in catalog.roles if role.role_id == "experiment_designer")
    assert designer.execution_capability == "proposal_only"
    assert "controlled_execution" not in designer.capability_ids

    invalid = catalog.model_dump(mode="json")
    invalid["roles"].append(
        {
            **invalid["roles"][0],
            "role_id": "code_runner",
            "independence_eligible": False,
        }
    )
    with pytest.raises(ValidationError, match="code_runner|deferred"):
        RoleCatalog.model_validate(invalid)

    role = RoleDefinition.model_validate(catalog.roles[0].model_dump(mode="json"))
    assert isinstance(role.capability_ids, tuple)
    with pytest.raises(ValidationError):
        RoleDefinition.model_validate({**role.model_dump(mode="json"), "unknown": True})


def test_assignment_is_frozen_and_content_changes_require_explicit_supersession() -> None:
    assignment = ImmutableAssignment.model_validate(_assignment_payload())
    assert isinstance(assignment.input_sha256, tuple)
    assert isinstance(assignment.capability_ids, tuple)
    assert assignment.acceptance_key.assignment_id == assignment.assignment_id
    with pytest.raises(ValidationError):
        ImmutableAssignment.model_validate({**_assignment_payload(), "unknown": True})
    with pytest.raises(ValidationError):
        ImmutableAssignment.model_validate(
            {
                **_assignment_payload(),
                "execution_mode": "degraded_inline",
                "independence_eligible": True,
            }
        )
    with pytest.raises(ValidationError):
        ImmutableAssignment.model_validate(
            {
                **_assignment_payload(),
                "acceptance_key": {
                    **_assignment_payload()["acceptance_key"],
                    "assignment_id": "assignment.other-001",
                },
            }
        )

    successor = ImmutableAssignment.model_validate(
        {
            **_assignment_payload(),
            "assignment_id": "assignment.review-002",
            "supersedes_assignment_id": assignment.assignment_id,
            "policy_sha256": "1" * 64,
            "acceptance_key": {
                "topological_layer": 1,
                "task_ordinal": 0,
                "assignment_id": "assignment.review-002",
            },
        }
    )
    assert successor.validate_supersedes(assignment) is None
    with pytest.raises(ValueError, match="supersed"):
        assignment.validate_supersedes(assignment)


def test_execution_modes_are_distinct_and_provenance_bound() -> None:
    native_profile = ImmutableAssignment.model_validate(
        {
            **_assignment_payload(),
            "execution_mode": "native_profile",
            "execution_provenance": "native_profile",
        }
    )
    assert native_profile.execution_mode == "native_profile"

    with pytest.raises(ValidationError, match="native_profile"):
        ImmutableAssignment.model_validate(
            {
                **_assignment_payload(),
                "execution_mode": "native_profile",
                "execution_provenance": "assignment_injected_subagent",
            }
        )


def test_worker_proposal_rejects_noncanonical_bytes_and_wrong_assignment_echoes() -> None:
    assignment = ImmutableAssignment.model_validate(_assignment_payload())
    attempt = AttemptDescriptor.model_validate(_attempt_payload())
    payload = _proposal_payload()
    payload["assignment_sha256"] = assignment.canonical_sha256()
    proposal = WorkerProposal.model_validate(payload)
    assert isinstance(proposal.artifacts, tuple)
    raw = canonical_json_bytes(proposal.model_dump(mode="json"))
    validated, digest = validate_worker_proposal_bytes(
        raw, assignment=assignment, attempt=attempt
    )
    assert validated == proposal
    assert len(digest) == 64

    pretty = (json.dumps(proposal.model_dump(mode="json"), indent=2) + "\n").encode("utf-8")
    with pytest.raises(ProposalValidationError, match="canonical"):
        validate_worker_proposal_bytes(pretty, assignment=assignment, attempt=attempt)

    wrong_echo = {**proposal.model_dump(mode="json"), "assignment_id": "assignment.other-001"}
    with pytest.raises(ProposalValidationError, match="assignment_id"):
        validate_worker_proposal_bytes(
            canonical_json_bytes(wrong_echo), assignment=assignment, attempt=attempt
        )
    with pytest.raises(ValidationError):
        WorkerProposal.model_validate({**_proposal_payload(), "unexpected": True})


def test_gate_human_hook_and_host_contracts_are_strict_and_append_only() -> None:
    gate = GateDecision.model_validate(
        {
            "schema_version": "arw.gate-decision.v1",
            "gate_id": "gate.formal-review-001",
            "subject_sha256": HASH_A,
            "evidence_sha256": [HASH_B],
            "verdict": "BLOCKED",
            "rationale": "A required independent report is still absent.",
            "fresh_until": "2026-07-16T00:00:00Z",
            "required": True,
            "human_decision": None,
        }
    )
    assert gate.verdict == "BLOCKED"
    authority = HumanAuthority.model_validate(
        {
            "schema_version": "arw.human-authority.v1",
            "authority_id": "authority.review-001",
            "authenticated_actor_id": "operator.user",
            "accountable_role": "operator",
            "validated_by_actor_id": "parent.coordinator",
            "allowed_decision_kinds": ["waiver"],
            "allowed_gate_ids": [gate.gate_id],
            "allowed_scopes": ["gate.formal-review-001"],
            "authenticated_at": "2026-07-15T00:00:00Z",
            "expires_at": "2026-07-16T00:00:00Z",
            "evidence_sha256": [HASH_D],
        }
    )
    decision = HumanDecisionRecord.model_validate(
        {
            "schema_version": "arw.human-decision.v1",
            "decision_id": "decision.review-001",
            "decision_kind": "waiver",
            "gate_id": gate.gate_id,
            "subject_sha256": HASH_A,
            "evidence_sha256": [HASH_B],
            "applicable_transition": "continue-review",
            "accountable_actor_id": "operator.user",
            "accountable_role": "operator",
            "scope": "gate.formal-review-001",
            "rationale": "The named blocker may be released only for the next transition.",
            "prior_verdict_sha256": HASH_C,
            "authority_sha256": authority.authority_sha256,
            "supersedes_decision_id": None,
        }
    )
    assert decision.verdict_rewrite is False
    with pytest.raises(ValidationError, match="scope|blanket"):
        HumanDecisionRecord.model_validate({**decision.model_dump(mode="json"), "scope": "*"})

    observation = HookObservation.model_validate(
        {
            "schema_version": "arw.hook-observation.v1",
            "hook_name": "SubagentStop",
            "hook_definition_sha256": HASH_A,
            "target_id": "attempt.review-001",
            "status": "trusted_enabled",
            "observation_sha256": HASH_B,
            "redacted_error_code": None,
            "idempotency_key": "hook-stop-attempt.review-001",
            "continuation_requested": True,
            "continuation_count": 1,
        }
    )
    assert observation.continuation_count == 1
    with pytest.raises(ValidationError):
        HookObservation.model_validate({**observation.model_dump(mode="json"), "gate_verdict": "PASS"})

    host = HostQualification.model_validate(
        {
            "schema_version": "arw.host-qualification.v1",
            "qualification_id": "qualification.codex-001",
            "codex_version": "0.144.1",
            "stage_sha256": HASH_A,
            "adapter_sha256": HASH_B,
            "plugin_sha256": HASH_C,
            "execution_mode": "assignment_injected_subagent",
            "status": "PASS",
            "worker_identity_id": "worker.methodology-001",
            "host_agent_id": "host-agent-001",
            "evidence_sha256": [HASH_D],
        }
    )
    assert isinstance(host.evidence_sha256, tuple)
    with pytest.raises(ValidationError):
        HostQualification.model_validate({**host.model_dump(mode="json"), "stage_sha256": "bad"})

    verdict = Phase4EvaluationVerdict.model_validate(
        {
            "schema_version": "arw.phase4-evaluation-verdict.v1",
            "corpus_version": "phase4-corpus-v1",
            "case_id": "P4-DEV-001",
            "manifest_sha256": HASH_A,
            "authority_normalized_replay_sha256": HASH_B,
            "terminal_status": "BLOCKED",
            "execution_mode": "blocked",
            "evidence_sha256": [HASH_C],
            "sealed_parent_only": False,
        }
    )
    assert canonical_json_bytes(verdict.model_dump(mode="json")).endswith(b"\n")


def test_phase4_events_are_parent_authored_and_preserve_source_provenance() -> None:
    from arw.models import CanonicalEvent

    assignment = ImmutableAssignment.model_validate(_assignment_payload())
    payload = {
        "assignment": assignment.model_dump(mode="json"),
        "assignment_sha256": assignment.canonical_sha256(),
    }
    event = CanonicalEvent.model_validate(
        {
            "schema_version": "1.0.0",
            "event_type": "assignment.prepared",
            "event_id": "evt-00000000-0000-4000-8000-000000000402",
            "command_id": "cmd-00000000-0000-4000-8000-000000000402",
            "run_id": RUN_ID,
            "sequence": 1,
            "occurred_at": "2026-07-15T00:00:00Z",
            "expected_revision": 0,
            "resulting_revision": 1,
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "prev_event_sha256": "0" * 64,
            "payload": payload,
            "event_sha256": "1" * 64,
        }
    )
    assert event.payload.assignment.assignment_id == assignment.assignment_id
    assert event.payload.assignment.worker_identity_id == "worker.methodology-001"

    event_schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/v1/event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(event_schema).validate(event.model_dump(mode="json"))

    with pytest.raises(ValidationError, match="parent_control_plane"):
        CanonicalEvent.model_validate(
            {
                **event.model_dump(mode="json"),
                "event_id": "evt-00000000-0000-4000-8000-000000000403",
                "command_id": "cmd-00000000-0000-4000-8000-000000000403",
                "actor_id": "worker.agent",
                "actor_role": "worker",
            }
        )


def test_phase4_event_union_covers_lifecycle_evidence_and_human_authority() -> None:
    from arw.models import EVENT_PAYLOAD_TYPES, PHASE4_EVENT_TYPES

    expected = {
        "execution.mode_selected",
        "assignment.prepared",
        "assignment.superseded",
        "attempt.prepared",
        "attempt.lifecycle",
        "proposal.accepted",
        "proposal.rejected",
        "review.report_accepted",
        "review.synthesis_accepted",
        "hook.observed",
        "gate.evaluated",
        "human_decision.recorded",
    }
    assert expected <= PHASE4_EVENT_TYPES
    assert expected <= set(EVENT_PAYLOAD_TYPES)

"""Bounded direction composition; original readers retain their proof scopes."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.accepted_refs import ResolutionContext, RunPrefix, resolve_ref
from arw.kernel.ledger.research_records import publish_once
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.policy.core_integrity import installed_core_preflight
from arw.kernel.state.models import ArtifactAcceptanceRequest
from arw.kernel.state.research_direction import (
    DirectionBinding,
    DirectionCase,
    DirectionPackage,
    LiteratureIntake,
    Operationalization,
)
from arw.research_startup import _validate_run, load_plan, project_root

MAX_PACKAGE = 524288


class DirectionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def read_document(path: Path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not stat.S_ISREG(
        path.stat().st_mode
    ):
        raise DirectionError(
            "direction_input_unsafe", "direction input must be a direct regular file"
        )
    with path.open("rb") as stream:
        raw = stream.read(MAX_PACKAGE + 1)
    if len(raw) > MAX_PACKAGE:
        raise DirectionError(
            "direction_input_too_large", "direction input exceeds 512 KiB"
        )
    value = strict_json_loads(raw)
    if not isinstance(value, dict):
        raise DirectionError(
            "direction_input_invalid", "direction input must be an object"
        )
    return value


def package_digest(value):
    return sha256_hex(canonical_json_bytes({**value, "package_sha256": "0" * 64}))


def seal_package(value):
    value = {**value, "package_sha256": "0" * 64}
    package = DirectionPackage.model_validate_json(canonical_json_bytes(value))
    value = package.model_dump(mode="json")
    value["package_sha256"] = package_digest(value)
    return DirectionPackage.model_validate_json(canonical_json_bytes(value))


# Only bundled fixed validators execute. Package contents are stdin JSON data;
# packages cannot supply a module name, executable, command or search path.
ARS_CHECK = """import json,sys
sys.path.insert(0,sys.argv[1])
from research_workflow_profile import validate_profile,effective_stage_map
from inquiry_branch_ledger import replay_ledger
value=json.load(sys.stdin)
for profile in [value["profile"],*value["profile_history"]]:validate_profile(profile)
result={"stage_map":effective_stage_map(value["profile"]),"branch_replay":None}
if value["ledger"] is not None:
 result["branch_replay"]=replay_ledger(value["ledger"],[value["profile"],*value["profile_history"]],expected_project_ref=value["project_ref"],require_materialized=False)
json.dump(result,sys.stdout,ensure_ascii=False)
"""


def ars_check(profile, ledger=None, project_ref=None, *, profile_history=()):
    installed_core_preflight()
    root = (
        Path(os.environ["ARW_PLUGIN_ROOT"]).absolute()
        if os.environ.get("ARW_PLUGIN_ROOT")
        else Path(__file__).resolve().parents[2]
    )
    tools = root / "skills/academic-research-suite/ars/scripts"
    for name in (
        "research_workflow_profile.py",
        "inquiry_branch_ledger.py",
        "file_lock.py",
    ):
        path = tools / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise DirectionError(
                "ars_contracts_unavailable",
                "bundled original direction validators are missing or unsafe",
            )
    if ledger is not None and (
        not isinstance(ledger.get("events"), list) or len(ledger["events"]) > 256
    ):
        raise DirectionError(
            "direction_branch_limit",
            "direction branch snapshot exceeds its event bound",
        )
    process = subprocess.run(
        [sys.executable, "-I", "-c", ARS_CHECK, str(tools)],
        input=canonical_json_bytes(
            {
                "profile": profile,
                "ledger": ledger,
                "project_ref": project_ref,
                "profile_history": list(profile_history),
            }
        ),
        capture_output=True,
        timeout=15,
        check=False,
        env={"PATH": os.defpath, "PYTHONNOUSERSITE": "1"},
        cwd=tools,
    )
    if process.returncode or len(process.stdout) > MAX_PACKAGE:
        raise DirectionError(
            "ars_direction_validation_failed",
            "original ARS profile/branch validator rejected the snapshot",
        )
    result = strict_json_loads(process.stdout)
    if not isinstance(result, dict) or set(result) != {"stage_map", "branch_replay"}:
        raise DirectionError(
            "ars_direction_validation_failed", "original validator output is incomplete"
        )
    return result


def load_package(path: Path):
    value = read_document(path)
    package = DirectionPackage.model_validate_json(canonical_json_bytes(value))
    if package.package_sha256 != package_digest(package.model_dump(mode="json")):
        raise DirectionError(
            "direction_digest_mismatch", "direction package digest differs"
        )
    reject_secret_shapes(canonical_json_bytes(value))
    return package


def inspect_package(path: Path):
    package = load_package(path)
    original = ars_check(package.profile, profile_history=package.profile_history)
    return {
        "schema_version": "arw.direction-inspection.v1",
        "status": "validated_data",
        "package_id": package.package_id,
        "package_version": package.package_version,
        "package_sha256": package.package_sha256,
        "scope": package.scope,
        "stage_map": original["stage_map"],
        "unknowns": package.unknowns,
        "hypothesis_state": "candidate_not_author_adopted",
        "execution_permission": "not_granted",
        "scientific_status": "not_evaluated",
    }


def _context(root):
    installed_core_preflight()
    root = project_root(root)
    plan = load_plan(root)
    run, manifest, replay = _validate_run(root, plan)
    return (
        root,
        plan,
        run,
        manifest,
        replay,
        ResolutionContext(
            project_id=plan.project_id,
            project_root=root,
            run_roots=(run,),
            run_prefixes=(
                RunPrefix(
                    replay.run_id,
                    replay.revision,
                    replay.last_event_sha256,
                    sha256_hex(manifest),
                ),
            ),
        ),
    )


def bind(
    root: Path,
    package_path: Path,
    *,
    ars_project_ref=None,
    branch_path=None,
    cases=None,
):
    root, plan, _run, manifest, replay, _ = _context(root)
    alias = ars_project_ref or plan.ars_project_ref
    if alias != plan.ars_project_ref:
        raise DirectionError(
            "direction_project_mismatch",
            "ARS project reference differs from the manifest-bound startup alias",
        )
    package = load_package(package_path)
    ledger = None if branch_path is None else read_document(branch_path)
    ars_check(package.profile, ledger, alias, profile_history=package.profile_history)
    cases = [
        DirectionCase.model_validate_json(canonical_json_bytes(c))
        for c in (cases or [])
    ]
    known = {h.hypothesis_id for h in package.hypotheses}
    for case in cases:
        if case.hypothesis_id not in known:
            raise DirectionError(
                "direction_hypothesis_missing",
                "case does not name a package hypothesis",
            )
        refs = [
            case.definition_ref,
            case.costs_ref,
            case.attempts_ref,
            *(e.ref for e in case.evidence),
        ]
        if any(ref is not None and ref.project_id != plan.project_id for ref in refs):
            raise DirectionError(
                "direction_project_mismatch",
                "case carries another project's accepted reference",
            )
    branch_raw = None if ledger is None else canonical_json_bytes(ledger)
    branch_sha = None if branch_raw is None else sha256_hex(branch_raw)
    binding = DirectionBinding(
        project_id=plan.project_id,
        ars_project_ref=alias,
        run_id=replay.run_id,
        run_manifest_sha256=sha256_hex(manifest),
        initial_event_sha256=replay.events[0].event_sha256,
        package_sha256=package.package_sha256,
        package_snapshot=f".arw/research/directions/packages/{package.package_sha256}.json",
        branch_sha256=branch_sha,
        branch_snapshot=None
        if branch_sha is None
        else f".arw/research/directions/branches/{branch_sha}.json",
        cases=cases,
    )
    raw = canonical_json_bytes(binding.model_dump(mode="json"))
    reject_secret_shapes(raw)
    relative = f".arw/research/directions/bindings/{sha256_hex(raw)}.json"
    publish_once(
        root,
        binding.package_snapshot,
        canonical_json_bytes(package.model_dump(mode="json")),
    )
    if branch_raw is not None:
        publish_once(root, binding.branch_snapshot, branch_raw)
    publish_once(root, relative, raw)
    return {
        "status": "candidate_binding_retained",
        "binding_path": relative,
        "binding_sha256": sha256_hex(raw),
        "run_id": replay.run_id,
        "project_id": plan.project_id,
        "record_admission": "not_accepted",
        "scientific_status": "not_evaluated",
    }


def check(
    root: Path, binding_relative: str, *, current_package=None, current_branch=None
):
    root, plan, run, manifest, replay, context = _context(root)
    binding = DirectionBinding.model_validate_json(
        read_retained_bytes(root, binding_relative, max_bytes=MAX_PACKAGE)
    )
    if (
        binding.project_id,
        binding.ars_project_ref,
        binding.run_id,
        binding.run_manifest_sha256,
        binding.initial_event_sha256,
    ) != (
        plan.project_id,
        plan.ars_project_ref,
        replay.run_id,
        sha256_hex(manifest),
        replay.events[0].event_sha256,
    ):
        raise DirectionError(
            "direction_project_mismatch",
            "binding differs from the actual project/run history",
        )
    package = load_package(root / binding.package_snapshot)
    if package.package_sha256 != binding.package_sha256:
        raise DirectionError(
            "direction_digest_mismatch",
            "retained package differs from the bound digest",
        )
    ledger = (
        None
        if binding.branch_snapshot is None
        else strict_json_loads(
            read_retained_bytes(root, binding.branch_snapshot, max_bytes=MAX_PACKAGE)
        )
    )
    if (
        ledger is not None
        and sha256_hex(canonical_json_bytes(ledger)) != binding.branch_sha256
    ):
        raise DirectionError(
            "direction_digest_mismatch", "retained branch snapshot changed"
        )
    original = ars_check(
        package.profile,
        ledger,
        plan.ars_project_ref,
        profile_history=package.profile_history,
    )
    current = package if current_package is None else load_package(current_package)
    ars_check(current.profile, profile_history=current.profile_history)
    stale = current.package_sha256 != binding.package_sha256
    if current_branch is not None:
        changed = read_document(current_branch)
        ars_check(
            current.profile,
            changed,
            plan.ars_project_ref,
            profile_history=current.profile_history,
        )
        stale = (
            stale or sha256_hex(canonical_json_bytes(changed)) != binding.branch_sha256
        )
    rows = []
    branches = {
        b["branch_id"]: b for b in (original["branch_replay"] or {}).get("branches", [])
    }
    cases = {c.hypothesis_id: c for c in binding.cases}
    for hypothesis in package.hypotheses:
        case = cases.get(
            hypothesis.hypothesis_id,
            DirectionCase(hypothesis_id=hypothesis.hypothesis_id),
        )

        def row(
            name,
            status,
            reason=None,
            scope="mechanical_binding_only",
            hypothesis_id=hypothesis.hypothesis_id,
        ):
            rows.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "check": name,
                    "status": status,
                    "reason_code": reason,
                    "scope": scope,
                }
            )

        if stale:
            row("current_input_binding", "stale", "direction_snapshot_changed")
        branch = branches.get(hypothesis.branch_id)
        adopted = branch is not None and branch.get("provenance") in {
            "author_originated",
            "author_adopted",
        }
        row(
            "branch",
            "author_declared" if adopted else "candidate",
            None if adopted else "branch_not_author_adopted",
            "ARS_original_replay",
        )
        definition_resolution = (
            None
            if case.definition_ref is None
            else resolve_ref(case.definition_ref, context)
        )
        definition = (
            definition_resolution
            if definition_resolution is not None
            and definition_resolution.status == "resolved"
            else None
        )
        if definition is None:
            row(
                "operationalization",
                "missing"
                if definition_resolution is None
                else definition_resolution.status,
                "definition_not_accepted"
                if definition_resolution is None
                else definition_resolution.reason,
            )
        else:
            try:
                value = Operationalization.model_validate_json(definition.raw_bytes)
                if value.definition_id != hypothesis.definition_id:
                    raise ValueError("definition identity differs")
                row("operationalization", "resolved", scope="accepted_record_bytes")
                row(
                    "construct_source_support",
                    "resolved"
                    if value.sources
                    and all(_resolved(r, context) is not None for r in value.sources)
                    else "missing",
                    "construct_sources_need_human_review",
                    "record_bindings_not_construct_validity",
                )
            except ValueError:
                row("operationalization", "stale", "definition_binding_invalid")
        row(
            "construct_validity",
            "human_review_required",
            scope="not_automatically_evaluated",
        )
        _experiment_rows(case, hypothesis, run, replay, row, definition)
        roles = {c.role for c in case.conditions}
        if "baseline" in hypothesis.required_controls:
            row(
                "baseline",
                "declared" if "baseline" in roles else "missing",
                scope="declared_conditions_only",
            )
        if "sham" in hypothesis.required_controls:
            row(
                "sham",
                "declared" if "sham" in roles else "missing",
                scope="declared_conditions_only",
            )
        if "equal_budget" in hypothesis.required_controls:
            equal = (
                bool(case.conditions)
                and len(
                    {
                        (
                            c.model_label,
                            c.data_sha256,
                            c.evaluation_sha256,
                            c.token_budget,
                        )
                        for c in case.conditions
                    }
                )
                == 1
                and {"baseline", "intervention"} <= roles
            )
            row(
                "equal_budget_data_evaluation",
                "declared_equal" if equal else "missing_or_different",
                scope="declared_conditions_not_observed_usage",
            )
        if "held_out" in hypothesis.required_controls:
            held = (
                bool(case.conditions)
                and all(c.held_out_sha256 is not None for c in case.conditions)
                and len({c.held_out_sha256 for c in case.conditions}) == 1
            )
            row(
                "held_out",
                "declared" if held else "missing",
                scope="declared_conditions_only",
            )
        if "costs" in hypothesis.required_controls:
            costs = _resolved(case.costs_ref, context)
            value = _record_body(costs)
            known_costs = (
                type(value.get("actual_tokens")) is int
                and value["actual_tokens"] >= 0
                and _nonnegative_number(value.get("elapsed_seconds"))
                and _nonnegative_number(value.get("actual_cost"))
                and isinstance(value.get("currency"), str)
                and bool(value["currency"].strip())
            )
            row(
                "actual_costs",
                "recorded" if known_costs else "missing",
                "unknown_cost_is_not_zero",
                "accepted_observation_record_only",
            )
        if "all_attempts" in hypothesis.required_controls:
            attempts = _resolved(case.attempts_ref, context)
            value = _record_body(attempts)
            all_attempts = (
                isinstance(value, dict)
                and isinstance(value.get("attempts"), list)
                and 0 < len(value["attempts"]) <= 256
                and value.get("declared_complete") is True
            )
            row(
                "all_attempts",
                "declared_complete" if all_attempts else "missing",
                "best_attempt_only_is_insufficient",
                "accepted_inventory_declaration_only",
            )
        for evidence in case.evidence:
            evidence_resolution = resolve_ref(evidence.ref, context)
            row(
                "evidence_" + evidence.relation,
                evidence_resolution.status,
                evidence_resolution.reason,
                scope="accepted_bytes_not_semantic_support",
            )
        row(
            "narrative",
            "human_review_required" if case.narrative_candidate else "not_evaluated",
            "conclusion_scope_needs_author_review",
            "candidate_without_manuscript_occurrence",
        )
    return {
        "schema_version": "arw.direction-check.v1",
        "status": "mechanical_checks_complete",
        "project_id": plan.project_id,
        "package_sha256": package.package_sha256,
        "input_state": "stale" if stale else "retained_snapshot",
        "stage_map": original["stage_map"],
        "checks": rows,
        "coverage": {
            "hypotheses_checked": len(package.hypotheses),
            "package_hypotheses": len(package.hypotheses),
            "mechanical_checks": len(rows),
        },
        "human_review_required": True,
        "uncovered": [
            "construct_validity",
            "philosophical_interpretation",
            "causal_identification",
            "actual_cost_authentication",
            "scientific_support",
            "manuscript_occurrences",
        ],
    }


def claim_digest(hypothesis, definition_bytes):
    return sha256_hex(
        canonical_json_bytes(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "statement": hypothesis.statement,
                "scope": hypothesis.scope,
                "definition_sha256": sha256_hex(definition_bytes),
            }
        )
    )


def _record_body(resolution):
    if resolution is None:
        return {}
    try:
        value = strict_json_loads(resolution.raw_bytes)
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeError):
        return {}


def _nonnegative_number(value):
    if type(value) not in {int, float, str} or len(str(value)) > 64:
        return False
    try:
        number = Decimal(str(value))
        return number.is_finite() and number >= 0
    except InvalidOperation:
        return False


def _resolved(ref, context):
    if ref is None:
        return None
    resolution = resolve_ref(ref, context)
    return resolution if resolution.status == "resolved" else None


def _experiment_rows(case, hypothesis, run, replay, row, definition):
    from arw.kernel.artifacts.experiment_acceptance import (
        load_experiment_acceptance,
        load_experiment_contract,
        replay_experiment_acceptance,
    )
    from arw.kernel.artifacts.experiment_provenance import load_experiment_provenance

    if case.contract_sha256 is None:
        row("contract", "missing", "contract_not_bound")
    else:
        try:
            contract = load_experiment_contract(run, case.contract_sha256)
            frozen = any(
                e.event_type == "experiment.contract.accepted"
                and e.payload.contract_sha256 == case.contract_sha256
                for e in replay.events
            )
            if (
                contract.contract_version != case.contract_version
                or contract.claim_id != hypothesis.hypothesis_id
            ):
                raise ValueError("hypothesis or contract version differs")
            expected_claim = (
                None
                if definition is None
                else claim_digest(hypothesis, definition.raw_bytes)
            )
            row(
                "hypothesis_definition_contract",
                "resolved"
                if expected_claim == contract.claim_sha256
                else "stale_or_missing",
                "hypothesis_or_definition_binding_differs",
            )
            row(
                "contract",
                "frozen" if frozen else "candidate",
                None if frozen else "contract_not_frozen",
                "original_contract_version_and_ledger",
            )
        except (ValueError, OSError, RuntimeError):
            row("contract", "unresolved", "contract_binding_invalid")
    if case.result_sha256 is None:
        row("result", "not_evaluated", "result_not_supplied")
        return
    try:
        result = load_experiment_acceptance(run, case.result_sha256)
        contract = load_experiment_contract(run, result.contract_sha256)
        provenance = load_experiment_provenance(run, result.provenance_sha256)
        replayed = replay_experiment_acceptance(
            result, contract, provenance, run, journal_prefix=replay
        )
        if (
            result.contract_sha256 != case.contract_sha256
            or result.contract_version != case.contract_version
            or result.claim_id != hypothesis.hypothesis_id
        ):
            raise ValueError("result does not bind this hypothesis/contract version")
        row("result", replayed.overall_status, scope=replayed.scope)
        row(
            "predeclaration",
            replayed.predeclaration,
            scope="original_parent_ledger_order",
        )
    except (ValueError, OSError, RuntimeError):
        row("result", "unresolved", "original_experiment_replay_failed")


def prepare_intake(
    root: Path,
    package_path: Path,
    input_path: Path,
    *,
    citation_store=None,
    previous=None,
):
    from arw.kernel.policy.citations import ReferenceRecord, replay_check

    root, plan, run, _, replay, context = _context(root)
    package = load_package(package_path)
    ars_check(package.profile, profile_history=package.profile_history)
    intake = LiteratureIntake.model_validate_json(
        canonical_json_bytes(read_document(input_path))
    )
    if (
        intake.project_id != plan.project_id
        or intake.package_sha256 != package.package_sha256
    ):
        raise DirectionError(
            "direction_project_mismatch", "intake differs from the project or package"
        )
    sources = []
    for source in intake.sources:
        reference = ReferenceRecord.model_validate_json(
            canonical_json_bytes(source.reference)
        )
        bibliographic = []
        for receipt_sha in source.citation_receipts:
            try:
                receipt = replay_check(citation_store or root, reference, receipt_sha)
                bibliographic.append(
                    {
                        "receipt_sha256": receipt_sha,
                        "status": receipt.status,
                        "scope": "bibliographic_metadata_only",
                    }
                )
            except (ValueError, OSError, RuntimeError):
                bibliographic.append(
                    {
                        "receipt_sha256": receipt_sha,
                        "status": "unresolved",
                        "scope": "bibliographic_metadata_only",
                    }
                )
        resolution = _resolved(source.source_ref, context)
        if (
            source.source_ref is not None
            and source.source_ref.project_id != plan.project_id
        ):
            raise DirectionError(
                "direction_project_mismatch",
                "reading carries another project's source reference",
            )
        source_available = resolution is not None and (
            source.source_sha256 is None
            or sha256_hex(resolution.raw_bytes) == source.source_sha256
        )
        sources.append(
            {
                "source_id": source.source_id,
                "bibliographic": bibliographic or [{"status": "not_evaluated"}],
                "version_label": source.version_label,
                "carrier": source.carrier,
                "source_bytes": "retained_accepted_bytes"
                if source_available
                else "missing_or_unaccepted",
                "recorded_reader": source.reader,
                "reading_status": source.reading_status,
                "read_ranges": source.read_ranges,
                "reading_proof": "operator_declaration_not_independent_human_read_verification",
                "scientific_support": "human_review_required",
                "experiment_replay": "not_evaluated",
            }
        )
    impacts = []
    if previous is not None:
        older = LiteratureIntake.model_validate_json(
            canonical_json_bytes(read_document(previous))
        )
        if older.project_id != intake.project_id:
            raise DirectionError(
                "direction_project_mismatch",
                "previous intake belongs to another project",
            )
        for old in older.sources:
            for new in intake.sources:
                if old.reference.get("reference_id") == new.reference.get(
                    "reference_id"
                ) and (old.version_label, old.carrier, old.source_sha256) != (
                    new.version_label,
                    new.carrier,
                    new.source_sha256,
                ):
                    impacts.append(
                        {
                            "from_source": old.source_id,
                            "to_source": new.source_id,
                            "affected_records": old.affected_records,
                            "status": "review_required_not_false",
                            "scope": "declared_source_dependencies",
                        }
                    )
    return _prepare_artifact(
        run,
        replay,
        intake.model_dump(mode="json"),
        "literature-intake",
        {
            "schema_version": "arw.literature-intake-report.v1",
            "sources": sources,
            "upgrade_impacts": impacts,
            "record_admission": "candidate",
            "human_review_required": True,
            "coverage": {
                "source_records": len(sources),
                "declared_intake_sources": len(intake.sources),
            },
        },
    )


def prepare_definition(
    root: Path, path: Path, *, package_path=None, hypothesis_id=None
):
    _, _, run, _, replay, context = _context(root)
    definition = Operationalization.model_validate_json(
        canonical_json_bytes(read_document(path))
    )
    if any(r.project_id != context.project_id for r in definition.sources):
        raise DirectionError(
            "direction_project_mismatch", "definition source belongs to another project"
        )
    claim = None
    if package_path is not None:
        package = load_package(package_path)
        ars_check(package.profile, profile_history=package.profile_history)
        hypothesis = next(
            (h for h in package.hypotheses if h.hypothesis_id == hypothesis_id), None
        )
        if hypothesis is None or hypothesis.definition_id != definition.definition_id:
            raise DirectionError(
                "direction_definition_mismatch",
                "definition does not bind the selected hypothesis",
            )
        claim = claim_digest(
            hypothesis, canonical_json_bytes(definition.model_dump(mode="json"))
        )
    return _prepare_artifact(
        run,
        replay,
        definition.model_dump(mode="json"),
        "operationalization",
        {
            "sources": [
                {
                    "status": "resolved"
                    if _resolved(r, context) is not None
                    else "unresolved"
                }
                for r in definition.sources
            ],
            "claim_sha256": claim,
            "construct_validity": "human_review_required",
            "record_admission": "candidate",
            "field_mapping": {
                "assumptions": "inquiry_branch.assumptions",
                "evidence_sought": "inquiry_branch.evidence_sought",
                "rival_explanations": "profile.alternative_categories",
                "cannot_conclude": "boundary_condition_overlay",
            },
        },
    )


def _prepare_artifact(run, replay, document, kind, report):
    raw = canonical_json_bytes(document)
    reject_secret_shapes(raw)
    digest = sha256_hex(raw)
    prefix = f"research-inputs/{kind}/{digest}"
    relative = prefix + "/artifact.json"
    artifact_id = f"{kind}.{digest[:32]}"
    existing = next(
        (
            e
            for e in replay.events
            if e.event_type == "artifact.accepted"
            and e.payload.artifact_id == artifact_id
        ),
        None,
    )
    if existing is not None:
        if existing.payload.artifact_sha256 != digest:
            raise DirectionError(
                "direction_artifact_conflict",
                "accepted artifact ID binds other content",
            )
        return {
            **report,
            "status": "already_accepted",
            "record_admission": "accepted_record",
            "artifact_path": relative,
            "content_sha256": digest,
            "artifact_id": artifact_id,
            "accepting_event_id": existing.event_id,
            "next_command": None,
            "scientific_status": "not_evaluated",
        }
    operation = uuid.uuid5(uuid.UUID(replay.run_id.removeprefix("run-")), kind + digest)
    stable_uuid = uuid.UUID(bytes=operation.bytes, version=4)
    request_relative = prefix + f"/request-{replay.last_event_sha256}.json"
    timestamp = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    if (run / request_relative).exists():
        previous = ArtifactAcceptanceRequest.model_validate_json(
            read_retained_bytes(run, request_relative, max_bytes=65536)
        )
        timestamp = previous.occurred_at
    request = ArtifactAcceptanceRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": replay.run_id,
            "occurred_at": timestamp,
            "event_id": f"evt-{stable_uuid}",
            "command_id": f"cmd-{stable_uuid}",
            "actor_id": "parent.direction-intake",
            "actor_role": "parent_control_plane",
            "expected_revision": replay.revision,
            "artifact_id": artifact_id,
            "artifact_kind": "research-evidence",
            "media_type": "application/json",
            "content_path": relative,
            "content_sha256": digest,
            "base_revision": replay.revision,
            "consumed_sha256": [replay.last_event_sha256],
        }
    )
    # Separate requests at each prefix preserve stale attempts and the first
    # preparation timestamp. Repeating preparation never overwrites history.
    publish_once(run, relative, raw)
    publish_once(
        run, request_relative, canonical_json_bytes(request.model_dump(mode="json"))
    )
    return {
        **report,
        "status": "prepared_candidate",
        "artifact_path": relative,
        "request_path": request_relative,
        "content_sha256": digest,
        "artifact_id": artifact_id,
        "expected_revision": replay.revision,
        "next_command": [
            "arw",
            "artifact-accept",
            "--run-root",
            str(run),
            "--request",
            str(run / request_relative),
        ],
        "scientific_status": "not_evaluated",
    }

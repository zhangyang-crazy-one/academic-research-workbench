"""Explicit synthetic workflow demonstration; no models or network requests."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from arw.kernel.artifacts.experiment_acceptance import (
    evaluate_experiment_acceptance,
    freeze_experiment_contract,
    publish_experiment_acceptance,
)
from arw.kernel.artifacts.experiment_provenance import (
    ProvenanceAuthorityEnvelope,
    ingest_experiment_provenance,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.policy.citations import (
    ReferenceRecord,
    check_response,
    check_unavailable,
    publish_check,
)
from arw.kernel.state.accepted_ref import ParentArtifactRef
from arw.kernel.state.models import ArtifactAcceptanceRequest, RuntimeCommandRequest


def execute(project: Path, plugin: Path):
    """Retain every input and output in a new, explicitly chosen project."""
    project.mkdir(parents=True, exist_ok=False)
    observations = project / "observations"
    observations.mkdir()
    commands = []

    def command(*args):
        argv = [str(plugin / "bin/arw"), *map(str, args)]
        result = subprocess.run(
            argv, capture_output=True, check=False, env=os.environ.copy()
        )
        commands.append(argv)
        (observations / f"{len(commands):02d}.stdout.json").write_bytes(result.stdout)
        (observations / f"{len(commands):02d}.stderr.txt").write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(
                f"CLI failed at operation {len(commands)} with exit {result.returncode}"
            )
        return json.loads(result.stdout)

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(value))
        return path

    started = command(
        "research",
        "start",
        "--project-root",
        project,
        "--direction",
        "修正对世界的理解",
        "--ars-project-ref",
        "ars.offline-demonstration",
    )
    run = project / started["run_relative"]
    package = plugin / "examples/research-directions/computational-pilot/package.json"
    data = json.loads(package.read_bytes())
    project_id = started["project"]["project_id"]

    def request():
        replay = replay_run(run)
        return RuntimeCommandRequest(
            schema_version="1.0.0",
            run_id=replay.run_id,
            event_id=f"evt-{uuid.uuid4()}",
            command_id=f"cmd-{uuid.uuid4()}",
            expected_revision=replay.revision,
            occurred_at="2026-10-12T01:00:00Z",
            actor_id="parent.offline-demonstration",
            actor_role="parent_control_plane",
        )

    def ref_for(event):
        return ParentArtifactRef(
            project_id=project_id,
            run_id=started["run"]["run_id"],
            run_manifest_sha256=sha256_hex((run / "run-manifest.json").read_bytes()),
            artifact_id=event.payload.artifact_id,
            accepting_event_id=event.event_id,
            accepting_event_sha256=event.event_sha256,
            content_sha256=event.payload.artifact_sha256,
        ).model_dump(mode="json")

    def admit(path, artifact_id):
        req = ArtifactAcceptanceRequest(
            **request().model_dump(),
            artifact_id=artifact_id,
            artifact_kind="research-evidence",
            media_type="application/json",
            content_path=path.relative_to(run).as_posix(),
            content_sha256=sha256_hex(path.read_bytes()),
            base_revision=replay_run(run).revision,
            consumed_sha256=[],
        )
        command(
            "artifact-accept",
            "--run-root",
            run,
            "--request",
            write(
                observations / f"{artifact_id}.request.json",
                req.model_dump(mode="json"),
            ),
        )
        return ref_for(replay_run(run).events[-1])

    # Deliberately inconsistent synthetic carriers; these are not real papers.
    source_ref = admit(
        write(
            run / "inputs/synthetic-v1.json", {"synthetic": True, "sample_count": 40}
        ),
        "source.synthetic-v1",
    )
    reference = ReferenceRecord(
        reference_id="reference.synthetic",
        citation_key="Synthetic2026",
        title="Synthetic contextual revision",
        authors=("Synthetic Author",),
        year=2026,
        doi="10.9999/synthetic-example",
    )
    raw = canonical_json_bytes(
        {
            "message": {
                "items": [
                    {
                        "DOI": reference.doi,
                        "title": [reference.title],
                        "published": {"date-parts": [[2026]]},
                        "author": [{"family": "Synthetic Author"}],
                    }
                ]
            }
        }
    )
    receipts = []
    for response in [raw, canonical_json_bytes({"message": {"items": []}})]:
        checked = check_response(
            reference, "crossref", response, observed_at="2026-10-12T00:00:00Z"
        )
        publish_check(project, checked, response)
        receipts.append(checked.receipt_sha256)
    unavailable = check_unavailable(
        reference, "openalex", observed_at="2026-10-12T00:00:00Z", error_code="timeout"
    )
    publish_check(project, unavailable, b"")
    receipts.append(unavailable.receipt_sha256)
    reading = {
        "source_id": "reading.v1",
        "reference": reference.model_dump(mode="json"),
        "version_label": "v1",
        "carrier": "text",
        "source_sha256": source_ref["content_sha256"],
        "source_ref": source_ref,
        "citation_receipts": receipts,
        "reader": "tool",
        "reading_status": "partial",
        "read_ranges": ["synthetic abstract"],
        "note": "v1:40 synthetic cases.",
        "limitations": ["Synthetic fixture; no downloaded real paper."],
        "affected_records": ["note.v1", "matrix.old"],
    }
    intake = {
        "schema_version": "arw.literature-intake.v1",
        "project_id": project_id,
        "package_sha256": data["package_sha256"],
        "sources": [reading],
    }
    first = write(observations / "intake-v1.json", intake)
    prepared = command(
        "research",
        "direction",
        "intake",
        "--project-root",
        project,
        "--package",
        package,
        "--input",
        first,
    )
    command(*prepared["next_command"][1:])
    reading = {
        **reading,
        "source_id": "reading.v2",
        "version_label": "v2",
        "carrier": "pdf",
        "source_ref": None,
        "source_sha256": None,
        "note": "v2:100 synthetic cases. v1 evidence cannot be reused automatically.",
        "reading_status": "timed_out",
    }
    revised = write(observations / "intake-v2.json", {**intake, "sources": [reading]})
    upgrade = command(
        "research",
        "direction",
        "intake",
        "--project-root",
        project,
        "--package",
        package,
        "--input",
        revised,
        "--previous-intake",
        first,
    )
    command(*upgrade["next_command"][1:])
    abstract = write(
        observations / "intake-abstract.json",
        {
            **intake,
            "sources": [
                {
                    **reading,
                    "source_id": "reading.web",
                    "version_label": "web-abstract",
                    "carrier": "web_abstract",
                    "note": "Web fixture still reports40; do not combine with v2.",
                    "reading_status": "failed",
                }
            ],
        },
    )
    web = command(
        "research",
        "direction",
        "intake",
        "--project-root",
        project,
        "--package",
        package,
        "--input",
        abstract,
        "--previous-intake",
        first,
    )
    command(*web["next_command"][1:])

    definition = {
        "schema_version": "arw.operationalization.v1",
        "definition_id": "definition.local-boundary",
        "sources": [source_ref],
        "author_interpretation": "Candidate conceptual revision; not an asserted identity with human experience.",
        "rival_explanations": ["Extra instructions alone improve a score."],
        "local_definition": "Revise an answer following a counterexample.",
        "measured_object": "Recorded synthetic answers.",
        "metric_definition": "CSV mean score",
        "why_relevant": "Narrow behavioral proxy.",
        "alternative_measurements": ["Human explanatory consistency."],
        "confounders": ["Leakage", "Extra context"],
        "refuting_observations": ["Sham produces the same gain."],
        "cannot_conclude": ["Human understanding or philosophical correctness."],
        "assumptions": ["Scores are illustrative."],
        "evidence_sought": ["Held-out non-sham effect in a future authorized study."],
    }
    prepared = command(
        "research",
        "direction",
        "definition",
        "--project-root",
        project,
        "--input",
        write(observations / "definition.json", definition),
        "--package",
        package,
        "--hypothesis-id",
        "hypothesis.transfer",
    )
    command(*prepared["next_command"][1:])
    definition_ref = ref_for(replay_run(run).events[-1])

    # The author event is an explicit synthetic action in this demo, never produced by startup.
    sys.path.insert(0, str(plugin / "skills/academic-research-suite/ars/scripts"))
    from inquiry_branch_ledger import append_event, new_ledger

    ledger = new_ledger("ars.offline-demonstration", data["profile"])
    ledger = append_event(
        ledger,
        {
            "recorded_at": "2026-10-12T00:00:00Z",
            "actor": "author",
            "kind": "branch_created",
            "branch_id": "transfer",
            "payload": {
                "parent_id": None,
                "statement": "Synthetic computational proxy.",
                "assumptions": definition["assumptions"],
                "evidence_sought": definition["evidence_sought"],
                "reopen_conditions": [
                    {"condition_id": "condition.null", "statement": "Null/sham result."}
                ],
                "downstream_refs": [],
            },
        },
        [data["profile"]],
        expected_project_ref="ars.offline-demonstration",
    )
    branch_path = write(observations / "branches.json", ledger)
    contract = {
        "schema_version": "arw.experiment-contract.v1",
        "contract_id": "contract.synthetic",
        "contract_version": 1,
        "claim_id": "hypothesis.transfer",
        "claim_sha256": prepared["claim_sha256"],
        "declared_timing": "predeclared",
        "checks": [
            {
                "check_id": "check.mean",
                "kind": "numeric_reproduction",
                "reported_metric": "accuracy",
                "unit": "ratio",
                "operator": "mean@1",
                "data": {
                    "artifact_id": "artifact.scores",
                    "format": "csv",
                    "column": "score",
                    "row_id_column": "sample",
                },
                "tolerance": {"absolute": "0", "relative": "0"},
            }
        ],
    }
    contract, _, _ = freeze_experiment_contract(
        contract, run, RuntimeCommandService(run), request()
    )
    results = []
    # Passing and failing recorded attempts both remain retained; no selection of only the best.
    for attempt, value in [("pass", 0.75), ("fail", 0.5)]:
        csv = b"sample,score\ns1,0.5\ns2,0.75\ns3,1\n"
        (run / "results").mkdir(exist_ok=True)
        (run / f"results/{attempt}.csv").write_bytes(csv)
        metric = {"name": "accuracy", "value": value, "unit": "ratio"}
        metric["metric_sha256"] = sha256_hex(canonical_json_bytes(metric))
        provenance = {
            "schema_version": "arw.experiment-provenance.v1",
            "provenance_id": f"provenance.{attempt}",
            "run_id": started["run"]["run_id"],
            "experiment_id": "experiment.synthetic",
            "source_datasets": [
                {
                    "uri_or_path": "inputs/synthetic-v1.json",
                    "content_sha256": source_ref["content_sha256"],
                    "access_state": "publicly_verified",
                    "manifest_sha256": sha256_hex(
                        canonical_json_bytes({"synthetic": True})
                    ),
                }
            ],
            "model_identity": [
                {
                    "name": "recorded-fixture-no-model-call",
                    "revision": "synthetic-v1",
                    "source_sha256": sha256_hex(
                        canonical_json_bytes(
                            {
                                "name": "recorded-fixture-no-model-call",
                                "revision": "synthetic-v1",
                            }
                        )
                    ),
                }
            ],
            "configuration": [
                {
                    "name": "synthetic",
                    "canonical_sha256": sha256_hex(
                        canonical_json_bytes(
                            {"name": "synthetic", "content_type": "application/json"}
                        )
                    ),
                    "content_type": "application/json",
                }
            ],
            "metrics": [metric],
            "artifacts": [
                {
                    "artifact_id": "artifact.scores",
                    "media_type": "text/csv",
                    "content_sha256": sha256_hex(csv),
                    "manifest_sha256": sha256_hex(
                        canonical_json_bytes({"synthetic": True, "attempt": attempt})
                    ),
                    "content_path": f"results/{attempt}.csv",
                }
            ],
            "environment": [
                {
                    "key": "python.version",
                    "redacted_value_or_digest": sys.version.split()[0],
                    "tool_version": sys.version.split()[0],
                    "redacted": True,
                }
            ],
            "runner": {
                "identity": "runner.synthetic",
                "command_digest": sha256_hex(b"offline-walkthrough"),
                "host_digest": sha256_hex(b"synthetic-local"),
                "started_at": "2026-10-12T00:00:00Z",
                "finished_at": "2026-10-12T00:01:00Z",
            },
            "execution_claim": {"mode": "external_only", "status": "imported"},
            "qualification_receipts": [],
            "source_manifest_sha256": [source_ref["content_sha256"]],
            "created_at": "2026-10-12T00:01:00Z",
        }
        accepted = ingest_experiment_provenance(
            provenance,
            run,
            ProvenanceAuthorityEnvelope(
                runtime=RuntimeCommandService(run), request=request()
            ),
        )
        result = evaluate_experiment_acceptance(
            contract, accepted.provenance, run, journal_prefix=replay_run(run)
        )
        publish_experiment_acceptance(run, result)
        results.append(result)
    costs = admit(
        write(
            run / "inputs/costs.json",
            {
                "actual_tokens": 0,
                "elapsed_seconds": None,
                "actual_cost": 0,
                "currency": "USD",
                "scope": "No model calls; elapsed wall clock not measured.",
            },
        ),
        "costs.synthetic",
    )
    attempts = admit(
        write(
            run / "inputs/attempts.json",
            {
                "declared_complete": True,
                "attempts": [
                    {
                        "attempt_id": "pass",
                        "status": results[0].overall_status,
                        "result_sha256": results[0].result_sha256,
                    },
                    {
                        "attempt_id": "fail",
                        "status": results[1].overall_status,
                        "result_sha256": results[1].result_sha256,
                    },
                ],
            },
        ),
        "attempts.synthetic",
    )
    null = admit(
        write(
            run / "inputs/null.json",
            {
                "synthetic": True,
                "effect": 0,
                "meaning": "Null fixture; no measured model effect.",
            },
        ),
        "evidence.null",
    )
    cases = {
        "cases": [
            {
                "hypothesis_id": "hypothesis.transfer",
                "definition_ref": definition_ref,
                "contract_sha256": contract.contract_sha256,
                "contract_version": 1,
                "result_sha256": results[1].result_sha256,
                "costs_ref": costs,
                "attempts_ref": attempts,
                "conditions": [
                    {
                        "condition_id": f"condition.{role}",
                        "role": role,
                        "model_label": "recorded-fixture",
                        "data_sha256": sha256_hex(b"data"),
                        "evaluation_sha256": sha256_hex(b"eval"),
                        "token_budget": 0,
                        "held_out_sha256": sha256_hex(b"heldout"),
                    }
                    for role in ["baseline", "intervention", "sham"]
                ],
                "evidence": [
                    {"relation": relation, "ref": null}
                    for relation in ["opposes", "null_result", "failed"]
                ],
                "narrative_candidate": "The synthetic workflow preserves a failed check and null/opposing records. No empirical or philosophical claim.",
            }
        ]
    }
    binding = command(
        "research",
        "direction",
        "bind",
        "--project-root",
        project,
        "--package",
        package,
        "--branch-ledger",
        branch_path,
        "--cases",
        write(observations / "cases.json", cases),
    )
    checked = command(
        "research",
        "direction",
        "check",
        "--project-root",
        project,
        "--binding-path",
        binding["binding_path"],
    )
    matrix = admit(
        write(
            run / "inputs/literature-matrix.json",
            {
                "schema_version": "arw.synthetic-literature-matrix.v1",
                "synthetic": True,
                "versions": [
                    {"source_id": "reading.v1", "cases": 40},
                    {"source_id": "reading.v2", "cases": 100},
                    {"source_id": "reading.web", "cases": 40},
                ],
                "interpretation": "Different carriers and versions remain separate; upgrade needs human review.",
                "candidate_graph": checked,
                "scientific_support": "not_evaluated",
            },
        ),
        "matrix.synthetic",
    )
    resumed = command("research", "resume", "--project-root", project)
    summary = {
        "schema_version": "arw.offline-direction-walkthrough.v1",
        "synthetic": True,
        "model_calls": 0,
        "command_count": len(commands),
        "prepared_adapter_requests": 4,
        "fixture_field_counts": {
            "intake_envelope": len(intake),
            "reading_record": len(reading),
            "operationalization": len(definition),
            "scope": "fixture schema fields; not measured human keystrokes",
        },
        "matrix_ref": matrix,
        "commands": commands,
        "project_id": project_id,
        "run_id": started["run"]["run_id"],
        "revision": resumed["run"]["revision"],
        "workflow_stage": resumed["run"]["workflow_stage"],
        "result_statuses": [r.overall_status for r in results],
        "checks": checked,
        "version_upgrade": upgrade["upgrade_impacts"],
        "scientific_status": "not_evaluated",
        "costs": {
            "model_calls": 0,
            "elapsed_seconds": "not_measured",
            "research_tokens": "not_measured",
        },
        "comparison_baseline": {
            "startup_commands": 3,
            "source": "issue115 owner observation; not a controlled latency/token comparison",
        },
    }
    write(observations / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--plugin-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    summary = execute(args.project_root.absolute(), args.plugin_root.absolute())
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in {"commands", "checks"}},
            ensure_ascii=False,
            indent=2,
        )
    )

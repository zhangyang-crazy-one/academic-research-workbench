"""Parent-orchestrated research figure compilation and historical inspection."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from pydantic import TypeAdapter

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import locked_replay, replay_run
from arw.kernel.ledger.research_records import (
    BodyUnavailable,
    ResearchRecordError,
    commit_artifact_pipeline,
    publish_once,
    unlink_retained,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import StableRuntimeId
from arw.kernel.state.research_artifact import (
    OutputDigest,
    ResearchArtifactIR,
    ResearchArtifactReceipt,
)

from .builder import SQLiteArtifactIRBuilder
from .renderer import SvgRenderer
from .validation import EvidenceValidator, IRValidationFault, accepted_content


class ResearchArtifactService:
    def __init__(self, *, renderer=None, validator=None, boundary=lambda _: None):
        self.renderer = renderer or SvgRenderer()
        self.validator = validator or EvidenceValidator()
        self.boundary = boundary
        from .plot_renderer import PlotRenderer

        self.plot_renderer = PlotRenderer()

    def build(self, specification, *, run_root, store_path=None):
        if specification.get("artifact_kind") == "result_plot":
            from arw.kernel.state.result_plot import ResultPlotIR

            specification = dict(specification)
            specification.setdefault(
                "renderer_hints", self.plot_renderer.identity.model_dump(mode="json")
            )
            return ResultPlotIR.model_validate_json(json.dumps(specification))
        return SQLiteArtifactIRBuilder().build(
            specification, run_root=run_root, store_path=store_path
        )

    def _renderer_for(self, ir):
        return (
            self.plot_renderer if ir.artifact_kind == "result_plot" else self.renderer
        )

    def _plot_context(self, ir, run_root, resolution_context=None):
        if resolution_context is not None:
            return resolution_context
        from arw.kernel.ledger.accepted_refs import ResolutionContext

        projects = {r.project_id for r in ir.source_refs}
        if len(projects) != 1:
            raise IRValidationFault("plot_project_scope_ambiguous")
        return ResolutionContext(
            project_id=next(iter(projects)), run_roots=(Path(run_root),)
        )

    def _plot_replay(self, run_root, context):
        from arw.kernel.ledger.journal import (
            replay_run_prefix,
            replay_run_under_held_lock,
        )
        from arw.kernel.state.models import RunManifest

        manifest = RunManifest.model_validate_json(
            read_retained_bytes(run_root, "run-manifest.json")
        )
        prefix = next(
            (p for p in context.run_prefixes if p.run_id == manifest.run_id), None
        )
        if context.run_prefixes and prefix is None:
            raise IRValidationFault("plot_target_missing_snapshot_prefix")
        arguments = (
            {}
            if prefix is None
            else {
                "revision": prefix.revision,
                "expected_head_sha256": prefix.head_sha256,
                "expected_manifest_sha256": prefix.run_manifest_sha256,
            }
        )
        if Path(run_root).absolute() in {
            Path(p).absolute() for p in context.held_lock_roots
        }:
            return replay_run_under_held_lock(run_root, **arguments)
        if prefix:
            return replay_run_prefix(run_root, **arguments)
        return replay_run(run_root)

    def _render(self, ir, *, run_root=None, resolution_context=None):
        renderer = self._renderer_for(ir)
        if ir.renderer_hints != renderer.identity:
            raise IRValidationFault("pinned_renderer_unavailable")
        raw = canonical_json_bytes(ir.model_dump(mode="json"))
        reject_secret_shapes(raw)
        if ir.artifact_kind == "result_plot":
            from .plot_policy import compile_plot

            context = self._plot_context(ir, run_root, resolution_context)
            output = renderer.render(
                compile_plot(ir, context, acceptance_root=run_root)
            )
        else:
            output = renderer.render(ir)
        if len(output) > 2_097_152:
            raise IRValidationFault("render_output_budget_exceeded")
        return raw, output

    def render(self, ir, *, run_root, resolution_context=None):
        raw, output = self._render(
            ir, run_root=run_root, resolution_context=resolution_context
        )
        prefix = f".arw/artifacts/candidates/{ir.artifact_id}/{sha256_hex(raw)}"
        publish_once(run_root, f"{prefix}/ir.json", raw)
        publish_once(run_root, f"{prefix}/figure.svg", output)
        return {
            "status": "candidate",
            "ir_sha256": sha256_hex(raw),
            "output_sha256": sha256_hex(output),
            "path": f"{prefix}/figure.svg",
        }

    def capture_result_plot(
        self,
        ir,
        *,
        run_root,
        resolution_context=None,
        visual_review_id=None,
        hard_caption_checks=False,
        attestation_verifier=None,
    ):
        """Read-only result receipt, including multi-run accepted-source rendering.

        Qualification here describes checks only. Parent-ledger acceptance is
        performed exclusively by qualify and is separately constrained.
        """
        from arw.kernel.state.result_plot import FigureRenderedFrom, ResultPlotReceipt

        from .plot_policy import compile_plot
        from .plot_validation import PlotValidator

        context = self._plot_context(ir, run_root, resolution_context)
        compiled = compile_plot(ir, context, acceptance_root=run_root)
        raw, output = self._render(ir, run_root=run_root, resolution_context=context)
        replayed = self._plot_replay(run_root, context)
        validation, reasons, reviewer, passed, checks = PlotValidator().validate(
            compiled,
            output,
            run_root=run_root,
            events=replayed.events,
            visual_review_id=visual_review_id,
            resolution_context=context,
            hard_caption_checks=hard_caption_checks,
            attestation_verifier=attestation_verifier,
        )
        digest = sha256_hex(raw)
        prefix = f".arw/artifacts/candidates/{ir.artifact_id}/{digest}"
        receipt = ResultPlotReceipt(
            artifact_id=ir.artifact_id,
            revision=ir.revision,
            ir_sha256=digest,
            renderer=self.plot_renderer.identity,
            inputs=ir.source_refs,
            rendered_from=FigureRenderedFrom(
                source_refs=ir.source_refs,
                ir_sha256=digest,
                renderer=self.plot_renderer.identity,
            ),
            outputs=(
                OutputDigest(path=f"{prefix}/ir.json", sha256=digest),
                OutputDigest(path=f"{prefix}/figure.svg", sha256=sha256_hex(output)),
            ),
            plot_values=compiled.plot_values,
            checks=checks,
            metadata=compiled.metadata,
            validation_policy=ir.validation_policy,
            validation=validation,
            qualification="PASS" if passed else "FAIL",
            purpose="publication-critical"
            if ir.publication_critical
            else "exploratory",
            visual_reviewer=reviewer,
            reason_codes=reasons,
            publication_quality="reviewed"
            if validation.visual == "PASS"
            else "not_verified",
        )
        return receipt, raw, output

    def qualify(
        self,
        ir,
        *,
        run_root,
        request,
        visual_review_id=None,
        resolution_context=None,
        hard_caption_checks=False,
        attestation_verifier=None,
    ):
        if ir.artifact_kind == "result_plot":
            if any(
                r.scope != "parent-artifact" or r.run_id != request.run_id
                for r in ir.source_refs
            ):
                from .plot_policy import PlotFault

                if not ir.acceptance_bindings:
                    raise PlotFault("plot_source_bridge_required")
            return self._qualify_plot(
                ir,
                run_root=run_root,
                request=request,
                visual_review_id=visual_review_id,
                resolution_context=resolution_context,
                hard_caption_checks=hard_caption_checks,
                attestation_verifier=attestation_verifier,
            )

        def prepare(events):
            raw, output = self._render(ir)
            validation, reasons, reviewer, passed = self.validator.validate(
                ir,
                output,
                run_root=run_root,
                events=events,
                visual_review_id=visual_review_id,
            )
            ir_sha = sha256_hex(raw)
            candidate = f".arw/artifacts/candidates/{ir.artifact_id}/{ir_sha}"
            accepted = f".arw/artifacts/accepted/{ir.artifact_id}"
            prefix = accepted if passed else candidate
            receipt = ResearchArtifactReceipt(
                receipt_version="arw.research-artifact-receipt.v1",
                artifact_id=ir.artifact_id,
                artifact_kind=ir.artifact_kind,
                ir_sha256=ir_sha,
                renderer=self.renderer.identity,
                inputs=ir.research_bindings,
                outputs=(
                    OutputDigest(path=f"{prefix}/ir.json", sha256=ir_sha),
                    OutputDigest(
                        path=f"{prefix}/figure.svg", sha256=sha256_hex(output)
                    ),
                ),
                validation_policy=ir.validation_policy,
                validation=validation,
                qualification="PASS" if passed else "FAIL",
                purpose="publication-critical"
                if ir.publication_critical
                else "exploratory",
                visual_reviewer=reviewer,
                reason_codes=reasons,
            )
            receipt_raw = canonical_json_bytes(receipt.model_dump(mode="json"))
            files = {
                f"{candidate}/ir.json": raw,
                f"{candidate}/figure.svg": output,
                f"{candidate}/receipt.json": receipt_raw,
            }
            if passed:
                files.update(
                    {
                        f"{accepted}/ir.json": raw,
                        f"{accepted}/figure.svg": output,
                        f"{accepted}/receipt.json": receipt_raw,
                    }
                )
            return ir, receipt, files

        return commit_artifact_pipeline(
            run_root, request, prepare, boundary=self.boundary
        )

    def caption_targets(self, ir, *, run_root, resolution_context=None):
        from .plot_policy import caption_target, compile_plot

        context = self._plot_context(ir, run_root, resolution_context)
        compiled = compile_plot(ir, context, acceptance_root=run_root)
        targets = []
        for binding in ir.caption_bindings:
            digest = sha256_hex(canonical_json_bytes(caption_target(compiled, binding)))
            targets.append(
                {
                    "binding_id": binding.binding_id,
                    "target_sha256": digest,
                    "scope": "caption:" + digest,
                }
            )
        return {
            "artifact_id": ir.artifact_id,
            "revision": ir.revision,
            "bindings": targets,
        }

    def source_bridge(self, ir, *, run_root, resolution_context=None):
        from .plot_policy import build_source_bridge

        context = self._plot_context(ir, run_root, resolution_context)
        return build_source_bridge(ir, context).model_dump(mode="json")

    def verify_plot_receipt(
        self, run_root, events, artifact_id, *, resolution_context=None
    ):
        return verify_plot_receipt(
            run_root, events, artifact_id, resolution_context=resolution_context
        )

    def _qualify_plot(self, ir, *, run_root, request, **options):
        def prepare(events):
            # Only this internal callback owns the actual parent writer lock.
            context = self._plot_context(
                ir, run_root, options.get("resolution_context")
            )
            context = replace(context, held_lock_roots=(Path(run_root).absolute(),))
            prepared_options = {**options, "resolution_context": context}
            if ir.supersedes:
                from arw.kernel.state.result_plot import ResultPlotReceipt

                prior = ResultPlotReceipt.model_validate_json(
                    read_retained_bytes(
                        run_root,
                        f".arw/artifacts/accepted/{ir.supersedes}/receipt.json",
                    )
                )
                if ir.revision != prior.revision + 1:
                    raise IRValidationFault("plot_supersession_revision_mismatch")
            receipt, raw, output = self.capture_result_plot(
                ir, run_root=run_root, **prepared_options
            )
            digest = sha256_hex(raw)
            candidate = f".arw/artifacts/candidates/{ir.artifact_id}/{digest}"
            accepted = f".arw/artifacts/accepted/{ir.artifact_id}"
            passed = receipt.qualification == "PASS"
            if passed:
                receipt = receipt.model_copy(
                    update={
                        "outputs": tuple(
                            o.model_copy(
                                update={
                                    "path": o.path.replace(
                                        candidate + "/", accepted + "/", 1
                                    )
                                }
                            )
                            for o in receipt.outputs
                        )
                    }
                )
            receipt_raw = canonical_json_bytes(receipt.model_dump(mode="json"))
            files = {
                f"{candidate}/ir.json": raw,
                f"{candidate}/figure.svg": output,
                f"{candidate}/receipt.json": receipt_raw,
            }
            if passed:
                files.update(
                    {
                        f"{accepted}/ir.json": raw,
                        f"{accepted}/figure.svg": output,
                        f"{accepted}/receipt.json": receipt_raw,
                    }
                )
            return ir, receipt, files

        return commit_artifact_pipeline(
            run_root, request, prepare, boundary=self.boundary
        )

    def inspect(self, artifact_id, *, run_root):
        TypeAdapter(StableRuntimeId).validate_python(artifact_id)
        replayed = replay_run(run_root)
        matches = [
            e
            for e in replayed.events
            if e.event_type == "research_artifact_accepted"
            and e.payload.artifact_id == artifact_id
        ]
        if len(matches) != 1:
            raise ResearchRecordError("artifact_not_accepted")
        event = matches[0]
        prefix = f".arw/artifacts/accepted/{artifact_id}"
        if (Path(run_root) / prefix / "tombstone.json").exists():
            tombstone = json.loads(
                read_retained_bytes(run_root, f"{prefix}/tombstone.json")
            )
            authorization, auth_event, _ = accepted_content(
                run_root, replayed.events, tombstone["authorization_artifact_id"]
            )
            if (
                authorization.get("action") != "purge_research_artifact"
                or authorization.get("artifact_id") != artifact_id
                or auth_event.event_sha256 != tombstone["authorization_event_sha256"]
            ):
                raise ResearchRecordError("invalid_purge_authorization")
            raise BodyUnavailable(
                f"body intentionally unavailable: {artifact_id}; authorization {auth_event.event_id}"
            )
        raw = read_retained_bytes(run_root, f"{prefix}/receipt.json")
        if sha256_hex(raw) != event.payload.artifact_sha256:
            raise ResearchRecordError("receipt_digest_mismatch")
        from arw.kernel.state.result_plot import ResultPlotReceipt

        model = (
            ResultPlotReceipt
            if json.loads(raw).get("artifact_kind") == "result_plot"
            else ResearchArtifactReceipt
        )
        receipt = model.model_validate_json(raw)
        for output in receipt.outputs:
            if not output.path.startswith(prefix + "/"):
                raise ResearchRecordError("accepted_output_path_mismatch")
            if sha256_hex(read_retained_bytes(run_root, output.path)) != output.sha256:
                raise ResearchRecordError("accepted_output_digest_mismatch")
        binding = json.loads(read_retained_bytes(run_root, f"{prefix}/binding.json"))
        expected = {
            "artifact_id": artifact_id,
            "ir_sha256": event.payload.ir_sha256,
            "receipt_sha256": event.payload.artifact_sha256,
            "event_id": event.event_id,
            "event_sha256": event.event_sha256,
        }
        if binding != expected:
            raise ResearchRecordError("post_freeze_binding_mismatch")
        return {
            "status": "accepted",
            "receipt": receipt.model_dump(mode="json"),
            "binding": binding,
            "supersedes": event.payload.supersedes,
            "renderer_available": receipt.renderer
            == (
                self.plot_renderer.identity
                if receipt.artifact_kind == "result_plot"
                else self.renderer.identity
            ),
        }

    def reproduce(self, artifact_id, *, run_root, resolution_context=None):
        inspection = self.inspect(artifact_id, run_root=run_root)
        raw = read_retained_bytes(
            run_root, f".arw/artifacts/accepted/{artifact_id}/ir.json"
        )
        from arw.kernel.state.result_plot import ResultPlotIR

        model = (
            ResultPlotIR
            if json.loads(raw).get("artifact_kind") == "result_plot"
            else ResearchArtifactIR
        )
        ir = model.model_validate_json(raw)
        _, output = self._render(
            ir, run_root=run_root, resolution_context=resolution_context
        )
        expected = next(
            o["sha256"]
            for o in inspection["receipt"]["outputs"]
            if o["path"].endswith("/figure.svg")
        )
        if sha256_hex(output) != expected:
            raise ResearchRecordError("reproduction_digest_mismatch")
        return {
            "status": "reproduced",
            "artifact_id": artifact_id,
            "output_sha256": expected,
            "renderer": self._renderer_for(ir).identity.model_dump(mode="json"),
        }

    def doctor(self, *, run_root):
        try:
            replayed = replay_run(run_root)
        except (ValueError, RuntimeError):
            return {
                "status": "FAIL",
                "faults": [{"code": "canonical_history_invalid"}],
                "accepted_artifacts": None,
            }
        accepted = [
            e for e in replayed.events if e.event_type == "research_artifact_accepted"
        ]
        predecessors = {e.payload.artifact_id: e.payload.supersedes for e in accepted}
        faults = []
        for artifact_id in predecessors:
            seen = set()
            current = artifact_id
            while current is not None:
                if current in seen:
                    faults.append(
                        {"artifact_id": artifact_id, "code": "supersession_cycle"}
                    )
                    break
                seen.add(current)
                current = predecessors.get(current)
            try:
                inspection = self.inspect(artifact_id, run_root=run_root)
                if not inspection["renderer_available"]:
                    faults.append(
                        {
                            "artifact_id": artifact_id,
                            "code": "pinned_renderer_unavailable",
                        }
                    )
            except (ValueError, RuntimeError, OSError) as error:
                faults.append(
                    {
                        "artifact_id": artifact_id,
                        "code": getattr(error, "code", "artifact_integrity_fault"),
                    }
                )
        return {
            "status": "PASS" if not faults else "FAIL",
            "faults": faults,
            "accepted_artifacts": len(accepted),
        }

    def purge(
        self, artifact_id, *, run_root, authorization_artifact_id, authorized=False
    ):
        if not authorized:
            raise ResearchRecordError("explicit_purge_authorization_required")
        TypeAdapter(StableRuntimeId).validate_python(artifact_id)
        with locked_replay(run_root) as (_, replayed):
            accepting = next(
                (
                    e
                    for e in replayed.events
                    if e.event_type == "research_artifact_accepted"
                    and e.payload.artifact_id == artifact_id
                ),
                None,
            )
            if accepting is None:
                raise ResearchRecordError("artifact_not_accepted")
            value, authorization, _ = accepted_content(
                run_root, replayed.events, authorization_artifact_id
            )
            if (
                value.get("action") != "purge_research_artifact"
                or value.get("artifact_id") != artifact_id
            ):
                raise ResearchRecordError("authorization_does_not_cover_artifact")
            prefix = f".arw/artifacts/accepted/{artifact_id}"
            tombstone = {
                "artifact_id": artifact_id,
                "body_status": "intentionally_unavailable",
                "authorization_artifact_id": authorization_artifact_id,
                "authorization_event_sha256": authorization.event_sha256,
                "accepted_receipt_sha256": accepting.payload.artifact_sha256,
            }
            publish_once(
                run_root, f"{prefix}/tombstone.json", canonical_json_bytes(tombstone)
            )
            for directory in (
                prefix,
                f".arw/artifacts/candidates/{artifact_id}/{accepting.payload.ir_sha256}",
            ):
                for filename in ("ir.json", "figure.svg", "receipt.json"):
                    relative = f"{directory}/{filename}"
                    path = Path(run_root) / relative
                    if path.exists():
                        read_retained_bytes(run_root, relative)
                        unlink_retained(run_root, relative)
            return {"status": "body_unavailable", "tombstone": tombstone}


def verify_plot_receipt(run_root, events, artifact_id, *, resolution_context=None):
    """Verify an accepted Figure at the caller's parent-event prefix.

    Receipt/output bytes, post-freeze binding, accepted source refs and every
    exact plot value are checked. This proves integrity only; caption advisory,
    unsupported statistical recomputation and visual states remain explicit.
    """
    from arw.kernel.state.result_plot import ResultPlotIR, ResultPlotReceipt

    from .plot_policy import PlotFault, compile_plot

    accepted = [
        e
        for e in events
        if e.event_type == "research_artifact_accepted"
        and e.payload.artifact_id == artifact_id
    ]
    if len(accepted) != 1:
        raise PlotFault("plot_not_accepted_at_prefix")
    service = ResearchArtifactService()
    inspected = service.inspect(artifact_id, run_root=run_root)
    if inspected["binding"]["event_sha256"] != accepted[0].event_sha256:
        raise PlotFault("plot_accepting_prefix_mismatch")
    receipt = ResultPlotReceipt.model_validate_json(json.dumps(inspected["receipt"]))
    raw = read_retained_bytes(
        run_root, f".arw/artifacts/accepted/{artifact_id}/ir.json"
    )
    ir = ResultPlotIR.model_validate_json(raw)
    if (
        sha256_hex(raw) != receipt.ir_sha256
        or receipt.ir_sha256 != accepted[0].payload.ir_sha256
    ):
        raise PlotFault("plot_ir_digest_mismatch")
    context = service._plot_context(ir, run_root, resolution_context)
    compiled = compile_plot(ir, context, acceptance_root=run_root)
    if (
        receipt.plot_values != compiled.plot_values
        or receipt.metadata != compiled.metadata
        or receipt.inputs != ir.source_refs
        or receipt.rendered_from.source_refs != ir.source_refs
        or receipt.rendered_from.ir_sha256 != receipt.ir_sha256
        or receipt.rendered_from.renderer != receipt.renderer
    ):
        raise PlotFault("plot_receipt_derivation_mismatch")
    _, output = service._render(ir, run_root=run_root, resolution_context=context)
    digest = next(o.sha256 for o in receipt.outputs if o.path.endswith("/figure.svg"))
    if sha256_hex(output) != digest:
        raise PlotFault("plot_reproduction_digest_mismatch")
    return receipt

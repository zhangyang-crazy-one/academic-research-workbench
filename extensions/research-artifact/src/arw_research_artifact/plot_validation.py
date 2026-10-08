"""Result policy plus the existing exact-output visual review validator."""

from __future__ import annotations

from arw.kernel.state.research_artifact import ValidationResults

from .plot_policy import PlotFault, caption_checks, validate_svg_safety
from .validation import EvidenceValidator


class _VisualProxy:
    """Retain exact result IR hashing while exposing empty schematic elements.

    Numeric/source checks are completed by compile_plot. EvidenceValidator is
    reused only for its original accepted visual review evidence contract.
    """

    def __init__(self, ir):
        self.ir = ir
        self.research_bindings = ()
        self.nodes = self.edges = self.groups = self.annotations = ()
        self.validation_policy = ir.validation_policy

    def model_dump(self, **kwargs):
        return self.ir.model_dump(**kwargs)


class PlotValidator:
    def validate(
        self,
        compiled,
        output,
        *,
        run_root,
        events,
        visual_review_id=None,
        resolution_context=None,
        hard_caption_checks=False,
        attestation_verifier=None,
    ):
        ir = compiled.ir
        checks = compiled.checks + caption_checks(
            compiled,
            resolution_context=resolution_context,
            hard_caption_checks=hard_caption_checks,
            attestation_verifier=attestation_verifier,
        )
        # The empty proxy makes legacy semantic loops vacuous; compiler has
        # already verified actual numeric/source semantics separately.
        validation, reasons, reviewer, passed = EvidenceValidator().validate(
            _VisualProxy(ir),
            output,
            run_root=run_root,
            events=events,
            visual_review_id=visual_review_id,
        )
        states = validation.model_dump(mode="json")
        reasons = list(reasons)
        try:
            validate_svg_safety(output)
        except PlotFault as error:
            states["render"] = "FAIL"
            reasons.append(error.code)
        if hard_caption_checks and any(
            c.category == "caption" and c.status in {"FAIL", "unsupported"}
            for c in checks
        ):
            states["semantic"] = "FAIL"
            reasons.extend(
                c.code
                for c in checks
                if c.category == "caption" and c.status in {"FAIL", "unsupported"}
            )
        passed = passed and "FAIL" not in states.values()
        return (
            ValidationResults.model_validate_json(__import__("json").dumps(states)),
            tuple(sorted(set(reasons))),
            reviewer,
            passed,
            checks,
        )

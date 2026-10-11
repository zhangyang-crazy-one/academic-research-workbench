"""New nested semantics preserve comparison identity and old evaluator bytes."""

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.policy.numeric_core import evaluate_derivation, result_unit
from arw.kernel.state.numeric_core import Derivation, DerivationRef
from tests.unit.test_accepted_refs import accepted_fixture
from tests.unit.test_numeric_core import CTX, fraction, request, scalar


@pytest.mark.parametrize(
    "operation,unit,expected",
    [
        ("relative_change", "ratio", (1, 5)),
        ("ratio", "ratio", (6, 5)),
        ("count", "count", (2, 1)),
    ],
)
def test_nested_value_uses_output_dimension_with_same_comparison_identity(
    tmp_path, operation, unit, expected
):
    _, context, ref, _ = accepted_fixture(tmp_path, b'{"current":120,"baseline":100}\n')
    ms = CTX.model_copy(update={"metric_definition": "latency", "unit": "ms"})
    child = evaluate_derivation(
        request(
            operation,
            scalar(ref, "/current", comparison=ms),
            scalar(ref, "/baseline", comparison=ms),
            context=ms,
        ),
        context,
    )
    mapping = {child.derivation_id: child}
    output_context = ms.model_copy(update={"unit": unit})
    outer = request(
        "value",
        DerivationRef(derivation_id=child.derivation_id),
        context=output_context,
    )
    result = evaluate_derivation(outer, context, mapping)
    assert (
        fraction(result).numerator == expected[0]
        and fraction(result).denominator == expected[1]
    )
    assert result_unit(result.request) == unit
    wrong = outer.model_copy(update={"context": ms})
    assert evaluate_derivation(wrong, context, mapping).status == "context_mismatch"
    for field in ("dataset", "metric_definition", "split", "evaluation_condition"):
        changed = outer.model_copy(
            update={"context": output_context.model_copy(update={field: "different"})}
        )
        assert (
            evaluate_derivation(changed, context, mapping).status == "context_mismatch"
        )


def test_legacy_nested_v1_results_keep_their_original_semantics_and_bytes(tmp_path):
    _, context, ref, _ = accepted_fixture(tmp_path, b'{"current":120,"baseline":100}\n')
    ms = CTX.model_copy(update={"unit": "ms"})
    child_request = request(
        "relative_change",
        scalar(ref, "/current", comparison=ms),
        scalar(ref, "/baseline", comparison=ms),
        context=ms,
    ).model_copy(update={"evaluator_version": "arw.rational.v1"})
    child = evaluate_derivation(child_request, context)
    outer = request(
        "value", DerivationRef(derivation_id=child.derivation_id), context=ms
    ).model_copy(update={"evaluator_version": "arw.rational.v1"})
    original = evaluate_derivation(outer, context, {child.derivation_id: child})
    raw = canonical_json_bytes(original.model_dump(mode="json"))
    assert Derivation.model_validate_json(raw) == original
    assert evaluate_derivation(outer, context, {child.derivation_id: child}) == original
    assert result_unit(original.request) == "ms" and fraction(original).numerator == 1
    # New requests cannot silently acquire that historical output dimension.
    upgraded = outer.model_copy(update={"evaluator_version": "arw.rational.v2"})
    assert (
        evaluate_derivation(upgraded, context, {child.derivation_id: child}).status
        == "context_mismatch"
    )
    assert canonical_json_bytes(original.model_dump(mode="json")) == raw

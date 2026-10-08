"""Exact numeric source selection and identity, using actual accepted artifacts."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import jsonschema
import pytest

from arw.kernel.artifacts.experiment_acceptance import ComparisonContext
from arw.kernel.policy.numeric_core import (
    derivation_id,
    evaluate_derivation,
    format_exact,
    resolve_operand,
)
from arw.kernel.state.numeric_core import (
    MAX_INTEGER,
    CsvSelection,
    DerivationRef,
    DerivationRequest,
    NumericExpression,
    NumericPresentation,
    RationalExact,
    RowIds,
    RowPredicate,
    ScalarJson,
    numeric_core_schema_documents,
)
from tests.unit.test_accepted_refs import accepted_fixture

CTX = ComparisonContext(
    metric_definition="accuracy",
    unit="ratio",
    dataset="test-data",
    split="test",
    evaluation_condition="fixed protocol",
)


def scalar(ref, pointer, *, comparison=CTX):
    return ScalarJson(
        ref=ref, json_pointer=pointer, unit=comparison.unit, context=comparison
    )


def selection(ref, **kwargs):
    return CsvSelection(
        ref=ref,
        columns=("score",),
        row_id_column="id",
        context=CTX,
        unit="ratio",
        **kwargs,
    )


def request(op, *args, context=CTX):
    return DerivationRequest(expr=NumericExpression(op=op, args=args), context=context)


def fraction(result):
    assert result.status == "exact", result
    return result.exact.as_fraction()


def test_nonterminating_mean_and_percentage_semantics(tmp_path):
    _, context, csv_ref, _ = accepted_fixture(tmp_path, b"id,score\na,0\nb,0\nc,1\n")
    mean = evaluate_derivation(request("mean", selection(csv_ref)), context)
    assert fraction(mean) == Fraction(1, 3)
    display = NumericPresentation(
        derivation_id=mean.derivation_id, decimals=2, rounding_mode="ROUND_HALF_EVEN"
    )
    assert format_exact(mean.exact, display) == "0.33"
    _, scalar_context, ref, _ = accepted_fixture(
        tmp_path, b'{"baseline":0.80,"current":0.831}\n', run_index=2
    )
    args = scalar(ref, "/current"), scalar(ref, "/baseline")
    point = evaluate_derivation(request("pct_point_diff", *args), scalar_context)
    relative = evaluate_derivation(request("relative_change", *args), scalar_context)
    assert fraction(point) == Fraction(31, 1000)
    assert fraction(relative) == Fraction(31, 800)
    hundred = RationalExact(numerator=100, denominator=1)
    assert (
        format_exact(
            point.exact,
            NumericPresentation(
                derivation_id=point.derivation_id,
                decimals=1,
                rounding_mode="ROUND_HALF_EVEN",
                scale=hundred,
                unit_suffix=" percentage points",
            ),
        )
        == "3.1 percentage points"
    )
    assert (
        format_exact(
            relative.exact,
            NumericPresentation(
                derivation_id=relative.derivation_id,
                decimals=2,
                rounding_mode="ROUND_HALF_EVEN",
                scale=hundred,
                unit_suffix="%",
            ),
        )
        == "3.88%"
    )


def test_selection_groups_identity_and_stable_metadata(tmp_path):
    _, context, ref, _ = accepted_fixture(
        tmp_path,
        b"id,score,series,order,pair\nc,0.831,B,2,p1\na,0.80,A,1,p1\nb,0.831,A,2,p2\n",
    )
    all_rows = resolve_operand(selection(ref), context)
    assert tuple(r.row_id for r in all_rows.rows) == ("a", "b", "c")
    assert all_rows.rows[2].fields["order"] == "2"
    subset = selection(ref, row_set=RowIds(ids=("a", "b")))
    another = selection(ref, row_set=RowIds(ids=("c",)))
    assert derivation_id(request("mean", subset)) != derivation_id(
        request("mean", another)
    )
    grouped = evaluate_derivation(
        request("mean", selection(ref, group_by=("series",))), context
    )
    assert [(g.key, g.exact.as_fraction(), g.row_ids) for g in grouped.groups] == [
        (("A",), Fraction(1631, 2000), ("a", "b")),
        (("B",), Fraction(831, 1000), ("c",)),
    ]
    predicate = selection(
        ref, row_set=RowPredicate(column="series", op="eq", value="A")
    )
    assert fraction(evaluate_derivation(request("count", predicate), context)) == 2
    original = request("mean", subset)
    result = evaluate_derivation(original, context)
    for decimals in (2, 3, 5):
        format_exact(
            result.exact,
            NumericPresentation(
                derivation_id=result.derivation_id,
                decimals=decimals,
                rounding_mode="ROUND_HALF_EVEN",
            ),
        )
        assert derivation_id(original) == result.derivation_id


@pytest.mark.parametrize(
    ("raw", "policy", "status"),
    [
        (b"id,score\na,1\nb,\n", "reject", "out_of_domain"),
        (b"id,score\na,1\nb,\n", "exclude", "exact"),
        (b"id,score\na,1\na,2\n", "exclude", "out_of_domain"),
        (b"id,score\n,1\n", "reject", "out_of_domain"),
        (b"id,score,score\na,1,2\n", "reject", "out_of_domain"),
    ],
)
def test_missing_and_duplicate_row_contract(tmp_path, raw, policy, status):
    _, context, ref, _ = accepted_fixture(tmp_path, raw)
    result = evaluate_derivation(
        request("mean", selection(ref, missing_policy=policy)), context
    )
    assert result.status == status
    if status == "exact":
        resolved = resolve_operand(selection(ref, missing_policy=policy), context)
        assert resolved.excluded_row_ids == ("b",)
        assert fraction(result) == 1


def test_typed_undefined_context_domain_and_unsupported(tmp_path):
    _, context, ref, _ = accepted_fixture(
        tmp_path, b'{"zero":0,"one":1,"outside":2,"huge":"1e9999999","bool":true}\n'
    )
    assert (
        evaluate_derivation(
            request("ratio", scalar(ref, "/one"), scalar(ref, "/zero")), context
        ).status
        == "undefined"
    )
    other = CTX.model_copy(update={"split": "validation"})
    assert (
        evaluate_derivation(
            request("diff", scalar(ref, "/one"), scalar(ref, "/one", comparison=other)),
            context,
        ).status
        == "context_mismatch"
    )
    assert (
        evaluate_derivation(
            request("pct_point_diff", scalar(ref, "/outside"), scalar(ref, "/one")),
            context,
        ).status
        == "out_of_domain"
    )
    for pointer in ("/huge", "/bool"):
        assert (
            evaluate_derivation(request("value", scalar(ref, pointer)), context).status
            == "out_of_domain"
        )
    unsupported = request("value", scalar(ref, "/one")).model_copy(
        update={"evaluator_version": "future.v2"}
    )
    assert evaluate_derivation(unsupported, context).status == "unsupported"
    with pytest.raises(ValueError):
        NumericExpression(op="sample_sd", args=(scalar(ref, "/one"),))


def test_distinct_exact_values_same_display_and_legacy_observed_rejected(tmp_path):
    _, context, ref, _ = accepted_fixture(tmp_path, b'{"first":0.831,"second":0.834}\n')
    a = evaluate_derivation(request("value", scalar(ref, "/first")), context)
    b = evaluate_derivation(request("value", scalar(ref, "/second")), context)
    assert a.exact != b.exact and a.derivation_id != b.derivation_id
    assert (
        format_exact(
            a.exact,
            NumericPresentation(
                derivation_id=a.derivation_id,
                decimals=2,
                rounding_mode="ROUND_HALF_EVEN",
            ),
        )
        == format_exact(
            b.exact,
            NumericPresentation(
                derivation_id=b.derivation_id,
                decimals=2,
                rounding_mode="ROUND_HALF_EVEN",
            ),
        )
        == "0.83"
    )
    raw = b'{"schema_version":"arw.experiment-acceptance.v1","checks":[{"observed":"0.333333333333"}]}\n'
    run, old_context, old_ref, _ = accepted_fixture(tmp_path, raw, run_index=2)
    before = (run / "data.json").read_bytes()
    old = evaluate_derivation(
        request("value", scalar(old_ref, "/checks/0/observed")), old_context
    )
    assert (
        old.status == "unsupported" and old.reason == "legacy_observed_is_display_only"
    )
    assert (run / "data.json").read_bytes() == before


def test_derivation_refs_recompute_and_do_not_trust_cached_exact(tmp_path):
    _, context, ref, _ = accepted_fixture(tmp_path, b'{"first":0.8,"second":0.831}\n')
    a = evaluate_derivation(request("value", scalar(ref, "/first")), context)
    b = evaluate_derivation(request("value", scalar(ref, "/second")), context)
    altered = b.model_copy(update={"exact": RationalExact(numerator=99, denominator=1)})
    comparison = request(
        "diff",
        DerivationRef(derivation_id=b.derivation_id),
        DerivationRef(derivation_id=a.derivation_id),
    )
    result = evaluate_derivation(
        comparison, context, {a.derivation_id: a, b.derivation_id: altered}
    )
    assert fraction(result) == Fraction(31, 1000)
    assert evaluate_derivation(comparison, context).status == "unsupported"


def test_numeric_schema_drift_and_rational_strictness():
    for name, schema in numeric_core_schema_documents().items():
        jsonschema.Draft202012Validator.check_schema(schema)
        assert (
            json.loads(
                (Path(__file__).resolve().parents[2] / "schemas/v1" / name).read_bytes()
            )
            == schema
        )
    for numerator, denominator in (
        (2, 6),
        (0, 3),
        (1, -1),
        (MAX_INTEGER + 1, 1),
        ("1", 3),
    ):
        with pytest.raises(ValueError):
            RationalExact(numerator=numerator, denominator=denominator)

"""Bounded rational evaluation over accepted files, independent of figures."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.ledger.accepted_refs import (
    ResolutionCache,
    ResolutionContext,
    resolve_pointer,
    resolve_ref,
)
from arw.kernel.state.numeric_core import (
    EVALUATOR_VERSION,
    MAX_INTEGER,
    CsvSelection,
    Derivation,
    DerivationRef,
    DerivationRequest,
    NumericGroup,
    NumericPresentation,
    RationalExact,
    RowIds,
    RowPredicate,
    ScalarJson,
)

MAX_ROWS = 10000
MAX_DEPTH = 32
MAX_DERIVATIONS = 128
MAX_RESOLVED_VALUES = 320000
MAX_NUMERIC_TEXT = 256


class NumericDomainError(ValueError):
    pass


# Output-dimension contract for every evaluator operator.  Plots, axis checks
# and caption bindings must consume this single derivation instead of
# inheriting an operand unit (#97): a relative_change of 120 ms over 100 ms is
# the dimensionless proportion 1/5, never "1/5 ms".
RATIO_RESULT_OPS = frozenset({"ratio", "relative_change"})
COUNT_RESULT_OPS = frozenset({"count"})


def result_unit(request: DerivationRequest) -> str:
    """Return the output unit of an evaluated expression.

    ``ratio``/``relative_change`` produce a dimensionless proportion and
    ``count`` produces a cardinality.  Every other operator preserves the
    comparison-context unit; evaluation already requires every operand context
    to equal ``request.context``, so the context unit is the operand unit for
    any successful derivation, including derivation-reference operands.
    """
    op = request.expr.op
    if op in RATIO_RESULT_OPS:
        return "ratio"
    if op in COUNT_RESULT_OPS:
        return "count"
    return request.context.unit


@dataclass(frozen=True)
class SelectedRow:
    row_id: str
    fields: dict[str, str]
    values: dict[str, RationalExact]
    group_key: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedOperand:
    status: str
    values: tuple[RationalExact, ...] = ()
    rows: tuple[SelectedRow, ...] = ()
    reason: str | None = None
    context: object = None
    unit: str | None = None
    excluded_row_ids: tuple[str, ...] = ()


def _fraction(value: object) -> Fraction:
    if isinstance(value, RationalExact):
        return value.as_fraction()
    if type(value) is int:
        result = Fraction(value)
    elif isinstance(value, (str, Decimal)):
        text = str(value)
        if len(text) > MAX_NUMERIC_TEXT or not re.fullmatch(
            r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text
        ):
            raise NumericDomainError(
                "numeric source must be bounded finite decimal text"
            )
        decimal = Decimal(text)
        if (
            not decimal.is_finite()
            or abs(decimal.adjusted()) > 128
            or abs(decimal.as_tuple().exponent) > 256
        ):
            raise NumericDomainError("decimal exponent exceeds numeric budget")
        result = Fraction(decimal)
    else:
        # No float reconstruction from rounded old receipts.
        raise NumericDomainError("numeric source is not an exact decimal or integer")
    _exact(result)
    return result


def _exact(value: Fraction) -> RationalExact:
    if abs(value.numerator) > MAX_INTEGER or value.denominator > MAX_INTEGER:
        raise NumericDomainError("rational exceeds numerator/denominator budget")
    return RationalExact.from_fraction(value)


def parse_exact_number(value: object) -> RationalExact:
    """Parse bounded decimal metadata before any large-integer construction.

    The same lexical/rational domain applies to numeric operands and external
    order/caption metadata. Invalid input raises NumericDomainError.
    """
    return _exact(_fraction(value))


def _scaled(value: object, scale: RationalExact) -> RationalExact:
    return _exact(_fraction(value) * scale.as_fraction())


def _predicate(fields: dict[str, str], predicate: RowPredicate) -> bool:
    value = fields[predicate.column]
    if predicate.op in {"eq", "ne"}:
        return (
            value == predicate.value
            if predicate.op == "eq"
            else value != predicate.value
        )
    a, b = _fraction(value), _fraction(predicate.value)
    return {"lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[predicate.op]


def _csv_headers(raw: bytes) -> tuple | None:
    """Return validated CSV headers, or None when they violate the budget."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
    headers = reader.fieldnames
    if (
        not headers
        or len(headers) > 128
        or len(set(headers)) != len(headers)
        or any(not name or len(name) > 128 for name in headers)
    ):
        return None
    return tuple(headers)


def _scan_csv_rows(raw: bytes, row_id_column: str) -> tuple:
    """Full-table scan with the global row checks, shareable per operation (#98).

    Row budget, row shape and bounded globally-unique row IDs are validated for
    every row exactly as the per-selection path did.  Per-selection filtering,
    missing-value policy and value scaling stay with the caller so each
    derivation keeps its own semantics; stored field dicts are private copies.
    """
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
    seen, rows = set(), []
    for index, fields in enumerate(reader):
        if index >= MAX_ROWS:
            raise NumericDomainError("CSV exceeds row budget")
        if None in fields or any(
            v is None or len(v) > 4096 for v in fields.values()
        ):
            raise NumericDomainError("CSV row shape or field budget is invalid")
        row_id = fields[row_id_column]
        if not row_id or row_id in seen or len(row_id) > 128:
            raise NumericDomainError(
                "CSV row IDs must be bounded, nonempty and globally unique"
            )
        seen.add(row_id)
        rows.append((row_id, dict(fields)))
    return tuple(rows)


def resolve_operand(
    operand: ScalarJson | CsvSelection,
    context: ResolutionContext,
    cache: ResolutionCache | None = None,
) -> ResolvedOperand:
    try:
        operand = type(operand).model_validate_json(
            canonical_json_bytes(operand.model_dump(mode="json"))
        )
        if operand.scale.numerator <= 0:
            return ResolvedOperand("out_of_domain", reason="scale must be positive")
        if operand.unit != operand.context.unit:
            return ResolvedOperand(
                "context_mismatch",
                reason="operand unit differs from comparison context",
            )
        resolved = resolve_ref(operand.ref, context, cache=cache)
        if resolved.status != "resolved":
            return ResolvedOperand(
                "unsupported", reason=f"accepted_ref:{resolved.reason}"
            )
        if isinstance(operand, ScalarJson):
            raw = resolved.raw_bytes
            if raw is None:
                return ResolvedOperand(
                    "unsupported", reason="missing retained numeric source"
                )
            original = strict_json_loads(raw)
            if (
                isinstance(original, dict)
                and original.get("schema_version") == "arw.experiment-acceptance.v1"
            ):
                return ResolvedOperand(
                    "unsupported", reason="legacy_observed_is_display_only"
                )
            # Strict load already rejected duplicate keys and constants. Decimal
            # preserves the accepted literal, never an intermediate binary float.
            value = json.loads(raw, parse_float=Decimal)
            if operand.ref.scope == "project-journal":
                value = resolve_pointer(value["payload"], operand.ref.payload_selector)
            else:
                if operand.ref.source_locator is not None:
                    return ResolvedOperand(
                        "unsupported",
                        reason="source locator quote is not a scalar JSON document",
                    )
                value = resolve_pointer(value, operand.ref.selector)
            value = resolve_pointer(value, operand.json_pointer)
            exact = _scaled(value, operand.scale)
            return ResolvedOperand(
                "exact", (exact,), context=operand.context, unit=operand.unit
            )
        if operand.ref.selector or operand.ref.source_locator is not None:
            return ResolvedOperand(
                "unsupported", reason="CSV selection requires whole artifact bytes"
            )
        headers = _csv_headers(resolved.raw_bytes)
        if headers is None:
            return ResolvedOperand(
                "out_of_domain",
                reason="CSV headers are missing, duplicate or exceed budget",
            )
        required = (
            set(operand.columns) | set(operand.group_by) | {operand.row_id_column}
        )
        if isinstance(operand.row_set, RowPredicate):
            required.add(operand.row_set.column)
        if not required <= set(headers):
            return ResolvedOperand(
                "unsupported", reason="CSV selected columns are absent"
            )
        table = (
            _scan_csv_rows(resolved.raw_bytes, operand.row_id_column)
            if cache is None
            else cache.csv_rows(
                operand.ref,
                operand.row_id_column,
                lambda: _scan_csv_rows(resolved.raw_bytes, operand.row_id_column),
            )
        )
        rows, excluded = [], []
        for row_id, fields in table:
            if isinstance(operand.row_set, RowIds) and row_id not in operand.row_set.ids:
                continue
            if isinstance(operand.row_set, RowPredicate) and not _predicate(
                fields, operand.row_set
            ):
                continue
            if any(not fields[c].strip() for c in operand.columns):
                if operand.missing_policy == "exclude":
                    excluded.append(row_id)
                    continue
                raise NumericDomainError(
                    "selected CSV row contains a missing numeric value"
                )
            rows.append(
                SelectedRow(
                    row_id,
                    fields,
                    {
                        c: _scaled(fields[c].strip(), operand.scale)
                        for c in operand.columns
                    },
                    tuple(fields[c] for c in operand.group_by),
                )
            )
        if isinstance(operand.row_set, RowIds) and not set(
            operand.row_set.ids
        ) <= {row_id for row_id, _ in table}:
            raise NumericDomainError("requested CSV row IDs are absent")
        rows.sort(key=lambda row: row.row_id)
        values = tuple(row.values[column] for row in rows for column in operand.columns)
        return ResolvedOperand(
            "exact",
            values,
            tuple(rows),
            context=operand.context,
            unit=operand.unit,
            excluded_row_ids=tuple(sorted(excluded)),
        )
    except (
        ValueError,
        UnicodeError,
        KeyError,
        IndexError,
        csv.Error,
        TypeError,
        OverflowError,
    ):
        return ResolvedOperand(
            "out_of_domain", reason="invalid or over-budget numeric operand"
        )


def derivation_id(request: DerivationRequest) -> str:
    # Identity contains reference hashes, selectors, contexts and evaluator
    # version. Presentation and graph state have no place in this envelope.
    return sha256_hex(canonical_json_bytes(request.model_dump(mode="json")))


def _aggregate(op: str, values: list[Fraction]) -> Fraction:
    if op == "count":
        return Fraction(len(values))
    if not values:
        raise ZeroDivisionError("empty selection")
    if op == "sum":
        value = Fraction(0)
        for number in values:
            value += number
            _exact(value)
        return value
    if op == "mean":
        return _aggregate("sum", values) / len(values)
    if op == "median":
        ordered = sorted(values)
        middle = len(ordered) // 2
        return (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2
        )
    if op == "min":
        return min(values)
    if op == "max":
        return max(values)
    raise NumericDomainError("unsupported aggregation")


def evaluate_derivation(
    request: DerivationRequest,
    context: ResolutionContext,
    derivations: Mapping[str, Derivation] | None = None,
    cache: ResolutionCache | None = None,
    *,
    _seen: frozenset[str] = frozenset(),
    _memo: dict[str, Derivation] | None = None,
    _budget: list[int] | None = None,
) -> Derivation:
    identity = derivation_id(request)
    memo = {} if _memo is None else _memo
    budget = [0, 0] if _budget is None else _budget

    def outcome(status, reason=None, **values):
        result = Derivation(
            derivation_id=identity,
            request=request,
            status=status,
            reason=reason,
            **values,
        )
        memo[identity] = result
        return result

    try:
        request = DerivationRequest.model_validate_json(
            canonical_json_bytes(request.model_dump(mode="json"))
        )
        if request.evaluator_version != EVALUATOR_VERSION:
            return outcome("unsupported", "unsupported_evaluator_version")
        if identity in _seen or len(_seen) >= MAX_DEPTH:
            return outcome("out_of_domain", "cyclic or over-depth derivation")
        if identity in memo:
            return memo[identity]
        budget[0] += 1
        if budget[0] > MAX_DERIVATIONS:
            return outcome("out_of_domain", "derivation graph exceeds node budget")
        operands = []
        for arg in request.expr.args:
            if isinstance(arg, DerivationRef):
                candidate = (derivations or {}).get(arg.derivation_id)
                if (
                    candidate is None
                    or candidate.derivation_id != arg.derivation_id
                    or derivation_id(candidate.request) != arg.derivation_id
                ):
                    return outcome(
                        "unsupported", "missing or substituted derivation reference"
                    )
                # Stored exact/results are never authority: re-evaluate request.
                derived = evaluate_derivation(
                    candidate.request,
                    context,
                    derivations,
                    cache=cache,
                    _seen=_seen | {identity},
                    _memo=memo,
                    _budget=budget,
                )
                if derived.status != "exact":
                    return outcome(derived.status, derived.reason)
                values = (
                    (derived.exact,)
                    if derived.exact
                    else derived.values or tuple(g.exact for g in derived.groups)
                )
                resolved = ResolvedOperand(
                    "exact",
                    values,
                    context=candidate.request.context,
                    unit=candidate.request.context.unit,
                )
            else:
                resolved = resolve_operand(arg, context, cache=cache)
            if resolved.status != "exact":
                return outcome(resolved.status, resolved.reason)
            if resolved.context != request.context:
                return outcome("context_mismatch", "comparison contexts differ")
            budget[1] += len(resolved.values)
            if budget[1] > MAX_RESOLVED_VALUES:
                return outcome(
                    "out_of_domain", "resolved values exceed expression budget"
                )
            operands.append(resolved)
        op = request.expr.op
        if op in {"diff", "ratio", "pct_point_diff", "relative_change"}:
            if len(operands) != 2 or any(len(o.values) != 1 for o in operands):
                return outcome(
                    "unsupported",
                    "binary comparisons require exactly two scalar operands",
                )
            a, b = (o.values[0].as_fraction() for o in operands)
            if op == "pct_point_diff" and (
                request.context.unit not in {"ratio", "proportion"}
                or not (0 <= a <= 1 and 0 <= b <= 1)
            ):
                return outcome(
                    "out_of_domain",
                    "percentage comparisons require normalized proportions",
                )
            if op == "relative_change" and (a < 0 or b < 0):
                return outcome(
                    "out_of_domain", "relative change requires nonnegative quantities"
                )
            result = (
                a - b
                if op in {"diff", "pct_point_diff"}
                else a / b
                if op == "ratio"
                else (a - b) / b
            )
            return outcome("exact", exact=_exact(result))
        if op == "value":
            values = tuple(value for o in operands for value in o.values)
            if not values:
                return outcome("undefined", "empty selection")
            return (
                outcome("exact", exact=values[0])
                if len(values) == 1
                else outcome("exact", values=values)
            )
        if any(
            isinstance(arg, CsvSelection) and len(arg.columns) != 1
            for arg in request.expr.args
        ):
            return outcome(
                "unsupported", "aggregate requires an explicit single numeric column"
            )
        grouped = [
            o for o in operands if o.rows and any(row.group_key for row in o.rows)
        ]
        if grouped:
            if len(operands) != 1:
                return outcome(
                    "unsupported", "group aggregation requires one CSV selection"
                )
            group_map = {}
            for row in grouped[0].rows:
                group_map.setdefault(row.group_key, []).append(row)
            groups = tuple(
                NumericGroup(
                    key=key,
                    exact=_exact(
                        _aggregate(
                            op,
                            [
                                next(iter(row.values.values())).as_fraction()
                                for row in rows
                            ],
                        )
                    ),
                    row_ids=tuple(row.row_id for row in rows),
                )
                for key, rows in sorted(group_map.items())
            )
            return outcome("exact", groups=groups)
        values = [value.as_fraction() for o in operands for value in o.values]
        return outcome("exact", exact=_exact(_aggregate(op, values)))
    except ZeroDivisionError:
        return outcome("undefined", "zero denominator or empty selection")
    except (ValueError, TypeError, OverflowError):
        return outcome("out_of_domain", "invalid or over-budget numeric expression")


def format_exact(exact: RationalExact, presentation: NumericPresentation) -> str:
    """Round for display without changing exact values or derivation identity."""
    exact = RationalExact.model_validate_json(
        canonical_json_bytes(exact.model_dump(mode="json"))
    )
    presentation = NumericPresentation.model_validate_json(
        canonical_json_bytes(presentation.model_dump(mode="json"))
    )
    scaled = _exact(exact.as_fraction() * presentation.scale.as_fraction())
    with localcontext() as decimal_context:
        decimal_context.prec = 300
        value = Decimal(scaled.numerator) / Decimal(scaled.denominator)
        rounded = value.quantize(
            Decimal(1).scaleb(-presentation.decimals),
            rounding=presentation.rounding_mode,
        )
        return f"{rounded:.{presentation.decimals}f}{presentation.unit_suffix}"


def csv_selection_from_data_selector(selector, ref, context) -> CsvSelection:
    """Losslessly map an old DataSelector only when stable IDs were declared.

    Existing selectors without row identity retain their original evaluator;
    this adapter does not fabricate row IDs from physical line numbers.
    """
    from arw.kernel.artifacts.experiment_acceptance import DataSelector

    selector = DataSelector.model_validate_json(
        canonical_json_bytes(selector.model_dump(mode="json"))
    )
    if selector.row_id_column is None or selector.artifact_id != ref.artifact_id:
        raise ValueError(
            "DataSelector lacks stable row identity or differs from accepted artifact"
        )
    return CsvSelection(
        ref=ref,
        columns=(selector.column,),
        row_id_column=selector.row_id_column,
        missing_policy=selector.missing_values,
        context=context,
        unit=context.unit,
    )

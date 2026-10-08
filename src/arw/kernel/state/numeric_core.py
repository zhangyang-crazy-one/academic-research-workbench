"""Sealed exact numeric contracts shared by prose and plots."""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from arw.kernel.state.accepted_ref import (
    AcceptedRef,
    ParentArtifactRef,
    validate_pointer,
)
from arw.kernel.state.experiment_context import ComparisonContext
from arw.kernel.state.models import Sha256, StrictModel

MAX_INTEGER = 10**128 - 1
EVALUATOR_VERSION = "arw.rational.v1"


class RationalExact(StrictModel):
    numerator: int = Field(ge=-MAX_INTEGER, le=MAX_INTEGER)
    denominator: int = Field(ge=1, le=MAX_INTEGER)

    @model_validator(mode="after")
    def canonical(self):
        if math.gcd(self.numerator, self.denominator) != 1:
            raise ValueError("rational must be reduced with a positive denominator")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> RationalExact:
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


ONE = RationalExact(numerator=1, denominator=1)
Column = Annotated[str, Field(min_length=1, max_length=128)]


class AllRows(StrictModel):
    kind: Literal["all"] = "all"


class RowIds(StrictModel):
    kind: Literal["ids"] = "ids"
    ids: tuple[Column, ...] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def stable_set(self):
        if tuple(sorted(set(self.ids))) != self.ids:
            raise ValueError("row IDs must be unique and sorted")
        return self


class RowPredicate(StrictModel):
    kind: Literal["predicate"] = "predicate"
    column: Column
    op: Literal["eq", "ne", "lt", "le", "gt", "ge"]
    value: str = Field(max_length=256)


RowSet = Annotated[AllRows | RowIds | RowPredicate, Field(discriminator="kind")]


class ScalarJson(StrictModel):
    kind: Literal["scalar_json"] = "scalar_json"
    ref: AcceptedRef
    json_pointer: str = Field(default="", max_length=2048)
    unit: Column
    scale: RationalExact = ONE
    context: ComparisonContext

    _pointer = field_validator("json_pointer")(validate_pointer)


class CsvSelection(StrictModel):
    kind: Literal["csv_selection"] = "csv_selection"
    ref: ParentArtifactRef
    columns: tuple[Column, ...] = Field(min_length=1, max_length=32)
    row_id_column: Column
    row_set: RowSet = AllRows()
    group_by: tuple[Column, ...] = Field(default=(), max_length=8)
    missing_policy: Literal["reject", "exclude"] = "reject"
    context: ComparisonContext
    unit: Column
    scale: RationalExact = ONE

    @model_validator(mode="after")
    def distinct_columns(self):
        if len(set(self.columns)) != len(self.columns) or len(
            set(self.group_by)
        ) != len(self.group_by):
            raise ValueError("duplicate CSV columns or grouping keys")
        return self


Operand = Annotated[ScalarJson | CsvSelection, Field(discriminator="kind")]


class DerivationRef(StrictModel):
    kind: Literal["derivation_ref"] = "derivation_ref"
    derivation_id: Sha256


class NumericExpression(StrictModel):
    schema_version: Literal["arw.numeric-expression.v1"] = "arw.numeric-expression.v1"
    op: Literal[
        "value",
        "diff",
        "ratio",
        "pct_point_diff",
        "relative_change",
        "count",
        "sum",
        "mean",
        "median",
        "min",
        "max",
    ]
    args: tuple[
        Annotated[
            ScalarJson | CsvSelection | DerivationRef, Field(discriminator="kind")
        ],
        ...,
    ] = Field(min_length=1, max_length=32)


class DerivationRequest(StrictModel):
    schema_version: Literal["arw.numeric-request.v1"] = "arw.numeric-request.v1"
    expr: NumericExpression
    context: ComparisonContext
    evaluator_version: str = Field(
        default=EVALUATOR_VERSION, min_length=1, max_length=64
    )


NumericStatus = Literal[
    "exact", "undefined", "context_mismatch", "out_of_domain", "unsupported"
]


class NumericGroup(StrictModel):
    key: tuple[str, ...]
    exact: RationalExact
    row_ids: tuple[str, ...]


class Derivation(StrictModel):
    schema_version: Literal["arw.numeric-derivation.v1"] = "arw.numeric-derivation.v1"
    derivation_id: Sha256
    request: DerivationRequest
    status: NumericStatus
    exact: RationalExact | None = None
    groups: tuple[NumericGroup, ...] = ()
    values: tuple[RationalExact, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "exact":
            if self.exact is None and not self.groups and not self.values:
                raise ValueError("exact outcome requires exact values")
        elif self.exact is not None or self.groups or self.values:
            raise ValueError("failed outcomes cannot carry exact values")
        return self


class NumericPresentation(StrictModel):
    derivation_id: Sha256
    decimals: int = Field(ge=0, le=18)
    rounding_mode: Literal["ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_DOWN"]
    unit_suffix: str = Field(default="", max_length=64)
    scale: RationalExact = ONE


def numeric_core_schema_documents() -> dict[str, dict]:
    documents = {}
    for name, model in (
        ("numeric-request.schema.json", DerivationRequest),
        ("numeric-derivation.schema.json", Derivation),
        ("numeric-presentation.schema.json", NumericPresentation),
    ):
        document = model.model_json_schema()
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = document
    return documents

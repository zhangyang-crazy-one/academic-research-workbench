"""Existing exact comparison envelope, shared without importing evaluators."""

from typing import Annotated

from pydantic import StringConstraints

from arw.kernel.state.models import StrictModel

Label = Annotated[str, StringConstraints(min_length=1, max_length=256)]
ShortLabel = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Unit = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class ComparisonContext(StrictModel):
    """Everything that must agree before two values may be compared."""

    metric_definition: Label
    unit: Unit
    dataset: Label
    split: ShortLabel
    evaluation_condition: Label

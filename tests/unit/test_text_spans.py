"""Original writing receipt bytes survive pure kernel algorithm extraction."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from arw_writing import diagnostics, preservation

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.state import text_spans

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/text-spans/legacy-byte-projection.json"


def test_old_imports_reexport_the_same_pure_objects():
    for name in ("SENTENCE_SEPARATOR", "sentence_spans", "sentences"):
        assert getattr(diagnostics, name) is getattr(text_spans, name)
    for name in (
        "PATTERNS",
        "CITATION_BINDINGS_VERSION",
        "_indexed_bindings",
        "_legacy_bindings",
        "validate_citation_bindings",
        "sentence_spans",
        "sentences",
    ):
        assert getattr(preservation, name) is getattr(text_spans, name)


def test_original_canonical_projection_bytes_are_identical():
    fixture = json.loads(FIXTURE.read_bytes())
    records = []
    for original in fixture["records"]:
        source, candidate = original["source"], original["candidate"]
        texts = (("source", source), ("candidate", candidate))
        record = {
            "source": source,
            "candidate": candidate,
            "spans": {
                side: list(text_spans.sentence_spans(text)) for side, text in texts
            },
            "sentences": {side: text_spans.sentences(text) for side, text in texts},
            "indexed": {
                side: text_spans._indexed_bindings(text) for side, text in texts
            },
            "legacy": {side: text_spans._legacy_bindings(text) for side, text in texts},
            "diagnostics": {side: diagnostics.diagnose(text) for side, text in texts},
            "verification": preservation.verify(source, candidate, (), ()),
        }
        text_spans.validate_citation_bindings(record["verification"], source, candidate)
        text_spans.validate_citation_bindings(
            {"citation_bindings": record["legacy"]}, source, candidate
        )
        records.append(record)
    assert (
        canonical_json_bytes({"baseline": fixture["baseline"], "records": records})
        == FIXTURE.read_bytes()
    )


def test_repeated_utf8_occurrences_preserve_distinct_byte_offsets():
    source = "  中文证据 [@Alpha]。重复证据 [@Alpha]。重复证据 [@Alpha]！"
    result = text_spans._indexed_bindings(source)
    assert len(result["assertions"]) == 3
    assert [row["assertion"] for row in result["bindings"]] == [0, 1, 2]
    assert result["assertions"][1]["sha256"] == result["assertions"][2]["sha256"]
    assert result["assertions"][1]["offset"] != result["assertions"][2]["offset"]
    first = result["assertions"][0]
    assert first["offset"] == 2
    assert first["length"] == len("中文证据 [@Alpha]".encode())


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean_offset",
        "swapped_occurrence",
        "missing_hash",
        "new_version",
        "extra_fields",
    ],
)
def test_original_binding_validator_strength_remains(mutation):
    source = "证据 [@A]。Another statement [2]."
    receipt = preservation.verify(source, source, (), ())
    altered = copy.deepcopy(receipt)
    binding = altered["citation_bindings"]
    if mutation == "boolean_offset":
        binding["source"]["assertions"][0]["offset"] = False
    elif mutation == "swapped_occurrence":
        binding["source"]["bindings"][0]["assertion"] = 1
    elif mutation == "missing_hash":
        del binding["source"]["assertions"][0]["sha256"]
    elif mutation == "new_version":
        binding["version"] = "arw.writing-citation-bindings.v3"
    else:
        binding["source"]["extra"] = True
    with pytest.raises((ValueError, TypeError)):
        text_spans.validate_citation_bindings(altered, source, source)

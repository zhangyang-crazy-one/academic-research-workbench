"""Exact drift rejection plus explicit contextual review, never lexical PASS."""

import re
from collections import Counter

from arw.kernel.core.canonical import sha256_hex

from .diagnostics import sentence_spans, sentences

PATTERNS = {
    "numbers_units": r"\b\d+(?:[.,]\d+)*(?:\s*(?:%|ms\b|kg\b|cm\b|mm\b|mg\b|mL\b|Hz\b|s\b))?",
    "equations": r"\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)",
    "citations": r"\[@[^\]]+\]|\[\d+(?:\s*[-,]\s*\d+)*\]|\\cite\w*\{[^}]+\}",
    "quoted_material": r'"[^"\n]+"|“[^”]+”|「[^」]+」',
    "hedging": r"\b(?:may|might|could|possibly|perhaps|suggests?|likely|unlikely)\b|可能|或许|提示|倾向于",
    "negation": r"\b(?:not|no|never|neither|without|cannot)\b|未能|不能|没有|并非",
    "comparatives": r"\b(?:higher|lower|more|less|greater|fewer|better|worse|increase[sd]?|decrease[sd]?)\b|高于|低于|优于|劣于|增加|降低",
    "experimental_conditions": r"\bin (?:our|these|the) experiments\b|\bunder\b|\bif\b|\bonly\b|\bgenerally\b|在本实验中|在我们的实验中|仅在|如果|普遍",
}
CONTEXT = (
    "claims_logical_direction",
    "citation_scope",
    "hedging_context",
    "negation_scope",
    "comparative_direction",
    "experimental_scope",
    "method_dataset_identity",
    "quoted_meaning",
)
CITATION_BINDINGS_VERSION = "arw.writing-citation-bindings.v2"


def _indexed_bindings(text):
    """Index cited sentence occurrences by UTF-8 byte span, without copying text."""
    assertions, bindings = [], []
    char_cursor = byte_cursor = 0
    for start, end in sentence_spans(text):
        byte_cursor += len(text[char_cursor:start].encode("utf-8"))
        sentence = text[start:end]
        encoded = sentence.encode("utf-8")
        citations = re.findall(PATTERNS["citations"], sentence)
        if citations:
            index = len(assertions)
            assertions.append(
                {
                    "offset": byte_cursor,
                    "length": len(encoded),
                    "sha256": sha256_hex(encoded),
                }
            )
            bindings.extend(
                {"citation": citation, "assertion": index} for citation in citations
            )
        byte_cursor += len(encoded)
        char_cursor = end
    return {"assertions": assertions, "bindings": bindings}


def _legacy_bindings(text):
    return [
        {"citation": citation, "assertion": sentence}
        for sentence in sentences(text)
        for citation in re.findall(PATTERNS["citations"], sentence)
    ]


def validate_citation_bindings(verification, source, candidate):
    """Validate v2 byte scopes or replay the exact legacy sentence semantics."""
    if not isinstance(verification, dict):
        raise TypeError("writing verification is invalid")
    value = verification.get("citation_bindings")
    if not isinstance(value, dict):
        raise TypeError("citation bindings are missing")
    texts = {"source": source, "candidate": candidate}
    if value.get("version") == CITATION_BINDINGS_VERSION:
        if set(value) != {"version", *texts}:
            raise ValueError("citation binding fields are invalid")
        for side, text in texts.items():
            actual = value[side]
            if not isinstance(actual, dict) or set(actual) != {
                "assertions",
                "bindings",
            }:
                raise ValueError(f"{side} citation binding table is invalid")
            if not isinstance(actual["assertions"], list) or not isinstance(
                actual["bindings"], list
            ):
                raise TypeError(f"{side} citation binding rows are invalid")
            if any(
                not isinstance(row, dict)
                or type(row.get("offset")) is not int
                or type(row.get("length")) is not int
                or set(row) != {"offset", "length", "sha256"}
                for row in actual["assertions"]
            ) or any(
                not isinstance(row, dict)
                or type(row.get("assertion")) is not int
                or set(row) != {"citation", "assertion"}
                for row in actual["bindings"]
            ):
                raise ValueError(f"{side} citation binding row is invalid")
            if actual != _indexed_bindings(text):
                raise ValueError(f"{side} citation scope or digest differs from text")
    elif "version" not in value:
        if set(value) != set(texts):
            raise ValueError("legacy citation binding fields are invalid")
        for side, text in texts.items():
            if value[side] != _legacy_bindings(text):
                raise ValueError(f"{side} legacy citation scope differs from text")
    else:
        raise ValueError("unsupported citation binding version")


def resolve_citation_bindings(verification, source, candidate):
    """Return legacy-shaped scoped assertions for either retained wire format."""
    validate_citation_bindings(verification, source, candidate)
    return {
        side: _legacy_bindings(text)
        for side, text in (("source", source), ("candidate", candidate))
    }


def verify(source, candidate, protected_terms, protected_spans):
    findings = []
    for dimension, pattern in PATTERNS.items():
        a, b = (
            re.findall(pattern, source, re.IGNORECASE),
            re.findall(pattern, candidate, re.IGNORECASE),
        )
        if Counter(a) != Counter(b):
            findings.append(
                {
                    "dimension": dimension,
                    "status": "reject",
                    "source_spans": a,
                    "candidate_spans": b,
                    "action": "Restore protected content/qualifiers before proposing again",
                }
            )
    for dimension, values in (
        ("method_dataset_terms", protected_terms),
        ("protected_spans", protected_spans),
    ):
        for value in values:
            if value not in source or source.count(value) != candidate.count(value):
                findings.append(
                    {
                        "dimension": dimension,
                        "status": "reject",
                        "source_spans": [value],
                        "candidate_spans": [],
                        "action": "Restore every exact protected occurrence",
                    }
                )
    # Identity of citation tokens alone is insufficient. Bind each token to
    # its exact sentence span in the retained source/candidate text.
    # Whole-text review scope is referenced by digest; the receipt already
    # carries the source and candidate once, so they are not copied per
    # dimension.
    source_sha256 = sha256_hex(source.encode("utf-8"))
    candidate_sha256 = sha256_hex(candidate.encode("utf-8"))
    for dimension in CONTEXT:
        findings.append(
            {
                "dimension": dimension,
                "status": "human_review",
                "scope": "whole_text",
                "source_sha256": source_sha256,
                "candidate_sha256": candidate_sha256,
                "action": "Reviewer must compare meaning, scope and evidence against the author target",
            }
        )
    return {
        "version": "arw.writing-preservation.v2",
        "disposition": "reject"
        if any(f["status"] == "reject" for f in findings)
        else "human_review",
        "findings": findings,
        "citation_bindings": {
            "version": CITATION_BINDINGS_VERSION,
            "source": _indexed_bindings(source),
            "candidate": _indexed_bindings(candidate),
        },
        "unresolved_dimensions": list(CONTEXT),
        "semantic_equivalence_proven": False,
    }

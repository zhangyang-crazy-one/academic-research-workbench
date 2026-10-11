"""Exact drift rejection plus explicit contextual review, never lexical PASS."""

import re
from collections import Counter

from arw.kernel.core.canonical import sha256_hex

# Legacy callers keep these same objects through the old module path.
from arw.kernel.state.text_spans import (
    CITATION_BINDINGS_VERSION,
    PATTERNS,
    _indexed_bindings,
    _legacy_bindings,
    validate_citation_bindings,
)

from .diagnostics import sentence_spans, sentences  # noqa: F401

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

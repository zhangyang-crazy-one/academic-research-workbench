"""Exact drift rejection plus explicit contextual review, never lexical PASS."""

import re
from collections import Counter

from .diagnostics import sentences

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
    # Identity of citation tokens alone is insufficient. Retain the assertion.
    citation = PATTERNS["citations"]
    bindings = lambda text: [
        {"citation": c, "assertion": s}
        for s in sentences(text)
        for c in re.findall(citation, s)
    ]
    for dimension in CONTEXT:
        findings.append(
            {
                "dimension": dimension,
                "status": "human_review",
                "source_spans": [source],
                "candidate_spans": [candidate],
                "action": "Reviewer must compare meaning, scope and evidence against the author target",
            }
        )
    return {
        "version": "arw.writing-preservation.v1",
        "disposition": "reject"
        if any(f["status"] == "reject" for f in findings)
        else "human_review",
        "findings": findings,
        "citation_bindings": {
            "source": bindings(source),
            "candidate": bindings(candidate),
        },
        "unresolved_dimensions": list(CONTEXT),
        "semantic_equivalence_proven": False,
    }

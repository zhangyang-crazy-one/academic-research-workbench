"""Pinned surface metrics for English/Chinese; no authorship inference."""

import re
from collections import Counter
from statistics import pvariance

VERSION = "arw.writing-surface.en-zh.v1"
TOKEN = r"[A-Za-z]+(?:'[A-Za-z]+)?|[\u3400-\u9fff]|\d+(?:\.\d+)?"
CONNECTORS = r"\b(?:however|therefore|moreover|furthermore|additionally|thus|nevertheless)\b|然而|因此|此外|而且|但是|所以"


def sentences(text):
    # Decimal dots are retained. This is a surface segmentation, not a parser.
    return [
        s.strip()
        for s in re.split(r"(?<!\d)[.!?]+\s*|[。！？]+\s*|\n\s*\n", text)
        if s.strip()
    ]


def tokens(text):
    return re.findall(TOKEN, text.lower())


def diagnose(text):
    words = tokens(text)
    sents = sentences(text)
    lengths = [len(tokens(s)) for s in sents]
    paragraphs = [len(tokens(p)) for p in re.split(r"\n\s*\n", text) if p.strip()]
    starts = [tuple(tokens(s)[:2]) for s in sents]
    ngrams = list(zip(words, words[1:], words[2:]))
    freq = Counter(words)
    return {
        "version": VERSION,
        "label": "Surface diagnostics, not authorship proof or semantic equivalence",
        "language_support": "English words + Chinese characters; other scripts unsupported",
        "status": "available" if words else "unsupported",
        "token_count": len(words),
        "sentence_count": len(sents),
        "sentence_lengths": lengths,
        "sentence_length_variance": round(pvariance(lengths), 6) if lengths else None,
        "clause_count": len(re.findall(r"[,;，；]", text)) + len(sents),
        "lexical_diversity": round(len(freq) / len(words), 6) if words else None,
        "lexical_repetition": len(words) - len(freq),
        "connector_count": len(re.findall(CONNECTORS, text, re.IGNORECASE)),
        "syntactic_template_proxy_repetition": len(starts) - len(set(starts)),
        "syntactic_template_definition": "repeated first-two-token surface pattern; no syntactic parsing",
        "paragraph_lengths": paragraphs,
        "paragraph_length_variance": round(pvariance(paragraphs), 6)
        if paragraphs
        else None,
        "trigram_repetition": len(ngrams) - len(set(ngrams)),
        "token_distribution": dict(sorted(freq.items())),
        "short_text_caution": len(words) < 50,
    }


CONTROL_METRICS = {
    "sentence_structure": "clause_count",
    "length_rhythm": "sentence_length_variance",
    "connectors": "connector_count",
    "lexical_repetition": "lexical_repetition",
    "syntactic_repetition": "syntactic_template_proxy_repetition",
    "paragraph_cadence": "paragraph_lengths",
}


def effects(before, after, controls):
    result = {}
    for control, direction in controls.items():
        metric = CONTROL_METRICS[control]
        a, b = before[metric], after[metric]
        met = (
            (
                a != b
                if direction == "change"
                else b < a
                if direction == "decrease"
                else b > a
            )
            if a is not None and b is not None
            else False
        )
        result[control] = {
            "metric": metric,
            "requested": direction,
            "before": a,
            "after": b,
            "status": "effective" if met else "ineffective",
        }
    return result

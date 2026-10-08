"""Deterministic producer for three original synthetic CPU response tables."""

from __future__ import annotations

import hashlib
from itertools import product

CONFIGS = tuple("".join(map(str, bits)) for bits in product((0, 1), repeat=4))

# These fixtures are original ARW arithmetic surrogates, not benchmark timings.
# Coefficients and seeds are deliberately absent from agent-facing task input.
FORMULAS = {
    "cpu-batch-v1": {
        "seed": 1103,
        "intercept": 72,
        "main": (5, -3, 2, 1),
        "pairs": (4, -2, 1, 3, -1, 2),
        "triple": 1,
    },
    "cpu-graph-v1": {
        "seed": 2207,
        "intercept": 64,
        "main": (-2, 4, 3, -1),
        "pairs": (-3, 2, 1, 4, -2, -3),
        "triple": -2,
    },
    "cpu-buffer-v1": {
        "seed": 3301,
        "intercept": 81,
        "main": (3, 1, -4, 2),
        "pairs": (2, -3, 4, -1, 3, -2),
        "triple": 2,
    },
}


def response(task_id: str, config: str) -> float:
    """Stable arithmetic CPU-workload surrogate, rounded to one decimal."""
    formula = FORMULAS[task_id]
    bits = tuple(1 if bit == "1" else -1 for bit in config)
    pairs = tuple(bits[i] * bits[j] for i in range(4) for j in range(i + 1, 4))
    jitter_hash = hashlib.sha256(f"{formula['seed']}:{config}".encode()).digest()
    jitter = (int.from_bytes(jitter_hash[:2], "big") % 7 - 3) / 10
    value = (
        formula["intercept"]
        + sum(coefficient * bit for coefficient, bit in zip(formula["main"], bits))
        + sum(coefficient * pair for coefficient, pair in zip(formula["pairs"], pairs))
        + formula["triple"] * bits[0] * bits[1] * bits[2]
        + jitter
    )
    return round(value, 1)


def reference_rows(task_id: str) -> list[dict]:
    return [
        {"config": config, "value": response(task_id, config)} for config in CONFIGS
    ]

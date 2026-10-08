"""Original standard-library deferred-acceptance implementation.

Gale and Shapley (1962), Theorem 1 proof, printed pages 12–13. This module
contains no text or code copied from the paper or another implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import deque

MAX_INPUT_BYTES = 60 * 1024
MAX_PARTICIPANTS = 64
MAX_OUTPUT_BYTES = 32 * 1024
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")


class MethodError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise MethodError("duplicate_json_key")
        value[key] = item
    return value


def parse(raw: bytes):
    if len(raw) > MAX_INPUT_BYTES:
        raise MethodError("input_budget_exceeded")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                MethodError("nonfinite_value")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MethodError("invalid_json") from error


def validate(value):
    if not isinstance(value, dict) or set(value) != {"proposers", "receivers"}:
        raise MethodError("invalid_input_shape")
    proposers, receivers = value["proposers"], value["receivers"]
    if not isinstance(proposers, dict) or not isinstance(receivers, dict):
        raise MethodError("invalid_type")
    size = len(proposers)
    if size < 1 or size > MAX_PARTICIPANTS or len(receivers) != size:
        raise MethodError("participant_range")
    if any(
        not isinstance(name, str) or NAME.fullmatch(name) is None
        for name in (*proposers, *receivers)
    ):
        raise MethodError("invalid_name")
    for owners, others in ((proposers, set(receivers)), (receivers, set(proposers))):
        for ranking in owners.values():
            if not isinstance(ranking, list) or len(ranking) != size:
                raise MethodError("invalid_ranking")
            if any(not isinstance(name, str) for name in ranking):
                raise MethodError("invalid_type")
            if set(ranking) != others or len(set(ranking)) != size:
                raise MethodError("invalid_ranking")
    return proposers, receivers


def solve(value):
    proposers, receivers = validate(value)
    size = len(proposers)
    priorities = {
        receiver: {name: rank for rank, name in enumerate(ranking)}
        for receiver, ranking in receivers.items()
    }
    free = deque(sorted(proposers))
    next_choice = {name: 0 for name in proposers}
    held = {}
    proposals = 0
    while free:
        proposer = free.popleft()
        index = next_choice[proposer]
        if index >= size:
            raise MethodError("proposal_budget_exceeded")
        receiver = proposers[proposer][index]
        next_choice[proposer] = index + 1
        proposals += 1
        if proposals > size * size:
            raise MethodError("proposal_budget_exceeded")
        current = held.get(receiver)
        if current is None:
            held[receiver] = proposer
        elif priorities[receiver][proposer] < priorities[receiver][current]:
            held[receiver] = proposer
            free.append(current)
        else:
            free.append(proposer)
    matching = {proposer: receiver for receiver, proposer in held.items()}
    if len(matching) != size:
        raise MethodError("incomplete_matching")
    # Independently check that no proposer and receiver prefer one another.
    for proposer, ranking in proposers.items():
        for receiver in ranking[: ranking.index(matching[proposer])]:
            other = held[receiver]
            if priorities[receiver][proposer] < priorities[receiver][other]:
                raise MethodError("unstable_matching")
    return {
        "matching": dict(sorted(matching.items())),
        "proposal_count": proposals,
        "stable_verified": True,
    }


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    try:
        result = {"status": "executed", "result": solve(parse(raw))}
    except MethodError as error:
        result = {"status": "failed", "reason_code": error.code}
    output = canonical(result)
    if len(output) > MAX_OUTPUT_BYTES:
        output = canonical(
            {"status": "failed", "reason_code": "output_budget_exceeded"}
        )
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import copy
from itertools import islice, permutations

from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from tests.integration.test_graph_projection import _fixture_records


def test_projection_replay_is_order_independent() -> None:
    records = _fixture_records()
    baseline = project_canonical_records(records, ledger_watermark=10, ledger_head_sha256="a" * 64)
    for order in islice(permutations(range(10)), 0, 120):
        projection = project_canonical_records(
            [copy.deepcopy(records[index]) for index in order],
            ledger_watermark=10,
            ledger_head_sha256="a" * 64,
        )
        assert projection.canonical_bytes() == baseline.canonical_bytes()


def test_graph_generation_replay_reuses_same_receipt(tmp_path) -> None:
    store = GraphStore(tmp_path / "control", "research-root")
    projection = project_canonical_records(_fixture_records(), ledger_watermark=10, ledger_head_sha256="a" * 64)
    first = store.build_full(projection)
    replay = store.build_full(projection)
    assert replay == first

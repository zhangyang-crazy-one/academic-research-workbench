"""Count real CSV row visits, index reads, decoding and accepted-run replay."""

from dataclasses import replace

import pytest

from arw.kernel.ledger import accepted_refs
from arw.kernel.policy import numeric_core
from arw.kernel.state.numeric_core import RowIds
from tests.unit.test_accepted_refs import accepted_fixture
from tests.unit.test_numeric_core import request, selection


@pytest.mark.parametrize(
    "rows,queries", [(1000, 10), (1000, 100), (1000, 1000), (10, 100), (100, 100)]
)
def test_cached_row_id_work_tracks_source_rows_plus_selected_rows(
    tmp_path, monkeypatch, rows, queries
):
    raw = b"id,score\n" + b"".join(f"r{i:04d},{i}\n".encode() for i in range(rows))
    _, context, ref, _ = accepted_fixture(tmp_path, raw)
    counts = {"parsed": 0, "table_visits": 0, "lookups": 0, "decoded": 0, "replays": 0}
    reader_type = numeric_core.csv.DictReader

    class Reader(reader_type):
        def __next__(self):
            row = super().__next__()
            counts["parsed"] += 1
            return row

    class TableRows(tuple):
        def __iter__(self):
            for row in super().__iter__():
                counts["table_visits"] += 1
                yield row

    class Index(dict):
        def __getitem__(self, key):
            counts["lookups"] += 1
            return super().__getitem__(key)

    original_scan, original_io = numeric_core._scan_csv_rows, numeric_core.io.StringIO
    original_replay = accepted_refs.replay_run

    def scan(*args):
        table = original_scan(*args)
        return replace(
            table, rows=TableRows(table.rows), rows_by_id=Index(table.rows_by_id)
        )

    def decode(*args, **kwargs):
        counts["decoded"] += 1
        return original_io(*args, **kwargs)

    def replay(*args, **kwargs):
        counts["replays"] += 1
        return original_replay(*args, **kwargs)

    monkeypatch.setattr(numeric_core.csv, "DictReader", Reader)
    monkeypatch.setattr(numeric_core.io, "StringIO", decode)
    monkeypatch.setattr(numeric_core, "_scan_csv_rows", scan)
    monkeypatch.setattr(accepted_refs, "replay_run", replay)
    cache = accepted_refs.ResolutionCache()
    requests, results = [], []
    for i in range(queries):
        req = request(
            "value", selection(ref, row_set=RowIds(ids=(f"r{i % rows:04d}",)))
        )
        requests.append(req)
        results.append(numeric_core.evaluate_derivation(req, context, cache=cache))
        assert results[-1].status == "exact" and results[-1].exact.numerator == i % rows
    assert counts == {
        "parsed": rows,
        "table_visits": 0,
        "lookups": queries,
        "decoded": 1,
        "replays": 1,
    }
    for i in {0, queries // 2, queries - 1}:
        assert numeric_core.evaluate_derivation(requests[i], context) == results[i]


def test_cached_and_uncached_whole_plot_have_identical_values_ids_and_svg(
    tmp_path, monkeypatch
):
    from arw_research_artifact.plot_policy import compile_plot
    from arw_research_artifact.plot_renderer import PlotRenderer

    from arw.kernel.state.result_plot import PlotEncoding, PlotLayer
    from tests.integration.test_result_plots import plot

    raw = b"id,score,category\n" + b"".join(
        f"r{i},0.{i % 10},A\n".encode() for i in range(50)
    )
    _, context, ref, _ = accepted_fixture(tmp_path, raw)
    ir = plot(
        (
            PlotLayer(
                layer_id="layer.points",
                role="observation",
                mark="point",
                source=selection(ref),
                encoding=PlotEncoding(x="category", y="score"),
            ),
        )
    )
    cached = compile_plot(ir, context)

    class NoCsvCache(accepted_refs.ResolutionCache):
        def csv_rows(self, ref, row_id_column, scan, *, context):
            return scan()

    monkeypatch.setattr(accepted_refs, "ResolutionCache", NoCsvCache)
    uncached = compile_plot(ir, context)
    assert cached == uncached
    assert PlotRenderer().render(cached) == PlotRenderer().render(uncached)

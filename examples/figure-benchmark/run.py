"""Execute frozen public tasks through real ARW artifacts, then optional pixels.

Run with the project venv and extension/src on PYTHONPATH. Output must be fresh.
This program produces review evidence, never independent human acceptance.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.accepted_refs import ResolutionContext, to_accepted_ref
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import (
    InitRunRequest,
    ArtifactAcceptanceRequest,
    RuntimeCommandRequest,
)
from arw.kernel.state.research_artifact import ResearchBinding, ValidationPolicy
from arw.kernel.state.numeric_core import (
    ComparisonContext,
    CsvSelection,
    ScalarJson,
    NumericExpression,
    DerivationRequest,
)
from arw.kernel.state.result_plot import (
    ResultPlotIR,
    PlotLayer,
    PlotDatum,
    PlotEncoding,
    PlotScales,
    PlotScale,
    PlotUncertainty,
)
from arw_research_artifact.composition import CompositionRenderer
from arw_research_artifact.service import ResearchArtifactService
from arw_research_artifact.plot_policy import compile_plot
from arw_research_artifact.plot_renderer import PlotRenderer

HERE = Path(__file__).resolve().parent


def load_tasks(directory=HERE):
    raw = (directory / "tasks.json").read_bytes()
    expected = (directory / "tasks.sha256").read_text().split()[0]
    if sha256_hex(raw) != expected:
        raise ValueError("frozen_task_digest_mismatch")
    return json.loads(raw), expected


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def request(root, number):
    replay = replay_run(root)
    return RuntimeCommandRequest(
        schema_version="1.0.0",
        run_id=replay.run_id,
        expected_revision=replay.revision,
        occurred_at="2026-10-16T00:00:00Z",
        actor_id="parent.benchmark",
        actor_role="parent_control_plane",
        event_id="evt-" + str(uuid.UUID(int=number, version=4)),
        command_id="cmd-" + str(uuid.UUID(int=number, version=4)),
    )


def accept(root, name, path, number, context, media="application/json"):
    replay = replay_run(root)
    command = ArtifactAcceptanceRequest.model_validate(
        {
            **request(root, number).model_dump(mode="json"),
            "artifact_id": name,
            "artifact_kind": "public-synthetic-evidence",
            "media_type": media,
            "content_path": path,
            "content_sha256": sha256_hex((root / path).read_bytes()),
            "base_revision": replay.revision,
            "consumed_sha256": [replay.last_event_sha256],
        }
    )
    outcome = RuntimeCommandService(root).accept_artifact(command)
    if not outcome.accepted:
        raise RuntimeError("canonical_source_acceptance_failed")
    event = outcome.event
    binding = ResearchBinding(
        binding_id="binding." + name,
        artifact_id=name,
        sha256=event.payload.artifact_sha256,
        ledger_event_id=event.event_id,
        ledger_event_sha256=event.event_sha256,
        json_pointer="",
    )
    resolution = to_accepted_ref(binding, context)
    # CSV is an AcceptedRef source; ResearchBinding intentionally requires JSON.
    if media == "text/csv":
        from arw.kernel.state.submission import SubmissionArtifactReference

        resolution = to_accepted_ref(
            SubmissionArtifactReference(
                artifact_id=name,
                manifest_sha256=event.payload.manifest_sha256,
                content_sha256=event.payload.artifact_sha256,
                accepting_event_id=event.event_id,
            ),
            context,
        )
    if resolution.status != "resolved":
        raise RuntimeError("canonical_ref_unresolved:" + str(resolution.reason))
    return event, binding, resolution.ref


def setup(output, tasks):
    root = output / "run"
    root.mkdir()
    material = copy.deepcopy(tasks)
    loop = tasks["loop"]
    for kind in ("control", "data"):
        material["loop_" + kind] = {
            **loop,
            "relations": [r for r in loop["relations"] if r["relation_type"] == kind],
        }
    material["panel_derivation"] = (
        "Partition supplied loop relations by explicit type; retain all entities, states, directions and labels unchanged."
    )
    (root / "source.json").write_bytes(canonical_json_bytes(material))
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": "run-00000000-0000-4000-8000-000000000153",
                "occurred_at": "2026-10-16T00:00:00Z",
                "immutable_input": {
                    "path": "source.json",
                    "sha256": sha256_hex((root / "source.json").read_bytes()),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000001",
                "command_id": "cmd-00000000-0000-4000-8000-000000000001",
                "actor_id": "parent.benchmark",
            }
        ),
    )
    context = ResolutionContext("project.public-figures", (root,))
    event, binding, ref = accept(root, "evidence.synthetic", "source.json", 2, context)
    csv = "id,score,category,series\n" + "".join(
        f"{name}.{i},{value},toy,{name}\n"
        for name in ("baseline", "proposed")
        for i, value in enumerate(tasks["values"][name])
    )
    (root / "raw.csv").write_text(csv)
    _, _, csvref = accept(root, "evidence.raw", "raw.csv", 3, context, media="text/csv")
    return root, context, material, event, binding, ref, csvref


def numeric_plot(ref, csvref):
    cc = ComparisonContext(
        metric_definition="toy score",
        unit="ratio",
        dataset="public synthetic observations",
        split="toy",
        evaluation_condition="fixed supplied values",
    )

    def value(pointer):
        return DerivationRequest(
            expr=NumericExpression(
                op="value",
                args=(
                    ScalarJson(ref=ref, json_pointer=pointer, unit="ratio", context=cc),
                ),
            ),
            context=cc,
        )

    source = CsvSelection(
        ref=csvref, columns=("score",), row_id_column="id", unit="ratio", context=cc
    )
    observed = PlotLayer(
        layer_id="raw.points",
        role="observation",
        mark="strip",
        jitter_axis="x",
        source=source,
        encoding=PlotEncoding(x="category", y="score", series="series"),
    )
    aggregate = PlotLayer(
        layer_id="means",
        role="aggregate",
        mark="point",
        encoding=PlotEncoding(x="category", y="score", series="series"),
        data=tuple(
            PlotDatum(
                datum_id="mean." + s,
                category="toy",
                series=s,
                y=value("/values/mean/" + s),
            )
            for s in ("baseline", "proposed")
        ),
    )
    from arw.kernel.state.numeric_core import RowPredicate

    n_source = DerivationRequest(
        expr=NumericExpression(
            op="count",
            args=(
                source.model_copy(
                    update={
                        "row_set": RowPredicate(
                            column="series", op="eq", value="baseline"
                        )
                    }
                ),
            ),
        ),
        context=cc,
    )
    uncertainty = PlotUncertainty(
        interval_type="range",
        sampling_unit="synthetic row",
        n_source=n_source,
        missing_policy="reject",
        method="Frozen precomputed min/max toy range, not confidence interval",
        assumptions=("All values are synthetic; no population inference.",),
        calculation_source=ref,
    )
    interval = PlotLayer(
        layer_id="ranges",
        role="interval",
        mark="rule",
        encoding=PlotEncoding(x="category", y="score", series="series"),
        uncertainty=uncertainty,
        data=tuple(
            PlotDatum(
                datum_id="range." + s,
                category="toy",
                series=s,
                lower=value("/values/lower/" + s),
                upper=value("/values/upper/" + s),
            )
            for s in ("baseline", "proposed")
        ),
    )
    return ResultPlotIR(
        artifact_id="figure.exact",
        revision=1,
        title="Synthetic close estimates",
        author_target="Compare supplied raw points, fixed means and precomputed ranges.",
        scales=PlotScales(
            x=PlotScale(type="band", unit="synthetic condition", categories=("toy",)),
            y=PlotScale(type="linear", unit="ratio"),
        ),
        layers=(observed, interval, aggregate),
        caption="Synthetic raw points jittered horizontally; central means and precomputed ranges, not confidence intervals.",
        renderer_hints=PlotRenderer().identity,
        validation_policy=policy(),
    )


def policy():
    return ValidationPolicy.model_validate_json(
        '{"schema":"REQUIRED","provenance":"REQUIRED","semantic":"REQUIRED","render":"REQUIRED","visual":"OPTIONAL"}'
    )


def composition(
    service, task, candidate, material, binding, child_event, child_receipt
):
    keys = {
        "loop": ["sequence", "loop_control", "loop_data"],
        "mixed": ["sequence", "mechanism", "accepted"],
        "stress": ["stress", "sequence"],
    }[task["id"]]
    if candidate == "single":
        candidate = "column"
    rows, cols = {
        "row": ([1], [1] * len(keys)),
        "column": (
            [1, 2, 3]
            if task["id"] == "mixed"
            else [1, 3, 3]
            if len(keys) == 3
            else [1, 1],
            [1],
        ),
        "grid": ([1, 2], [1, 1]),
    }[candidate]
    panels = []
    renderer = CompositionRenderer().identity.model_dump(mode="json")
    titles = {
        "sequence": "Observed source",
        "loop_control": "Conditional control loop",
        "loop_data": "Distinct data flow",
        "mechanism": "Bound representation",
        "accepted": "Accepted exact evidence",
        "stress": "中文 / English + math stress",
    }
    for i, key in enumerate(keys):
        if candidate == "row":
            position = {"row": 0, "column": i}
        elif candidate == "column":
            position = {"row": i, "column": 0}
        elif i == 2:
            position = {"row": 1, "column": 0, "column_span": 2}
        else:
            position = {"row": 0, "column": i}
        content_binding = binding.model_copy(
            update={"binding_id": f"binding.{i}", "json_pointer": "/" + key}
        )
        if key == "accepted":
            value = child_receipt
            content_binding = ResearchBinding(
                binding_id=f"binding.{i}",
                artifact_id=child_event.payload.artifact_id,
                sha256=child_event.payload.artifact_sha256,
                ledger_event_id=child_event.event_id,
                ledger_event_sha256=child_event.event_sha256,
                json_pointer="",
            )
            kind = "accepted_v1"
            pin = child_receipt["renderer"]
        else:
            value = material[key]
            kind = value["kind"]
            pin = renderer
        panels.append(
            {
                "panel_id": f"panel.{i}",
                "role": "quantitative" if key == "accepted" else "schematic",
                "label": chr(97 + i),
                "title": titles[key],
                "reading_order": i + 1,
                "position": position,
                "content_kind": kind,
                "content_ref": content_binding.model_dump(mode="json"),
                "content_sha256": sha256_hex(canonical_json_bytes(value)),
                "renderer": pin,
            }
        )
    encodings = [
        {"semantic_id": n, "label": n.title(), "color": c, "shape": s, "line_style": d}
        for n, c, s, d in [
            ("sample", "#0072B2", "circle", "solid"),
            ("analysis", "#D55E00", "diamond", "dashed"),
            ("exit", "#009E73", "square", "dotted"),
        ]
    ]
    if task["id"] == "stress":
        encodings.extend(
            {
                "semantic_id": f"extra.{i}",
                "label": f"Legend {i}: 中文 long label",
                "color": "#222222",
                "shape": "circle",
                "line_style": "solid",
            }
            for i in range(2)
        )
    spec = {
        "artifact_kind": "figure_composition",
        "artifact_id": f"figure.{task['id']}.{candidate}",
        "revision": 1,
        "visual_argument": task["argument"],
        "width_mm": task["width_mm"],
        "height_mm": task["height_mm"],
        "panels": panels,
        "layout": {"kind": candidate, "row_ratios": rows, "column_ratios": cols},
        "encodings": encodings,
        "legend_ids": [e["semantic_id"] for e in encodings],
        "validation_policy": policy().model_dump(mode="json"),
    }
    return service.build(spec, run_root=None)


def rasterize(svg, png, task, profile, python="/usr/bin/python3"):
    try:
        proc = subprocess.run(
            [
                python,
                str(HERE / "rasterize.py"),
                str(svg),
                str(png),
                str(task["width_mm"]),
                str(task["height_mm"]),
                str(profile["dpi"]),
            ],
            text=True,
            capture_output=True,
            timeout=60,
        )
        if proc.returncode:
            return {"status": "unavailable", "reason": proc.stderr[-1500:]}
        return json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "reason": str(exc)}


def selection_reason(task, candidate, min_font, minimum):
    if task["id"] in {"exact", "stress"}:
        return "Single layout: frozen simple quantitative comparison or controlled stress task; no three-candidate exploration required. Independent review remains pending."
    if candidate == task["selected"]:
        return f"Producer preselection: full-width panels give the largest readable labels. Actual minimum {min_font:.2f} pt versus required {minimum:.2f} pt; any failure remains open. Human structural-choice confirmation pending."
    return f"Not selected by producer: parallel/grid organization reduces labels to {min_font:.2f} pt (required {minimum:.2f} pt) and increases relation-reading density. Facts are unchanged; human confirmation pending."


def review_binding(record):
    return sha256_hex(
        canonical_json_bytes(
            {k: record[k] for k in ("task_sha256", "ir_sha256", "svg_sha256", "pixels")}
        )
    )


def review_state(review, record):
    if review is None:
        return "pending"
    if review.get("binding_sha256") != review_binding(record):
        return "stale"
    if (
        not review.get("producer")
        or not review.get("reviewer")
        or review.get("producer") == review.get("reviewer")
        or review.get("role") != "human_nonproducer"
    ):
        return "invalid"
    if review.get("decision") not in {"accept", "revise", "reject"} or not review.get(
        "reason"
    ):
        return "incomplete"
    return review["decision"]


def run(output, python="/usr/bin/python3"):
    tasks, task_sha = load_tasks()
    output.mkdir(parents=True, exist_ok=False)
    root, context, material, event, binding, ref, csvref = setup(output, tasks)
    service = ResearchArtifactService()
    plot = numeric_plot(ref, csvref)
    child = service.qualify(
        plot, run_root=root, request=request(root, 4), resolution_context=context
    )
    if not child["accepted"]:
        raise RuntimeError("numeric_child_qualification_failed")
    child_event = replay_run(root).events[-1]
    child_receipt = service.inspect(plot.artifact_id, run_root=root)["receipt"]
    report = {
        "schema_version": "arw.public-figure-benchmark.v1",
        "task_sha256": task_sha,
        "source_license": tasks["license"],
        "profile": tasks["profile"],
        "producer": "ARW deterministic benchmark generator; no independent visual acceptance",
        "records": [],
        "human_acceptance": "pending",
        "publication_visual_pass": False,
        "negative_cases": [],
    }
    for task in tasks["tasks"]:
        for candidate in task["candidates"]:
            stem = task["id"] + "-" + candidate
            folder = output / stem
            folder.mkdir()
            ir = (
                plot
                if task["id"] == "exact"
                else composition(
                    service,
                    task,
                    candidate,
                    material,
                    binding,
                    child_event,
                    child_receipt,
                )
            )
            if task["id"] == "exact":
                raw, svg = service._render(
                    ir, run_root=root, resolution_context=context
                )
                compiled = compile_plot(ir, context)
                write_json(
                    folder / "numeric-values.json",
                    [v.model_dump(mode="json") for v in compiled.plot_values],
                )
                fonts = [
                    float(e.attrib["font-size"])
                    for e in ET.fromstring(svg).iter()
                    if "font-size" in e.attrib
                ]
                min_font = (
                    min(fonts) * task["width_mm"] * 72 / 25.4 / ir.presentation.width
                )
                receipt = child_receipt
            else:
                from arw_research_artifact.composition import render_composition

                raw, svg, typography = render_composition(
                    service, ir, run_root=root, resolution_context=context
                )
                min_font = min([t.min_font_pt for t in typography] + [9.6])
                receipt = {
                    "status": "candidate",
                    "visual": "UNAVAILABLE",
                    "typography": [t.model_dump(mode="json") for t in typography],
                }
            (folder / "ir.json").write_bytes(raw)
            (folder / "figure.svg").write_bytes(svg)
            write_json(folder / "receipt.json", receipt)
            pixels = rasterize(
                folder / "figure.svg",
                folder / "figure.png",
                task,
                tasks["profile"],
                python,
            )
            tests = {
                "render": pixels["status"],
                "nonempty": "passed"
                if pixels.get("ink_pixels", 0) > 0
                else "unavailable"
                if pixels["status"] == "unavailable"
                else "failed",
                "border_screen": "failed"
                if pixels.get("border_ink")
                else "passed"
                if pixels["status"] == "passed"
                else "unavailable",
                "glyph_probe": "passed"
                if pixels.get("font_probe_unknown_glyphs") == 0 and pixels.get("fonts")
                else "failed"
                if pixels["status"] == "passed"
                else "unavailable",
                "minimum_font": "passed"
                if min_font >= tasks["profile"]["minimum_font_pt"]
                else "failed",
            }
            record = {
                "id": stem,
                "task_id": task["id"],
                "candidate": candidate,
                "selected": candidate == task["selected"],
                "task_sha256": task_sha,
                "ir_sha256": sha256_hex(raw),
                "svg_sha256": sha256_hex(svg),
                "pixels": pixels,
                "min_font_pt": min_font,
                "provenance_numeric": "passed",
                "mechanical": tests,
                "visual_argument": {
                    "status": "producer_critique_only",
                    "finding": "Column separates source, typed mechanism and evidence with the largest full-width labels."
                    if candidate == "column"
                    else "Parallel panels share facts; inspect small labels and relation routing."
                    if candidate in {"row", "grid"}
                    else "Simple explicit comparison; no significance claim. Inspect separation of raw points/means and grayscale series discrimination.",
                },
                "independent_human": "pending",
                "facts_sha256": sha256_hex(
                    canonical_json_bytes([p.content_sha256 for p in ir.panels])
                )
                if hasattr(ir, "panels")
                else task_sha,
            }
            record["selection_reason"] = selection_reason(
                task, candidate, min_font, tasks["profile"]["minimum_font_pt"]
            )
            record["review_binding_sha256"] = review_binding(record)
            report["records"].append(record)
    report["negative_cases"] = negative_cases(output, report, tasks, python)
    statuses = [v for r in report["records"] for v in r["mechanical"].values()]
    report["mechanical_summary"] = {
        s: statuses.count(s) for s in ("passed", "failed", "unavailable", "not_run")
    }
    report["mechanical_summary"]["denominator"] = len(statuses)
    report["independent_review_summary"] = {
        "reviewed": 0,
        "pending": 4,
        "denominator": 4,
    }
    write_json(output / "report.json", report)
    questions(output, report, tasks)
    return report


def reference_differences(expected, actual):
    """Bound-geometry regression detector, independent of fault generation.

    The reference is the accepted numeric SVG or source-verified composition.
    This inspects identity, geometry/encoding and explicit arrow direction; it
    does not infer scientific semantics from arbitrary unbound images.
    """
    before = {e.attrib["id"]: e for e in expected.iter() if "id" in e.attrib}
    after = {e.attrib["id"]: e for e in actual.iter() if "id" in e.attrib}
    differences = {
        "missing_ids": sorted(set(before) - set(after)),
        "numeric_mark_positions": [],
        "series_colors": [],
        "edge_directions": [],
        "viewport_changed": expected.attrib.get("viewBox")
        != actual.attrib.get("viewBox"),
    }
    for identifier in sorted(set(before) & set(after)):
        old, new = before[identifier], after[identifier]
        if old.tag.endswith("}circle"):
            if tuple(old.attrib.get(k) for k in ("cx", "cy", "r")) != tuple(
                new.attrib.get(k) for k in ("cx", "cy", "r")
            ):
                differences["numeric_mark_positions"].append(identifier)
            if old.attrib.get("fill") != new.attrib.get("fill"):
                differences["series_colors"].append(identifier)
        paths_before = [
            e
            for e in old.iter()
            if "marker-start" in e.attrib or "marker-end" in e.attrib
        ]
        paths_after = [
            e
            for e in new.iter()
            if "marker-start" in e.attrib or "marker-end" in e.attrib
        ]
        if [
            (e.attrib.get("marker-start"), e.attrib.get("marker-end"))
            for e in paths_before
        ] != [
            (e.attrib.get("marker-start"), e.attrib.get("marker-end"))
            for e in paths_after
        ]:
            differences["edge_directions"].append(identifier)
    return differences


def exact_value_differences(expected, actual):
    before = {v["plot_value_id"]: v["exact"] for v in expected}
    after = {v["plot_value_id"]: v["exact"] for v in actual}
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def negative_cases(output, report, tasks, python):
    """Fault injection observations; never admitted as canonical artifacts."""
    exact = output / "exact-single"
    loop = output / "loop-column"
    neg = output / "negative"
    neg.mkdir()
    records = []
    for name in tasks["negative_cases"]:
        base = loop if name in {"arrow_reversed", "object_missing"} else exact
        tree = ET.fromstring((base / "figure.svg").read_bytes())
        original = copy.deepcopy(tree)
        check, reason = "unavailable", ""
        evidence = {}
        if name == "number_replaced":
            values = json.loads((exact / "numeric-values.json").read_bytes())
            expected_values = copy.deepcopy(values)
            expected = copy.deepcopy(values[0]["exact"])
            values[0]["exact"] = {"numerator": 999, "denominator": 1000}
            write_json(neg / "number_replaced-values.json", values)
            evidence = {
                "expected_exact": expected,
                "injected_exact": values[0]["exact"],
            }
            # Alter the associated mark as well as the numeric evidence sidecar.
            mark = next(e for e in tree.iter() if e.tag.endswith("}circle"))
            mark.set("cy", str(float(mark.attrib["cy"]) + 20))
            reason = "Frozen exact rational value is replaced by 999/1000; associated mark position also changes."
        elif name == "arrow_reversed":
            edge = next(
                e
                for e in tree.iter()
                if e.tag.endswith("}path") and "marker-end" in e.attrib
            )
            edge.set("marker-start", edge.attrib.pop("marker-end"))
            reason = (
                "Frozen directed control answer requires marker-end, not marker-start."
            )
        elif name == "object_missing":
            target = next(
                e for e in tree.iter() if e.attrib.get("id", "").endswith("__analysis")
            )
            for parent in tree.iter():
                if target in list(parent):
                    parent.remove(target)
                    break
            reason = "Frozen required analysis object is absent from the SVG identity inventory."
        elif name == "cropped":
            tree.set("viewBox", "100 100 160 90")
            reason = (
                "Expected source viewport is changed and actual edge ink is screened."
            )
        elif name == "glyph_missing":
            text = next(e for e in tree.iter() if e.tag.endswith("}tspan"))
            text.text = "\U0010ffff"
            reason = "Pango glyph probe counts an unsupported scalar in the injected actual text."
        else:
            mark = next(e for e in tree.iter() if e.tag.endswith("}circle"))
            mark.set("fill", "#ff00ff")
            reason = "Frozen series/accepted SVG color differs; this is a synthetic mutation check, not general color perception."
        raw = ET.tostring(tree, encoding="utf-8")
        path = neg / (name + ".svg")
        path.write_bytes(raw)
        task = next(
            t
            for t in tasks["tasks"]
            if t["id"] == ("loop" if base == loop else "exact")
        )
        pixels = rasterize(
            path, path.with_suffix(".png"), task, tasks["profile"], python
        )
        delta = reference_differences(original, tree)
        evidence["reference_differences"] = delta
        if name == "glyph_missing":
            check = (
                "passed"
                if pixels.get("font_probe_unknown_glyphs", 0) > 0
                else "unavailable"
                if pixels["status"] == "unavailable"
                else "failed"
            )
        elif name == "object_missing":
            check = "passed" if delta["missing_ids"] else "failed"
        elif name == "arrow_reversed":
            check = "passed" if delta["edge_directions"] else "failed"
        elif name == "cropped":
            evidence.update(
                {
                    "expected_viewbox": original.attrib["viewBox"],
                    "injected_viewbox": tree.attrib["viewBox"],
                    "actual_ink_pixels": pixels.get("ink_pixels"),
                }
            )
            check = (
                "passed"
                if delta["viewport_changed"]
                and (pixels.get("ink_pixels") == 0 or pixels.get("border_ink"))
                else "unavailable"
                if pixels["status"] == "unavailable"
                else "failed"
            )
        elif name == "number_replaced":
            mismatches = exact_value_differences(expected_values, values)
            evidence["exact_value_mismatches"] = mismatches
            check = (
                "passed" if mismatches and delta["numeric_mark_positions"] else "failed"
            )
        else:
            check = "passed" if delta["series_colors"] else "failed"
        records.append(
            {
                "id": name,
                "expected": "detected",
                "detector_status": check,
                "observation": reason,
                "detector_evidence": evidence,
                "svg_sha256": sha256_hex(raw),
                "pixels": pixels,
                "scope": "Known injected fault only; detector success does not certify arbitrary scientific correctness.",
            }
        )
    return records


def questions(output, report, tasks):
    lines = [
        "# 公开制图基准：待独立人工审阅",
        "",
        "这里的“接受”只表示你能从指定图片读懂该 toy 图，不认可任何真实科研结论。生成程序没有替你填写判定。",
        "请按 PNG 在声明的毫米尺寸查看；过小或看不清就选“修改”，不需要理解源码。示例尺寸是作者定义的测试 profile，不声称符合某期刊版式。",
        "",
    ]
    reviews = []
    for task in tasks["tasks"]:
        rec = next(
            r for r in report["records"] if r["task_id"] == task["id"] and r["selected"]
        )
        lines += [
            f"## {task['id']}",
            "",
            f"![{task['id']}]({rec['id']}/figure.png)",
            "",
            f"[查看同一输出的灰阶版本]({rec['id']}/figure-gray.png)",
            "",
            f"SVG/PDF/IR：`{rec['id']}/`。目标 {task['width_mm']} × {task['height_mm']} mm，最小字高 {rec['min_font_pt']:.2f} pt。",
            "",
        ]
        qs = {
            "exact": [
                "能否分清 baseline 和 proposed？转灰阶后还能分清吗？",
                "是否能同时看到原始点、均值和区间？这里区间是合成数据的预计算范围，不是置信区间。",
            ],
            "loop": [
                "能否找到输入、analysis 和条件出口？看不清的文字或箭头请指出位置。",
                "能否看出 complete 时退出、otherwise 时返回 analysis？控制关系与数据关系能否区分？",
            ],
            "mixed": [
                "能否认出前后面板的 sample 是同一对象，而没有声称已证明因果变化？",
                "你能找到结果面板并读清 baseline/proposed 吗？对象和证据的联系是否清楚？",
            ],
            "stress": [
                "中文、英文和数学符号是否缺字、重叠或被裁切？",
                "长标签和图例是否还能读懂？这是压力测试，发现缺陷是有效结果。",
            ],
        }[task["id"]]
        lines += [
            "1. " + qs[0],
            "2. " + qs[1],
            "3. 请选择：接受 / 修改 / 拒绝，并用一句话写明理由。",
            "",
        ]
        if task["id"] in {"loop", "mixed"}:
            lines += [
                "三种结构候选（科学事实相同，尚待你确认结构差异与选择）：",
                *[
                    "- [" + c + "](" + task["id"] + "-" + c + "/figure.png)"
                    for c in task["candidates"]
                ],
                "预选 column：保留全宽对象与结果，减少横排缩小字体。row/grid 的小字和路径密度保留在报告中。",
                "",
            ]
        reviews.append(
            {
                "task_id": task["id"],
                "producer": report["producer"],
                "reviewer": None,
                "role": "human_nonproducer",
                "binding_sha256": rec["review_binding_sha256"],
                "decision": None,
                "reason": None,
            }
        )
    lines += [
        "## 边界",
        "",
        "这份表还没有任何真实人工签字。机械检查、制图者自查和接受回执均不能替代你的审阅。任何 IR、SVG、PNG、字体或环境变化都使旧绑定失效。受信研究运行如需出版接受，仍须由父级按现有 arw.visual-review.v1 契约独立接纳审查证据。",
    ]
    (output / "REVIEW.md").write_text("\n".join(lines) + "\n")
    write_json(output / "review-pending.json", reviews)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--raster-python", default="/usr/bin/python3")
    args = parser.parse_args()
    result = run(args.output, args.raster_python)
    print(
        json.dumps(
            {
                "records": len(result["records"]),
                "mechanical": result["mechanical_summary"],
                "human_acceptance": result["human_acceptance"],
            },
            ensure_ascii=False,
        )
    )

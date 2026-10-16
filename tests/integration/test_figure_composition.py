"""Real accepted sources/children; no simulated visual-quality certification."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import replace

import jsonschema
import pytest
from pydantic import ValidationError
from arw_research_artifact.composition import CompositionRenderer, safe_tree
from arw_research_artifact.service import ResearchArtifactService
from arw_research_artifact.validation import IRValidationFault

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.accepted_refs import RunPrefix
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.figure_composition import (
    FigureCompositionIR,
    figure_composition_schema_documents,
)
from arw.kernel.state.research_artifact import ResearchBinding
from tests.unit.test_accepted_refs import accepted_fixture
from .test_research_artifacts import request
from .test_result_plots import aggregate, plot, policy


def fixture(tmp_path, *, series=None):
    objects = [
        {
            "kind": "sequence",
            "object_id": "sample",
            "state_id": "raw",
            "segments": [
                {"segment_id": "token.a", "text": "A: observed", "highlighted": True},
                {"segment_id": "token.b", "text": "B: retained", "highlighted": False},
            ],
        },
        {
            "kind": "entity_graph",
            "entities": [
                {
                    "object_id": "sample",
                    "state_id": "processed",
                    "entity_type": "sample",
                    "label": "Observed sample",
                },
                {
                    "object_id": "analysis",
                    "state_id": "fixed",
                    "entity_type": "method",
                    "label": "Accepted analysis",
                },
            ],
            "relations": [
                {
                    "relation_id": "uses.sample",
                    "source": "sample",
                    "target": "analysis",
                    "relation_type": "data",
                    "label": "supplied observations",
                    "directed": True,
                }
            ],
            "expanded_group": {
                "label": "Local analysis",
                "members": ["sample", "analysis"],
            },
        },
    ]
    root, context, ref, event = accepted_fixture(
        tmp_path, canonical_json_bytes({"A": 0.831, "B": 0.832, "objects": objects})
    )
    service = ResearchArtifactService()
    layer = aggregate(ref)
    if series is not None:
        layer = layer.model_copy(
            update={"data": (layer.data[0].model_copy(update={"series": series}),)}
        )
    child = plot((layer,))
    assert service.qualify(
        child, run_root=root, request=request(root), resolution_context=context
    )["accepted"]
    child_event = replay_run(root).events[-1]
    child_receipt = service.inspect(child.artifact_id, run_root=root)["receipt"]

    def binding(i, pointer, e=event):
        return ResearchBinding(
            binding_id=f"binding.{i}",
            artifact_id=e.payload.artifact_id,
            sha256=e.payload.artifact_sha256,
            ledger_event_id=e.event_id,
            ledger_event_sha256=e.event_sha256,
            json_pointer=pointer,
        )

    renderer = CompositionRenderer().identity.model_dump(mode="json")
    panels = []
    for i, obj in enumerate(objects):
        panels.append(
            {
                "panel_id": f"panel.{i}",
                "role": "schematic",
                "label": chr(97 + i),
                "title": ["Source sequence", "Bound mechanism"][i],
                "reading_order": i + 1,
                "position": {"row": 0, "column": i},
                "content_kind": obj["kind"],
                "content_ref": binding(i, f"/objects/{i}").model_dump(mode="json"),
                "content_sha256": sha256_hex(canonical_json_bytes(obj)),
                "renderer": renderer,
            }
        )
    panels.append(
        {
            "panel_id": "panel.2",
            "role": "quantitative",
            "label": "c",
            "title": "Accepted result",
            "reading_order": 3,
            "position": {"row": 0, "column": 2},
            "content_kind": "accepted_v1",
            "content_ref": binding(2, "", child_event).model_dump(mode="json"),
            "content_sha256": sha256_hex(canonical_json_bytes(child_receipt)),
            "renderer": child_receipt["renderer"],
        }
    )
    spec = {
        "artifact_id": "figure.composition",
        "revision": 1,
        "artifact_kind": "figure_composition",
        "visual_argument": "The supplied sample supports the retained analysis and accepted result; no inferred causal transformation.",
        "width_mm": 180.0,
        "height_mm": 140.0,
        "panels": panels,
        "layout": {"kind": "row", "row_ratios": [1], "column_ratios": [1, 1, 2]},
        "encodings": [
            {
                "semantic_id": i,
                "label": i.title(),
                "color": c,
                "shape": s,
                "line_style": d,
            }
            for i, c, s, d in (
                ("sample", "#0072B2", "circle", "solid"),
                ("analysis", "#D55E00", "diamond", "dashed"),
            )
        ],
        "legend_ids": ["sample", "analysis"],
        "validation_policy": policy().model_dump(mode="json"),
    }
    ir = service.build(spec, run_root=root)
    return root, context, service, ir


def test_three_panel_parent_admission_deterministic_layout_and_v1_replay(tmp_path):
    root, context, service, ir = fixture(tmp_path)
    raw, svg = service._render(ir, run_root=root, resolution_context=context)
    assert service._render(ir, run_root=root, resolution_context=context) == (raw, svg)
    assert b"sample" in svg and b"Accuracy result" in svg
    # Child marks/data are copied unchanged; scientific values are not recomputed.
    from arw_research_artifact.composition import namespace_tree

    child_raw = (root / ".arw/artifacts/accepted/figure.result/figure.svg").read_bytes()
    child_tree = namespace_tree(safe_tree(child_raw), "arw_panel_3__")
    composed = ET.fromstring(svg).find(
        ".//{http://www.w3.org/2000/svg}g[@id='arw_panel_3']"
    )[0]
    assert [ET.tostring(e) for e in child_tree] == [ET.tostring(e) for e in composed]
    tree = ET.fromstring(svg)
    ids = [e.attrib["id"] for e in tree.iter() if "id" in e.attrib]
    assert len(ids) == len(set(ids)) and tree.attrib["width"] == "180mm"
    assert list(tree.iter("{http://www.w3.org/2000/svg}text"))
    assert b"clip-path" not in svg
    grid = ir.model_dump(mode="json")
    grid["layout"] = {"kind": "grid", "row_ratios": [1, 2], "column_ratios": [1, 1]}
    grid["panels"][2]["position"] = {"row": 1, "column": 0, "column_span": 2}
    other = FigureCompositionIR.model_validate_json(json.dumps(grid))
    raw2, svg2 = service._render(other, run_root=root, resolution_context=context)
    assert raw != raw2 and svg != svg2
    assert [p.content_sha256 for p in ir.panels] == [
        p.content_sha256 for p in other.panels
    ]
    result = service.qualify(
        ir, run_root=root, request=request(root, 101), resolution_context=context
    )
    assert (
        result["accepted"]
        and result["receipt"]["validation"]["visual"] == "OPTIONAL_SKIPPED"
    )
    assert result["receipt"]["glyph_coverage"] == "not_verified"
    assert all(p["min_font_pt"] > 0 for p in result["receipt"]["typography"])
    assert (
        service.reproduce(ir.artifact_id, run_root=root, resolution_context=context)[
            "status"
        ]
        == "reproduced"
    )
    assert (
        service.reproduce("figure.result", run_root=root, resolution_context=context)[
            "status"
        ]
        == "reproduced"
    )
    assert service.doctor(run_root=root)["status"] == "PASS"
    assert service.qualify(
        ir, run_root=root, request=request(root, 101), resolution_context=context
    )["idempotent"]
    for name, doc in figure_composition_schema_documents().items():
        jsonschema.Draft202012Validator.check_schema(doc)
        value = ir.model_dump(mode="json") if "-ir." in name else result["receipt"]
        jsonschema.validate(value, doc)


@pytest.mark.parametrize(
    "mutation", ["digest", "event", "selected", "bytes", "child", "missing_relation"]
)
def test_reject_tampered_proof_and_bytes(tmp_path, mutation):
    root, context, service, ir = fixture(tmp_path)
    payload = ir.model_dump(mode="json")
    if mutation == "bytes":
        (root / "data.json").write_text("{}")
    elif mutation == "child":
        (root / ".arw/artifacts/accepted/figure.result/figure.svg").write_text("<svg/>")
    elif mutation == "missing_relation":
        payload["panels"][1]["content_ref"]["json_pointer"] = "/objects/9"
    elif mutation == "selected":
        payload["panels"][0]["content_sha256"] = "f" * 64
    else:
        key = "sha256" if mutation == "digest" else "ledger_event_sha256"
        payload["panels"][0]["content_ref"][key] = "f" * 64
    bad = FigureCompositionIR.model_validate_json(json.dumps(payload))
    with pytest.raises((ValueError, RuntimeError)):
        service._render(bad, run_root=root, resolution_context=context)
    assert (
        not any(
            e.payload.artifact_id == ir.artifact_id
            for e in replay_run(root).events
            if e.event_type == "research_artifact_accepted"
        )
        if mutation != "bytes"
        else True
    )


def test_historical_prefix_does_not_gain_later_child(tmp_path):
    root, context, service, ir = fixture(tmp_path)
    events = replay_run(root).events
    early = events[1]
    prefix = RunPrefix(events[0].run_id, early.sequence, early.event_sha256)
    with pytest.raises((ValueError, RuntimeError)):
        service._render(
            ir,
            run_root=root,
            resolution_context=replace(context, run_prefixes=(prefix,)),
        )


def test_publication_blocks_without_exact_review(tmp_path):
    root, context, service, ir = fixture(tmp_path)
    ir = ir.model_copy(
        update={"publication_critical": True, "validation_policy": policy("REQUIRED")}
    )
    result = service.qualify(
        ir, run_root=root, request=request(root, 102), resolution_context=context
    )
    assert (
        not result["accepted"]
        and result["receipt"]["validation"]["visual"] == "UNAVAILABLE"
    )
    assert not any(
        e.event_type == "research_artifact_accepted"
        and e.payload.artifact_id == ir.artifact_id
        for e in replay_run(root).events
    )


@pytest.mark.parametrize(
    "body",
    [
        "<script>alert(1)</script>",
        '<rect onclick="evil()"/>',
        '<image href="https://example.org/x"/>',
        '<rect fill="url(https://example.org/x)"/>',
        '<g id="x"/><g id="x"/>',
        '<g style="fill:red"/>',
        '<g transform="scale(1e999)"/>',
        '<use href="#x"/>',
    ],
)
def test_closed_svg_grammar(body):
    with pytest.raises(IRValidationFault):
        safe_tree(
            ('<svg xmlns="http://www.w3.org/2000/svg">' + body + "</svg>").encode()
        )


def test_namespaced_markers_and_duplicate_ids():
    from arw_research_artifact.composition import namespace_tree

    root = safe_tree(
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><marker id="arrow"/></defs><path marker-end="url(#arrow)"/></svg>'
    )
    result = ET.tostring(namespace_tree(root, "a."))
    assert b'id="a.arrow"' in result and b"url(#a.arrow)" in result


@pytest.mark.parametrize(
    "mutation", ["overlap", "size", "panels", "axes", "encoding", "publication"]
)
def test_strict_bounded_contract(tmp_path, mutation):
    root, context, service, ir = fixture(tmp_path)
    p = ir.model_dump(mode="json")
    if mutation == "overlap":
        p["panels"][1]["position"] = {"row": 0, "column": 0}
    elif mutation == "size":
        p["width_mm"] = float("inf")
    elif mutation == "panels":
        p["panels"] = p["panels"][:1]
    elif mutation == "axes":
        p["layout"]["axes"] = "shared"
    elif mutation == "encoding":
        p["encodings"].append(p["encodings"][0])
    else:
        p["publication_critical"] = True
    with pytest.raises(ValidationError):
        FigureCompositionIR.model_validate_json(json.dumps(p))


def test_shared_encoding_independent_of_panel_order_and_subset(tmp_path):
    root, context, service, ir = fixture(tmp_path)
    renderer = CompositionRenderer()
    from arw.kernel.state.figure_composition import SCIENTIFIC_OBJECT

    obj = SCIENTIFIC_OBJECT.validate_json(
        b'{"kind":"entity_graph","entities":[{"object_id":"sample","state_id":"one","entity_type":"sample","label":"Observed"}],"relations":[]}'
    )
    a = renderer._object(obj, {e.semantic_id: e for e in ir.encodings})
    b = renderer._object(obj, {e.semantic_id: e for e in reversed(ir.encodings)})
    c = renderer._object(obj, {"sample": ir.encodings[0]})
    assert ET.tostring(a) == ET.tostring(b) == ET.tostring(c)
    assert b"#0072B2" in ET.tostring(c)


def test_wrong_output_review_is_rejected_and_not_upgraded(tmp_path):
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.state.models import ArtifactAcceptanceRequest

    root, context, service, ir = fixture(tmp_path)
    ir = ir.model_copy(
        update={"publication_critical": True, "validation_policy": policy("REQUIRED")}
    )
    raw, svg = service._render(ir, run_root=root, resolution_context=context)
    value = {
        "schema_version": "arw.visual-review.v1",
        "ir_sha256": sha256_hex(raw),
        "output_sha256": "f" * 64,
        "status": "PASS",
        "reviewer": {
            "tool_id": "simulated.contract.only",
            "version": "1",
            "identity_digest": "a" * 64,
        },
    }
    (root / "review.json").write_bytes(canonical_json_bytes(value))
    replay = replay_run(root)
    outcome = RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                **request(root, 103).model_dump(mode="json"),
                "artifact_id": "review.composition",
                "artifact_kind": "visual-review",
                "media_type": "application/json",
                "content_path": "review.json",
                "content_sha256": sha256_hex(canonical_json_bytes(value)),
                "base_revision": replay.revision,
                "consumed_sha256": [replay.last_event_sha256],
            }
        )
    )
    assert outcome.accepted
    result = service.qualify(
        ir,
        run_root=root,
        request=request(root, 104),
        resolution_context=context,
        visual_review_id="review.composition",
    )
    assert (
        not result["accepted"] and result["receipt"]["validation"]["visual"] == "FAIL"
    )


def test_existing_schematic_child_and_cli_dispatch(tmp_path):
    import subprocess
    import sys
    from .test_research_artifacts import prepared

    root, service, child = prepared(tmp_path)
    assert service.qualify(child, run_root=root, request=request(root))["accepted"]
    event = replay_run(root).events[-1]
    receipt = service.inspect(child.artifact_id, run_root=root)["receipt"]
    from .test_result_plots import policy

    panels = []
    for i in range(2):
        panels.append(
            {
                "panel_id": f"panel.{i}",
                "role": "schematic",
                "label": chr(97 + i),
                "title": "Original accepted schematic",
                "reading_order": i + 1,
                "position": {"row": 0, "column": i},
                "content_kind": "accepted_v1",
                "content_ref": {
                    "binding_id": f"binding.{i}",
                    "artifact_id": child.artifact_id,
                    "sha256": event.payload.artifact_sha256,
                    "ledger_event_id": event.event_id,
                    "ledger_event_sha256": event.event_sha256,
                    "json_pointer": "",
                },
                "content_sha256": sha256_hex(canonical_json_bytes(receipt)),
                "renderer": receipt["renderer"],
            }
        )
    ir = service.build(
        {
            "artifact_kind": "figure_composition",
            "artifact_id": "figure.pair",
            "revision": 1,
            "visual_argument": "Compare two unchanged accepted views.",
            "width_mm": 180.0,
            "height_mm": 120.0,
            "panels": panels,
            "layout": {"kind": "row", "row_ratios": [1], "column_ratios": [1, 1]},
            "encodings": [],
            "legend_ids": [],
            "validation_policy": policy().model_dump(mode="json"),
        },
        run_root=root,
    )
    (root / "composition.json").write_bytes(
        canonical_json_bytes(ir.model_dump(mode="json"))
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "artifact",
            "render",
            "--run-root",
            str(root),
            "--input",
            "composition.json",
        ],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "candidate"
    result = service.qualify(ir, run_root=root, request=request(root, 105))
    assert result["accepted"]
    assert service.reproduce(ir.artifact_id, run_root=root)["status"] == "reproduced"


def test_child_encoding_conflict_requires_new_accepted_candidate(tmp_path):
    root, context, service, ir = fixture(tmp_path, series="sample")
    with pytest.raises(IRValidationFault, match="requires_new_candidate"):
        service._render(ir, run_root=root, resolution_context=context)

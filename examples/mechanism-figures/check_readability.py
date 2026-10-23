"""Independent mechanical screening of source-expanded SVG and actual font bounds.

Run with the optional system GI interpreter. This is not a pixel review.
"""

from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from itertools import pairwise
from pathlib import Path

NS = "{http://www.w3.org/2000/svg}"
HERE = Path(__file__).resolve().parent


def source_preserved(current, previous):
    """Undo only the declared v3 decomposition; compare every prior fact exactly."""
    restored = json.loads(json.dumps(current))
    for task in restored["tasks"]:
        facts = task["facts"]
        for component in facts["components"]:
            component.pop("coordinate_sum", None)
            component.pop("rule_change", None)
        if task["id"] == "tool-loop":
            init = facts["components"].pop(0)
            assert init["semantic_id"] == "initialize"
            request = facts["components"][0]
            request["steps"].insert(0, init["steps"][0])
            initial_port = request["ports"].pop(0)
            assert initial_port["port_id"] == "initial"
            assert facts["relations"].pop(0)["semantic_id"] == "initialized"
            assert facts["object_chain"].pop(0) == "initialize"
    return all(
        a["facts"] == b["facts"]
        for a, b in zip(restored["tasks"], previous["tasks"], strict=True)
    )


def screen(task, svg):
    import gi

    gi.require_version("Rsvg", "2.0")
    from gi.repository import Rsvg

    root = ET.fromstring(svg)
    nodes = {e.get("id"): e for e in root.iter() if e.get("id")}
    handle = Rsvg.Handle.new_from_data(svg)
    # SVG coordinates are points. Fix physical-unit conversion for the font
    # geometry query; render_document independently uses the output viewport.
    handle.set_dpi(72)
    width, height = map(float, root.get("viewBox").split()[2:])
    viewport = Rsvg.Rectangle()
    viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, width, height
    checks, boxes = [], {}

    def check(name, passed, **details):
        checks.append({"check": name, "passed": bool(passed), **details})

    def value(identity):
        return "".join(nodes[identity].itertext())

    def bounds(identity):
        _, ink, _ = handle.get_geometry_for_layer("#" + identity, viewport)
        return [ink.x, ink.y, ink.x + ink.width, ink.y + ink.height]

    def contains(outer, inner):
        return all(
            (
                outer[0] <= inner[0],
                outer[1] <= inner[1],
                outer[2] >= inner[2],
                outer[3] >= inner[3],
            )
        )

    for identity, node in nodes.items():
        if node.tag == NS + "text":
            boxes[identity] = bounds(identity)
            check(
                "text_inside_canvas:" + identity,
                contains([0, 0, width, height], boxes[identity]),
            )
    for component in task["facts"]["components"]:
        cid = component["semantic_id"]
        body = nodes["body." + cid]
        x, y, w, h = (float(body.get(k)) for k in ("x", "y", "width", "height"))
        for node in nodes["content." + cid].iter(NS + "text"):
            check(
                "text_inside_component:" + node.get("id"),
                contains([x, y, x + w, y + h], boxes[node.get("id")]),
            )
        if table := component.get("coordinate_sum"):
            prefix = "coordinate." + cid + "."
            for j, name in enumerate(table["axis_labels"]):
                check(
                    prefix + "axis." + str(j), value(prefix + "axis." + str(j)) == name
                )
                for i, operand in enumerate(table["operands"]):
                    check(
                        prefix + f"{i}.{j}",
                        value(prefix + f"{i}.{j}") == str(operand["values"][j]),
                    )
                expression = (
                    " + ".join(str(o["values"][j]) for o in table["operands"])
                    + " = "
                    + str(table["result"][j])
                )
                check(prefix + f"sum.{j}", value(prefix + f"sum.{j}") == expression)
        if change := component.get("rule_change"):
            prefix = "rule." + cid + "."
            check(
                prefix + "exact_added_clause",
                value(prefix + "added") == change["added_clause"],
            )
            check(
                prefix + "emphasis",
                nodes[prefix + "added"].get("font-weight") == "bold"
                and nodes[prefix + "guard-box"].get("stroke-width") == "2",
            )
            check(
                prefix + "guard_inside_box",
                contains(bounds(prefix + "guard-box"), boxes[prefix + "added"]),
            )
            for part in ("retained", "conclusion"):
                a = nodes[prefix + "before." + part].find(NS + "tspan")
                b = nodes[prefix + "after." + part].find(NS + "tspan")
                check(prefix + "aligned." + part, a.get("x") == b.get("x"))

    edges = {
        r["semantic_id"]: nodes["edge." + r["semantic_id"]]
        for r in task["facts"]["relations"]
    }
    for relation in task["facts"]["relations"]:
        rid = relation["semantic_id"]
        label = nodes["edge-label." + rid]
        check(
            "intact_edge_name:" + rid,
            [e.text for e in label.findall(NS + "tspan")] == [rid],
        )
        box = boxes["edge-label." + rid]
        for eid, edge in edges.items():
            points = [
                tuple(map(float, p.split(","))) for p in edge.get("points").split()
            ]
            for i, (a, b) in enumerate(pairwise(points)):
                # These fixtures use orthogonal paths. Include stroke clearance.
                if a[0] == b[0]:
                    crossing = (
                        box[0] - 1 <= a[0] <= box[2] + 1
                        and max(a[1], b[1]) >= box[1] - 1
                        and min(a[1], b[1]) <= box[3] + 1
                    )
                elif a[1] == b[1]:
                    crossing = (
                        box[1] - 1 <= a[1] <= box[3] + 1
                        and max(a[0], b[0]) >= box[0] - 1
                        and min(a[0], b[0]) <= box[2] + 1
                    )
                else:
                    raise ValueError("nonorthogonal fixture route")
                check(f"edge_label_clear:{rid}:{eid}:{i}", not crossing)
        if relation["source_component"] == "decide":
            port = relation["source_port"]
            role = "continue" if relation["feedback"] else "stop"
            check(
                "predicate_exact:" + rid,
                value("predicate.decide." + port) == role + ": " + relation["trigger"],
            )
            leader = nodes["predicate-link.decide." + port]
            output = nodes["port.decide." + port]
            endpoint = (output.get("cx"), output.get("cy"))
            check(
                "predicate_port_binding:" + rid,
                (leader.get("x2"), leader.get("y2")) == endpoint
                and edges[rid].get("points").split()[0] == ",".join(endpoint),
            )
    return {
        "id": task["id"],
        "status": "passed" if all(c["passed"] for c in checks) else "failed",
        "checks": checks,
        "text_ink_bounds_pt": boxes,
    }


def run(packet):
    tasks = json.loads((HERE / "tasks.json").read_text())
    previous = json.loads((HERE / "tasks.v2.json").read_text())
    preserved = source_preserved(tasks, previous)
    outputs = [
        screen(t, (packet / (t["id"] + ".svg")).read_bytes()) for t in tasks["tasks"]
    ]
    result = {
        "scope": "Mechanical SVG source/port/font-ink geometry checks; not independent pixel review",
        "status": "passed"
        if preserved and all(t["status"] == "passed" for t in outputs)
        else "failed",
        "source_v2_facts_preserved_after_declared_decomposition": preserved,
        "tasks_sha256": hashlib.sha256((HERE / "tasks.json").read_bytes()).hexdigest(),
        "geometry_environment": {
            "interpreter": sys.version.split()[0],
            "dpi_for_point_coordinates": 72,
        },
        "tasks": outputs,
        "independent_pixel_review": "not_run",
        "human_status": "human_pending",
        "publication_visual_pass": False,
        "limits": [
            "Text ink containment does not establish reader comprehension.",
            "Edge clearance only screens local labels against orthogonal relation paths; it does not grade all visual interactions.",
        ],
    }
    (packet / "mechanical.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "source_v2_facts_preserved_after_declared_decomposition",
                    "independent_pixel_review",
                )
            }
        )
    )
    return result


if __name__ == "__main__":
    result = run(Path(sys.argv[1]))
    sys.exit(0 if result["status"] == "passed" else 1)

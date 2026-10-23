"""Prepare six actual pixel controls; keep truth out of the reviewer input."""

import argparse
import json
import pathlib
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("output", type=pathlib.Path)
parser.add_argument("truth", type=pathlib.Path)
parser.add_argument("--raster-python", default="/usr/bin/python3")
args = parser.parse_args()
root = args.output

v = json.loads((root / "reviewer-input.json").read_text())
truth = [
    ("representation", "missing_step"),
    ("tool-loop", "reverse_arrow"),
    ("representation", "object_identity"),
    ("tool-loop", "stop_role_label"),
    ("representation", "fabricated_value"),
    ("constraint", "small_text"),
]
caseinputs = []
answers = []
for i, (name, fault) in enumerate(truth, 1):
    case = "case-" + str(i)
    svg = root / (name + ".negative." + fault + ".svg")
    dest = root / (case + ".svg")
    dest.write_bytes(svg.read_bytes())
    task = next(t for t in v["tasks"] if t["id"] == name)
    ir = json.loads((root / task["ir"]).read_text())
    cmd = [
        args.raster_python,
        str(
            pathlib.Path(__file__).resolve().parents[1]
            / "figure-benchmark/rasterize.py"
        ),
        str(dest),
        str(root / (case + ".png")),
        str(ir["width_mm"]),
        str(ir["height_mm"]),
        "150",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    raster = json.loads(res.stdout)
    if raster["status"] != "passed":
        raise RuntimeError(raster)
    caseinputs.append(
        dict(
            case_id=case, task_id=name, svg=dest.name, png=case + ".png", raster=raster
        )
    )
    answers.append(dict(case_id=case, truth=fault, expected="changes_required"))
(root / "reviewer-blind-cases.json").write_text(
    json.dumps(dict(cases=caseinputs), ensure_ascii=False, indent=2) + "\n"
)
args.truth.write_text(json.dumps(answers, indent=2) + "\n")
print("Rendered", len(caseinputs), "actual negative PNGs")

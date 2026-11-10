"""The focused native job must exercise real isolation, not accept a skip."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_native_security_requires_real_cpu_boundary_before_source_materialization():
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    job = workflow["jobs"]["native-security"]
    steps = job["steps"]
    names = [step.get("name") for step in steps]
    name = "Require independent CPU pilot isolation boundary"
    index = names.index(name)
    step = steps[index]
    assert names.index("Install native test prerequisites") < index
    assert index < names.index(
        "Restore legal receipt and materialize pinned native source"
    )
    assert "needs" not in job  # Broad Python qualification cannot suppress this job.
    assert "if" not in step and "continue-on-error" not in step
    assert step["env"]["ARW_REQUIRE_INDEPENDENT_ISOLATION"] == "1"
    assert step["env"]["PYTHONPATH"] == "src:."
    assert step["run"].splitlines() == [
        "mkdir -p build/evidence",
        ".venv/bin/python -m pytest -q tests/evals/test_independent_cpu_pilot.py --basetemp=build/evidence/ci-independent-pilot",
    ]

    retained = steps[index + 1]
    assert retained["name"] == "Retain independent CPU pilot evidence"
    assert retained["if"] == "always()"
    assert retained["uses"] == "actions/upload-artifact@v7"
    assert retained["with"]["name"] == "ci-independent-pilot"
    assert retained["with"]["path"] == "build/evidence/ci-independent-pilot"
    assert retained["with"]["if-no-files-found"] == "warn"

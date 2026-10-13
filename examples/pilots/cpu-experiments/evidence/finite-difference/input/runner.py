#!/usr/bin/env python3
"""Inspected stdlib-only numerical pilot worker, explicitly run outside ARW."""

from __future__ import annotations

import csv
import json
import math
import platform
import random
import time
from datetime import UTC, datetime
from pathlib import Path


def utc():
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def execute(root: Path):
    config = json.loads((root / "input/config.json").read_text())
    started = utc()
    wall, cpu = time.perf_counter(), time.process_time()
    values = []
    for trial in config["trials"]:
        if config["experiment"] == "trapezoid":
            n = trial
            value = (0.5 + sum((i / n) ** 2 for i in range(1, n))) / n
        elif config["experiment"] == "finite-difference":
            h = trial
            value = (math.sin(h) - math.sin(-h)) / (2 * h)
        elif config["experiment"] == "monte-carlo-pi":
            rng = random.Random(trial)
            n = config["samples"]
            value = (
                4
                * sum(rng.random() ** 2 + rng.random() ** 2 <= 1 for _ in range(n))
                / n
            )
        else:
            raise ValueError("unsupported inspected experiment")
        values.append((str(trial), value))
    measured = {
        "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
    }
    output = root / "results"
    output.mkdir()
    with (output / "raw.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("trial", "value"))
        writer.writerows(values)
    record = {
        "started_at": started,
        "finished_at": utc(),
        "measurements": measured,
        "python_version": platform.python_version(),
        "machine_architecture": platform.machine(),
        "processes": 1,
        "gpu_used": False,
        "model_calls": 0,
        "monetary_cost": "unknown",
        "energy_cost": "unknown",
        "peak_memory_bytes": "unknown",
        "cost_scope": "worker numerical-loop wall and process CPU time only; excludes parent/CLI overhead",
    }
    (output / "execution.json").write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    execute(parser.parse_args().root)

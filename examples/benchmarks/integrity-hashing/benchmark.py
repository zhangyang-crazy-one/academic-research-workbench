"""Controlled file-hash and retained-stage verification benchmark, not startup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def worker(mode, kind, path):
    from arw.kernel.core.canonical import sha256_file

    def baseline_hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    if kind == "preflight":
        from arw.kernel.policy import core_integrity, integration_lock

        if mode == "baseline":
            core_integrity.sha256_file = baseline_hash
            integration_lock.sha256_file = baseline_hash

        def action():
            return core_integrity.verify_staged_core(path)
    else:
        reader = baseline_hash if mode == "baseline" else sha256_file

        def action():
            return reader(path)

    tracemalloc.start()
    start = time.perf_counter()
    result = action()
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "mode": mode,
        "kind": kind,
        "input": path.name if kind == "hash" else "retained-stage",
        "wall_seconds": elapsed,
        "tracemalloc_peak_bytes": peak,
        "ru_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "result": result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-root", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "build/benchmarks/integrity-hashing"
    )
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("this RSS report uses Linux ru_maxrss units")
    if (
        args.stage_root
        and not (args.stage_root / "share/arw/build-identity.json").is_file()
    ):
        parser.error("stage root must contain the assembled plugin build identity")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []

    def measure(kind, path, expected=None):
        previous_result = expected
        for repeat in range(3):
            for mode in ("baseline", "stream"):
                result = subprocess.run(
                    [sys.executable, __file__, "--worker", mode, kind, str(path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=True,
                )
                item = json.loads(result.stdout)
                if previous_result is None:
                    previous_result = item["result"]
                if item["result"] != previous_result:
                    raise RuntimeError("baseline and stream results differ")
                item["repeat"] = repeat
                records.append(item)

    for size in (32, 512):
        path = args.output / f"{size}MiB.bin"
        # Exclusive creation prevents overwriting any caller-owned benchmark input.
        with path.open("xb") as stream:
            stream.truncate(size * 1024 * 1024)
        try:
            with path.open("rb") as stream:
                expected = hashlib.file_digest(stream, "sha256").hexdigest()
            measure("hash", path, expected)
        finally:
            path.unlink()
    if args.stage_root:
        measure("preflight", args.stage_root.resolve())
    report = {
        "schema_version": "1.0.0",
        "measurement_scope": "isolated hash and controlled retained-stage verifier",
        "python_version": sys.version.split()[0],
        "records": records,
    }
    path = args.output / "results.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    env_path = os.pathsep.join(
        [str(ROOT / "src"), *map(str, (ROOT / "extensions").glob("*/src"))]
    )
    os.environ["PYTHONPATH"] = env_path
    sys.path[:0] = env_path.split(os.pathsep)
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        print(json.dumps(worker(sys.argv[2], sys.argv[3], Path(sys.argv[4]))))
    else:
        main()

"""Audit two fixed, public English examples with a locally verified model."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    "The public archive keeps field notebooks in a climate controlled room. "
    "Each notebook lists the date, the observer, and a short description of the visit. "
    "Researchers can compare those records with maps and photographs held by the same library. "
    "The catalog describes how the materials were collected, but it does not resolve every ambiguity. "
    "Readers should inspect the original pages before drawing conclusions about a particular event."
)
REVISION = (
    "Field notebooks are kept in a climate controlled room at the public archive. "
    "Each one records a visit date, an observer, and a brief account of the visit. "
    "The library also holds maps and photographs that researchers can compare with these records. "
    "Its catalog explains the collection history while leaving some ambiguities unresolved. "
    "A reader should examine the original pages before reaching a conclusion about any particular event."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "original.txt").write_text(SOURCE, encoding="utf-8")
    (args.output_dir / "revision.txt").write_text(REVISION, encoding="utf-8")
    (args.output_dir / "detectors.json").write_text(
        json.dumps(
            {
                "detectors": [
                    {
                        "backend": "openai_gpt2_detector_local",
                        "model_path": str(args.model_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONPATH": f"{ROOT / 'src'}:{ROOT / 'extensions/academic-humanization/src'}",
    }
    command = [
        sys.executable,
        "-m",
        "arw.cli",
        "writing",
        "audit",
        "--source",
        str(args.output_dir / "original.txt"),
        "--revision",
        str(args.output_dir / "revision.txt"),
        "--detectors",
        str(args.output_dir / "detectors.json"),
    ]
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())

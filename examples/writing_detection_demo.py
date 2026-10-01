"""Run public synthetic inputs through the real local detector algorithms."""

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "tests/fixtures/writing_detection/synthetic_nb.json"
VOCAB = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
KEY = "PUBLIC_SYNTHETIC_DEMO_ONLY"


def next_green(previous):
    digest = hmac.digest(KEY.encode(), previous.encode(), "sha256")
    seed = int.from_bytes(digest[:8], "big")
    ranked = sorted(
        VOCAB,
        key=lambda word: hashlib.sha256(
            seed.to_bytes(8, "big") + word.encode()
        ).digest(),
    )
    return ranked[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    words = [VOCAB[0]]
    for _ in range(80):
        words.append(next_green(words[-1]))
    original = " ".join(words)
    revised = original.replace("alpha", "beta")
    (args.output_dir / "original.txt").write_text(original, encoding="utf-8")
    (args.output_dir / "revised.txt").write_text(revised, encoding="utf-8")
    config = {
        "detectors": [
            {
                "backend": "naive_bayes_local",
                "model_path": str(MODEL),
                "label": "synthetic_a",
                "max_tokens": 100,
            },
            {
                "backend": "hmac_green",
                "key": KEY,
                "key_id": "public-demo-v1",
                "vocabulary": VOCAB,
                "gamma": 0.5,
                "min_tokens": 30,
            },
        ]
    }
    (args.output_dir / "detectors.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
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
        str(args.output_dir / "revised.txt"),
        "--detectors",
        str(args.output_dir / "detectors.json"),
    ]
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())

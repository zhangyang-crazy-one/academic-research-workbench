"""Explicitly fetch and verify the pinned public safetensors GPT-2 detector."""

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "extensions/academic-humanization/src"))
from arw_writing.gpt2_preset import (
    FILES,
    MODEL_ID,
    REVISION,
    verify_files,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Explicit public HTTPS download; omitted means offline verification only",
    )
    args = parser.parse_args()
    root = args.destination
    if root.is_symlink():
        parser.error("destination symlink is not allowed")
    if args.download:
        root.mkdir(parents=True, exist_ok=True)
        opener = build_opener(ProxyHandler({}))
        for name, expected in FILES.items():
            path = root / name
            if path.exists():
                continue
            url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}"
            temporary = root / f".{name}.part"
            digest = hashlib.sha256()
            try:
                with (
                    opener.open(url, timeout=120) as source,
                    temporary.open("xb") as target,
                ):
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        target.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError(f"digest mismatch for {name}")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    fault = verify_files(root)
    if fault:
        parser.error(f"model verification failed: {fault}")
    print(f"verified {MODEL_ID}@{REVISION} ({len(FILES)} pinned files)")


if __name__ == "__main__":
    main()

"""Pinned public GPT-2 detector files; no network or model loading here."""

from __future__ import annotations

import hashlib
from pathlib import Path

MODEL_ID = "openai-community/roberta-base-openai-detector"
REVISION = "6cba99c003b711c7fe94f8a3aa2be35a792cb6fa"
LICENSE = "MIT"
MODEL_CARD = f"https://huggingface.co/{MODEL_ID}/tree/{REVISION}"
FILES = {
    "config.json": "bd2b40605e167659786107548562d94a87a3cb50c084ccc386d7177ccfb1d268",
    "merges.txt": "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5",
    "model.safetensors": "3abd6d2b005f5876b945cb5b68ddde04f6e28fbd9c5d6dc5adfb06ba647e0546",
    "tokenizer.json": "847bbeab6174d66a88898f729d52fa8d355fafe1bea101cf960dd404581df70e",
    "tokenizer_config.json": "994f46754c5bf4014f1aa92d34b1374319c3a6b3f702105cd5b742beaecd18ce",
    "vocab.json": "9e7f63c2d15d666b52e21d250d2e513b87c9b713cfa6987a82ed89e5e6e50655",
}


def verify_files(root: Path) -> str | None:
    """Return a bounded fault code, or None when exact safe files match."""
    if root.is_symlink() or not root.is_dir():
        return "model_directory_missing_or_symlink"
    if {item.name for item in root.iterdir()} != set(FILES):
        return "unexpected_or_missing_model_files"
    if (root / "pytorch_model.bin").exists():
        return "pickle_weights_not_allowed"
    for name, expected in FILES.items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            return "model_file_missing_or_symlink"
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return "model_file_unreadable"
        if digest.hexdigest() != expected:
            return "model_file_digest_mismatch"
    return None

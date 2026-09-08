"""Keep qualified wheel hashes independent of the host's DEFLATE library."""

from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def normalize_wheel(path: Path) -> None:
    """Preserve member bytes/metadata while storing them without compression.

    Hatchling supplies reproducible timestamps and permissions. Different zlib
    implementations can nevertheless encode identical members differently. Stored
    members avoid that variability without changing METADATA, WHEEL or RECORD.
    """
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".wheel-tmp")
    try:
        with os.fdopen(descriptor, "w+b") as output:
            with ZipFile(path) as source, ZipFile(output, "w") as destination:
                for info in sorted(source.infolist(), key=lambda entry: entry.filename):
                    metadata = copy.copy(info)
                    metadata.compress_type = ZIP_STORED
                    destination.writestr(metadata, source.read(info))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class ReproducibleWheelHook(BuildHookInterface):
    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        if self.target_name == "wheel" and version != "editable":
            normalize_wheel(Path(artifact_path))

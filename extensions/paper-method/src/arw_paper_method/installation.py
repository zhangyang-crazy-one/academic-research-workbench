"""Explicit create-only installation of a relocatable standard-library adapter."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from .method import canonical
from .provenance import export_proof, verify_proof
from .qualification import CAPSULE, EXT, ROOT, SOURCE_PATHS, sha, validate_capsule


def install(destination: Path, *, capsule_path: Path = CAPSULE) -> dict:
    capsule_raw, capsule = validate_capsule(capsule_path)
    proof_path = EXT / "source-proof.json"
    if proof_path.is_file():
        import json

        proof = json.loads(proof_path.read_bytes())
    else:
        proof = export_proof(ROOT, capsule["source_commit"], SOURCE_PATHS)
    verify_proof(ROOT, capsule["source_commit"], SOURCE_PATHS, proof)
    # Read and bind every payload before creating an installation directory.
    payload = {path: (ROOT / path).read_bytes() for path in SOURCE_PATHS}
    payload["extensions/paper-method/source-capsule.json"] = capsule_raw
    payload["extensions/paper-method/source-proof.json"] = canonical(proof)
    payload["extensions/paper-method/README.md"] = (EXT / "README.md").read_bytes()
    payload["bin/arw-paper-method"] = (
        b"#!/usr/bin/env bash\nset -euo pipefail\n"
        b'ARW_METHOD_ROOT="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"\n'
        b'export PYTHONPATH="$ARW_METHOD_ROOT/src:$ARW_METHOD_ROOT/extensions/paper-method/src"\n'
        b'exec /usr/bin/python3 -S -m arw_paper_method.server "$@"\n'
    )
    destination = destination.absolute()
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for relative, raw in payload.items():
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        target.chmod(0o700 if relative.startswith("bin/") else 0o600)
    manifest = {
        "schema_version": "arw.paper-method-installation.v1",
        "source_commit": capsule["source_commit"],
        "source_capsule_sha256": sha(capsule_raw),
        "dependency_inventory": [],
        "files": {path: sha(raw) for path, raw in payload.items()},
        "qualification_required": True,
        "automatic_registration": False,
    }
    (destination / "installation-manifest.json").write_bytes(canonical(manifest))
    return {"status": "installed", "destination": str(destination), **manifest}


def package(destination: Path, *, capsule_path: Path = CAPSULE) -> dict:
    """Create an offline archive; extracting it performs no registration."""
    with TemporaryDirectory(dir=destination.absolute().parent) as temporary:
        stage = Path(temporary) / "stage"
        manifest = install(stage, capsule_path=capsule_path)
        with ZipFile(destination, mode="x", compression=ZIP_STORED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage).as_posix())
    return {
        "status": "packaged",
        "archive": str(destination.absolute()),
        "archive_sha256": sha(destination.read_bytes()),
        "source_commit": manifest["source_commit"],
        "qualification_required": True,
        "automatic_registration": False,
    }

"""Portable Git Merkle witnesses; verification uses only the standard library."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def object_id(kind: str, raw: bytes) -> str:
    return hashlib.sha1(f"{kind} {len(raw)}\0".encode() + raw).hexdigest()


def tree_entries(raw: bytes) -> dict[str, tuple[str, str]]:
    entries = {}
    offset = 0
    while offset < len(raw):
        end = raw.index(b"\0", offset)
        mode, name = raw[offset:end].split(b" ", 1)
        identifier = raw[end + 1 : end + 21]
        if len(identifier) != 20 or name.decode() in entries:
            raise ValueError("invalid source tree")
        entries[name.decode()] = mode.decode(), identifier.hex()
        offset = end + 21
    return entries


def export_proof(root: Path, commit: str, paths: tuple[str, ...]) -> dict:
    def read(kind, identifier):
        return subprocess.check_output(
            ["git", "-C", str(root), "cat-file", kind, identifier], timeout=2
        )

    commit_raw = read("commit", commit)
    root_tree = commit_raw.splitlines()[0].removeprefix(b"tree ").decode()
    trees = {}
    for path in paths:
        identifier = root_tree
        for name in path.split("/")[:-1]:
            raw = read("tree", identifier)
            trees[identifier] = raw.hex()
            identifier = tree_entries(raw)[name][1]
        trees[identifier] = read("tree", identifier).hex()
    return {"commit_object": commit_raw.hex(), "trees": trees}


def verify_proof(root: Path, commit: str, paths: tuple[str, ...], proof: dict) -> None:
    raw = bytes.fromhex(proof["commit_object"])
    if object_id("commit", raw) != commit or not raw.startswith(b"tree "):
        raise ValueError("source commit mismatch")
    root_tree = raw.splitlines()[0][5:].decode()
    for path in paths:
        identifier = root_tree
        parts = path.split("/")
        for index, name in enumerate(parts):
            raw = bytes.fromhex(proof["trees"][identifier])
            if object_id("tree", raw) != identifier:
                raise ValueError("source tree mismatch")
            mode, identifier = tree_entries(raw)[name]
            if index < len(parts) - 1:
                if mode != "40000":
                    raise ValueError("source directory mismatch")
            elif (
                mode not in ("100644", "100755")
                or object_id("blob", (root / path).read_bytes()) != identifier
            ):
                raise ValueError("source file mismatch")

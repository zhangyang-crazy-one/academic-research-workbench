"""Focused checks for the explicit candidate wheel boundary."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import runpy
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = runpy.run_path(str(ROOT / "scripts/license-gate"))
BUILDER = runpy.run_path(str(ROOT / "scripts/build-candidate"))


def test_native_environment_uses_production_only_npm_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("npm_config_omit", "")
    monkeypatch.setenv("NPM_CONFIG_OMIT", "optional")
    monkeypatch.setenv("npm_config_include", "dev")
    monkeypatch.setenv("NPM_CONFIG_INCLUDE", "dev")
    monkeypatch.setenv("npm_config_production", "false")
    monkeypatch.setenv("NPM_CONFIG_PRODUCTION", "true")
    monkeypatch.setattr(GATE["shutil"], "which", lambda tool: str(tmp_path / "virtual-tools" / tool))
    environment = GATE["native_environment"](tmp_path / "evidence", tmp_path)

    assert environment["npm_config_omit"] == "dev"
    assert environment["npm_config_include"] == "prod"
    assert {key for key in environment if key.lower() == "npm_config_omit"} == {"npm_config_omit"}
    assert {key for key in environment if key.lower() == "npm_config_include"} == {"npm_config_include"}
    assert not any(key.lower() == "npm_config_production" for key in environment)
    assert environment["PATH"].split(os.pathsep)[0] == str(tmp_path / "wrappers")
    for tool in ("npm", "scancode"):
        assert str(tmp_path / "virtual-tools" / tool) in (tmp_path / "wrappers" / tool).read_text()


def test_candidate_builder_accepts_multiple_declared_lower_bounds() -> None:
    requirements = ["hatchling>=1.31.0", "packaging>=25.0", "colorama>=0.4.6; sys_platform == 'win32'"]
    assert BUILDER["validate_build_requirements"]({
        "build-backend": "hatchling.build",
        "requires": requirements,
    }) == requirements


@pytest.mark.parametrize("requirements", (["hatchling==1.31.0"], ["hatchling>=1.31.0,<2"], ["packaging>=25.0"]))
def test_candidate_builder_rejects_locked_or_missing_backend(requirements: list[str]) -> None:
    with pytest.raises(ValueError):
        BUILDER["validate_build_requirements"]({
            "build-backend": "hatchling.build",
            "requires": requirements,
        })


def test_candidate_builder_rejects_duplicate_normalized_requirements() -> None:
    with pytest.raises(ValueError, match="duplicate normalized build requirement"):
        BUILDER["validate_build_requirements"]({
            "build-backend": "hatchling.build",
            "requires": ["hatchling>=1.31.0", "Hatchling>=1.32.0"],
        })


def test_candidate_builder_collapses_identical_distribution_sightings() -> None:
    hatchling = {"name": "hatchling", "version": "1.32.4", "license": "MIT",
                 "installed_content_sha256": "a" * 64}
    packaging = {"name": "packaging", "version": "25.0", "license": "Apache-2.0",
                 "installed_content_sha256": "b" * 64}
    assert BUILDER["collapse_distribution_sightings"]([hatchling, packaging, hatchling.copy()]) == [
        hatchling, packaging,
    ]


@pytest.mark.parametrize("change", ({"name": "Hatchling"}, {"version": "1.32.5"},
                                    {"installed_content_sha256": "c" * 64}))
def test_candidate_builder_rejects_conflicting_distribution_sightings(change: dict[str, str]) -> None:
    row = {"name": "hatchling", "version": "1.32.4", "license": "MIT",
           "installed_content_sha256": "a" * 64}
    with pytest.raises(ValueError, match="conflicting distribution sightings: hatchling"):
        BUILDER["collapse_distribution_sightings"]([row, {**row, **change}])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_wheel(path: Path, *, metadata_name: str = "academic-research-workbench", corrupt_record: bool = False,
                generator: str = "hatchling 1.32.4", extra_member: str | None = None,
                altered_source: bool = False, missing_source: bool = False) -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = configuration["project"]
    prefix = "academic_research_workbench-0.1.0.dist-info/"
    requirements = [f"Requires-Dist: {item}" for item in project["dependencies"]]
    for extra, items in project["optional-dependencies"].items():
        requirements.append(f"Provides-Extra: {extra}")
        requirements.extend(f"Requires-Dist: {item}; extra == '{extra}'" for item in items)
    files = {
        prefix + "METADATA": (f"Metadata-Version: 2.5\nName: {metadata_name}\nVersion: {project['version']}\n"
                              f"Summary: {project['description']}\nLicense-File: LICENSE\n"
                              f"Requires-Python: {project['requires-python']}\n" + "\n".join(requirements) + "\n").encode(),
        prefix + "WHEEL": f"Wheel-Version: 1.0\nGenerator: {generator}\nRoot-Is-Purelib: true\nTag: py3-none-any\n".encode(),
        prefix + "licenses/LICENSE": (ROOT / "LICENSE").read_bytes(),
    }
    entry_points = {
        "console_scripts": project.get("scripts", {}),
        "gui_scripts": project.get("gui-scripts", {}),
        **project.get("entry-points", {}),
    }
    if any(entry_points.values()):
        files[prefix + "entry_points.txt"] = ("\n".join(
            f"[{group}]\n" + "\n".join(f"{name} = {target}" for name, target in entries.items())
            for group, entries in entry_points.items() if entries
        ) + "\n").encode()
    source_map = GATE["wheel_source_map"](configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"])
    files.update({member: (ROOT / source).read_bytes() for member, source in source_map.items()})
    if altered_source:
        files["arw/__init__.py"] = b"substituted source\n"
    if missing_source:
        del files["arw/__init__.py"]
    if extra_member is not None:
        files[extra_member] = b"ordinary unconfigured payload\n"
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for name, data in files.items():
        checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={checksum if not corrupt_record or name != 'arw/__init__.py' else '0' * 43}", len(data)))
    writer.writerow((prefix + "RECORD", "", ""))
    files[prefix + "RECORD"] = record.getvalue().encode()
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def candidate(tmp_path: Path, **wheel_options: object) -> tuple[Path, Path]:
    wheel = tmp_path / "dist/academic_research_workbench-0.1.0-py3-none-any.whl"
    write_wheel(wheel, **wheel_options)
    sdist = tmp_path / "dist/academic_research_workbench-0.1.0.tar.gz"
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text())
    roots = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    sources = ["pyproject.toml", "build_hooks.py", "LICENSE",
               "tests/fixtures/confinement/allowed/escape-link",
               "tests/fixtures/confinement/outside/secret.txt",
               *GATE["wheel_source_map"](roots).values()]
    with tarfile.open(sdist, "w:gz") as archive:
        for relative in sources:
            archive.add(ROOT / relative, arcname=f"academic_research_workbench-0.1.0/{relative}")
        project = configuration["project"]
        requirements = [f"Requires-Dist: {item}" for item in project["dependencies"]]
        for extra, items in project["optional-dependencies"].items():
            requirements.append(f"Provides-Extra: {extra}")
            requirements.extend(f"Requires-Dist: {item}; extra == '{extra}'" for item in items)
        metadata = (f"Metadata-Version: 2.5\nName: {project['name']}\nVersion: {project['version']}\n"
                    f"Summary: {project['description']}\nLicense-File: LICENSE\n"
                    f"Requires-Python: {project['requires-python']}\n" + "\n".join(requirements) + "\n").encode()
        info = tarfile.TarInfo("academic_research_workbench-0.1.0/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
    evidence = {
        "schema_version": "1.0.0",
        "source_identity": {
            "source_manifest_sha256": sha256(ROOT / "vendor/source-manifest.json"),
            "pyproject_sha256": sha256(ROOT / "pyproject.toml"),
            "build_hook_sha256": sha256(ROOT / "build_hooks.py"),
            "package_tree_sha256": GATE["package_tree_sha256"](configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]),
            "sdist_sha256": sha256(sdist),
        },
        "build": {
            "python": {"version": "3.14.6", "executable": "/tmp/builder/bin/python"},
            "uv": {"version": "uv 0.11.28"},
            "backend": {"name": "hatchling", "version": "1.32.4"},
            "inventory": [{"name": "hatchling", "version": "1.32.4", "license": "MIT", "installed_content_sha256": "0" * 64}],
            "argv": ["python", "-m", "hatchling", "build"],
            "requirements": configuration["build-system"]["requires"],
        },
        "resolved_runtime_inventory": [
            {"name": name, "version": version, "license": "MIT", "installed_content_sha256": "1" * 64}
            for name, version in (("jsonschema", "4.26.0"), ("platformdirs", "4.11.6"),
                                  ("portalocker", "3.2.0"), ("pydantic", "2.13.4"))
        ],
        "runtime_resolution_environment": {
            "python": {"version": "3.14.6", "executable": "/tmp/validation/bin/python"},
            "uv": {"version": "uv 0.11.28"},
            "install_argv": ["uv", "pip", "install"],
            "inventory": [
                {"name": name, "version": version, "license": "MIT", "installed_content_sha256": "1" * 64}
                for name, version in (("jsonschema", "4.26.0"), ("platformdirs", "4.11.6"),
                                      ("portalocker", "3.2.0"), ("pydantic", "2.13.4"))
            ],
        },
        "artifacts": [
            {"kind": "wheel", "path": f"dist/{wheel.name}", "size": wheel.stat().st_size, "sha256": sha256(wheel)},
            {"kind": "sdist", "path": f"dist/{sdist.name}", "size": sdist.stat().st_size, "sha256": sha256(sdist)},
        ],
    }
    evidence_path = tmp_path / "build-evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return wheel, evidence_path


def validate(wheel: Path, evidence: Path) -> tuple[dict[str, str], dict[str, object]]:
    return GATE["validate_candidate"](wheel, evidence, ROOT / "vendor/source-manifest.json")


def strip_wheel_license(wheel: Path, evidence_path: Path) -> None:
    """Reseal a valid candidate after removing its license and declaration."""
    with zipfile.ZipFile(wheel) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    record_name = next(name for name in files if name.endswith(".dist-info/RECORD"))
    metadata_name = next(name for name in files if name.endswith(".dist-info/METADATA"))
    files[metadata_name] = files[metadata_name].replace(b"License-File: LICENSE\n", b"")
    for name in list(files):
        if ".dist-info/licenses/" in name or name == record_name:
            del files[name]
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for name, data in files.items():
        checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={checksum}", len(data)))
    writer.writerow((record_name, "", ""))
    files[record_name] = record.getvalue().encode()
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    evidence = json.loads(evidence_path.read_text())
    row = next(item for item in evidence["artifacts"] if item["kind"] == "wheel")
    row["size"] = wheel.stat().st_size
    row["sha256"] = sha256(wheel)
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")


def test_candidate_requires_source_declared_wheel_license(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wheel, evidence = candidate(tmp_path)
    validate(wheel, evidence)
    strip_wheel_license(wheel, evidence)
    with pytest.raises(SystemExit):
        validate(wheel, evidence)
    assert "required wheel license files are absent: ['LICENSE']" in capsys.readouterr().err


def mutate_sdist(evidence_path: Path, *, member_name: str = "build_hooks.py",
                 replacement: bytes | None = None, rename: str | None = None,
                 omit: bool = False) -> None:
    evidence = json.loads(evidence_path.read_text())
    row = next(item for item in evidence["artifacts"] if item["kind"] == "sdist")
    path = evidence_path.parent / row["path"]
    with tarfile.open(path, "r:gz") as archive:
        members = [(info, archive.extractfile(info).read() if info.isfile() else None)
                   for info in archive.getmembers()]
    with tarfile.open(path, "w:gz") as archive:
        for info, data in members:
            if info.name.endswith("/" + member_name):
                if omit:
                    continue
                info.name = rename or info.name
                if replacement is not None:
                    data = replacement
                    info.size = len(data)
            archive.addfile(info, io.BytesIO(data) if data is not None else None)
    row["size"] = path.stat().st_size
    row["sha256"] = sha256(path)
    evidence["source_identity"]["sdist_sha256"] = row["sha256"]
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")


def test_candidate_wheel_metadata_and_record_are_validated(tmp_path: Path) -> None:
    wheel, evidence = candidate(tmp_path)
    identity, _ = validate(wheel, evidence)
    assert identity["sha256"] == sha256(wheel)
    for option in ({"metadata_name": "substituted-package"}, {"corrupt_record": True}):
        alternate = tmp_path / next(iter(option))
        bad_wheel, bad_evidence = candidate(alternate, **option)
        with pytest.raises(SystemExit):
            validate(bad_wheel, bad_evidence)


@pytest.mark.parametrize("filename", (
    "unrelated-0.1.0-py3-none-any.whl",
    "academic_research_workbench-0.2.0-py3-none-any.whl",
    "academic_research_workbench-0.1.0-cp313-cp313-manylinux_2_17_x86_64.whl",
))
def test_candidate_rejects_wheel_filename_identity_or_tag(tmp_path: Path, filename: str) -> None:
    wheel, path = candidate(tmp_path)
    renamed = wheel.with_name(filename)
    wheel.rename(renamed)
    evidence = json.loads(path.read_text())
    evidence["artifacts"][0]["path"] = f"dist/{filename}"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(SystemExit):
        validate(renamed, path)


def test_candidate_rejects_generator_version_drift(tmp_path: Path) -> None:
    wheel, path = candidate(tmp_path, generator="hatchling 9.9.9")
    with pytest.raises(SystemExit):
        validate(wheel, path)


@pytest.mark.parametrize("option", (
    {"extra_member": "surprise/data.txt"},
    {"extra_member": "academic_research_workbench-0.1.0.other-info/UNEXPECTED"},
    {"altered_source": True},
    {"missing_source": True},
))
def test_candidate_rejects_unbound_wheel_members(tmp_path: Path, option: dict[str, object]) -> None:
    wheel, path = candidate(tmp_path, **option)
    with pytest.raises(SystemExit):
        validate(wheel, path)


@pytest.mark.parametrize("mutation", ("text", "source-bytes", "foreign-path", "traversal", "metadata", "missing-package-source"))
def test_candidate_rejects_unbound_sdist(tmp_path: Path, mutation: str) -> None:
    wheel, path = candidate(tmp_path)
    if mutation == "text":
        evidence = json.loads(path.read_text())
        row = next(item for item in evidence["artifacts"] if item["kind"] == "sdist")
        source = path.parent / row["path"]
        source.write_bytes(b"synthetic source archive")
        row["size"] = source.stat().st_size
        row["sha256"] = sha256(source)
        evidence["source_identity"]["sdist_sha256"] = row["sha256"]
        path.write_text(json.dumps(evidence), encoding="utf-8")
    elif mutation == "source-bytes":
        mutate_sdist(path, replacement=b"altered build hook\n")
    elif mutation == "foreign-path":
        mutate_sdist(path, rename="other_project-0.1.0/build_hooks.py")
    elif mutation == "traversal":
        mutate_sdist(path, rename="academic_research_workbench-0.1.0/../build_hooks.py")
    elif mutation == "missing-package-source":
        mutate_sdist(path, member_name="src/arw/__init__.py", omit=True)
    else:
        mutate_sdist(path, member_name="PKG-INFO", replacement=b"Name: other-project\nVersion: 0.1.0\n")
    with pytest.raises(SystemExit):
        validate(wheel, path)


def test_candidate_rejects_synthetic_text_wheel(tmp_path: Path) -> None:
    wheel, path = candidate(tmp_path)
    wheel.write_bytes(b"synthetic wheel")
    evidence = json.loads(path.read_text())
    evidence["artifacts"][0]["size"] = wheel.stat().st_size
    evidence["artifacts"][0]["sha256"] = sha256(wheel)
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises((SystemExit, zipfile.BadZipFile)):
        validate(wheel, path)


@pytest.mark.parametrize("mutation", (
    "builder-python", "builder-python-27", "runtime-python", "runtime-python-27",
    "builder-uv", "runtime-uv", "duplicate-build", "duplicate-runtime",
    "bad-version", "uppercase-hash", "two-backends", "conflicting-sha",
))
def test_candidate_rejects_invalid_inventory(tmp_path: Path, mutation: str) -> None:
    wheel, path = candidate(tmp_path)
    evidence = json.loads(path.read_text())
    build = evidence["build"]
    runtime = evidence["resolved_runtime_inventory"]
    if mutation == "builder-python":
        build["python"]["version"] = "3.12.9"
    elif mutation == "builder-python-27":
        build["python"]["version"] = "2.7.18"
    elif mutation == "runtime-python":
        evidence["runtime_resolution_environment"]["python"]["version"] = "not-a-version"
    elif mutation == "runtime-python-27":
        evidence["runtime_resolution_environment"]["python"]["version"] = "2.7.18"
    elif mutation == "builder-uv":
        build["uv"]["version"] = "uv not-a-version"
    elif mutation == "runtime-uv":
        evidence["runtime_resolution_environment"]["uv"]["version"] = "not-uv 0.11.28"
    elif mutation == "duplicate-build":
        build["inventory"].append({**build["inventory"][0], "name": "Hatchling"})
    elif mutation == "duplicate-runtime":
        runtime.append({**runtime[0], "name": "JSONSchema"})
    elif mutation == "bad-version":
        build["inventory"][0]["version"] = "not-a-version"
    elif mutation == "uppercase-hash":
        runtime[0]["installed_content_sha256"] = "A" * 64
    elif mutation == "two-backends":
        build["inventory"].append({**build["inventory"][0], "name": "Hatchling"})
    else:
        runtime.append({**build["inventory"][0], "installed_content_sha256": "f" * 64})
    evidence["runtime_resolution_environment"]["inventory"] = runtime
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(SystemExit):
        validate(wheel, path)


@pytest.mark.parametrize("mutation", ("empty", "missing-direct", "unsatisfied-direct"))
def test_candidate_requires_resolved_direct_dependencies(tmp_path: Path, mutation: str) -> None:
    wheel, path = candidate(tmp_path)
    evidence = json.loads(path.read_text())
    inventory = evidence["resolved_runtime_inventory"]
    if mutation == "empty":
        inventory.clear()
    elif mutation == "missing-direct":
        inventory[:] = [row for row in inventory if row["name"] != "portalocker"]
    else:
        next(row for row in inventory if row["name"] == "pydantic")["version"] = "1.0.0"
    evidence["runtime_resolution_environment"]["inventory"] = inventory
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(SystemExit):
        validate(wheel, path)


@pytest.mark.parametrize("mutation", ("wheel-digest", "missing-backend", "ambiguous-wheel", "missing-inventory", "mixed-runtime"))
def test_candidate_rejects_bad_build_evidence(tmp_path: Path, mutation: str) -> None:
    wheel, path = candidate(tmp_path)
    evidence = json.loads(path.read_text())
    if mutation == "wheel-digest":
        evidence["artifacts"][0]["sha256"] = "0" * 64
    elif mutation == "missing-backend":
        del evidence["build"]["backend"]
    elif mutation == "ambiguous-wheel":
        evidence["artifacts"].append({**evidence["artifacts"][0], "path": "dist/other.whl"})
    elif mutation == "missing-inventory":
        evidence["build"]["inventory"] = []
    else:
        evidence["runtime_resolution_environment"]["python"]["executable"] = evidence["build"]["python"]["executable"]
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(SystemExit):
        validate(wheel, path)

"""Wheel normalization preserves payloads while eliminating compressor drift."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

spec = spec_from_file_location(
    "arw_build_hooks", Path(__file__).parents[2] / "build_hooks.py"
)
module = module_from_spec(spec)
spec.loader.exec_module(module)


def test_identical_payloads_have_identical_wheel_bytes_across_compressors(tmp_path):
    members = {
        "arw/example.py": b"example = 'payload'\n" * 200,
        "arw.dist-info/RECORD": b"unchanged-record-bytes\n",
    }
    paths = [tmp_path / "first.whl", tmp_path / "second.whl"]
    for path, level in zip(paths, (1, 9), strict=True):
        with ZipFile(path, "w") as archive:
            for name, data in members.items():
                info = ZipInfo(name, (2020, 2, 2, 0, 0, 0))
                info.external_attr = 0o644 << 16
                archive.writestr(
                    info, data, compress_type=ZIP_DEFLATED, compresslevel=level
                )
    assert paths[0].read_bytes() != paths[1].read_bytes()
    for path in paths:
        module.normalize_wheel(path)
        with ZipFile(path) as archive:
            assert {name: archive.read(name) for name in archive.namelist()} == members
            assert all(info.compress_type == ZIP_STORED for info in archive.infolist())
            assert all(info.external_attr >> 16 == 0o644 for info in archive.infolist())
    assert paths[0].read_bytes() == paths[1].read_bytes()
    before = paths[0].read_bytes()
    module.normalize_wheel(paths[0])
    assert paths[0].read_bytes() == before

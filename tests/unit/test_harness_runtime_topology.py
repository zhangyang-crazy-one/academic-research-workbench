"""Selected driver topology is provenance, including internal symlinks."""

import pytest

from arw.kernel.execution.configured_harness import ConfiguredHarnessAdapter
from arw.kernel.execution.execution import PermissionDenied
from arw.kernel.execution.harness_config import HarnessEntry


def _adapter(tmp_path):
    driver = tmp_path / "driver"
    driver.mkdir()
    (driver / "one.py").write_text("one\n")
    (driver / "two.py").write_text("two\n")
    run = tmp_path / "run"
    run.mkdir()
    return (
        driver,
        run,
        ConfiguredHarnessAdapter(
            HarnessEntry(
                kind="command",
                command=("/usr/bin/python3", str(driver / "entry.py")),
                runtime_roots=(str(driver),),
            ),
            config_sha256="a" * 64,
            config_base=tmp_path,
        ),
    )


@pytest.mark.parametrize("directory", [False, True])
def test_runtime_fingerprint_binds_internal_link_target(tmp_path, directory):
    driver, run, adapter = _adapter(tmp_path)
    if directory:
        (driver / "one").mkdir()
        (driver / "two").mkdir()
    link = driver / "entry.py"
    link.symlink_to("one" if directory else "one.py")
    before = adapter._runtime_digest(run)
    assert adapter._runtime_digest(run) == before
    link.unlink()
    link.symlink_to("two" if directory else "two.py")
    after = adapter._runtime_digest(run)
    assert after != before
    assert adapter._runtime_digest(run) == after


@pytest.mark.parametrize("target", ["absent", "entry.py", "../outside.py"])
def test_runtime_rejects_dangling_cyclic_and_escaping_links(tmp_path, target):
    driver, run, adapter = _adapter(tmp_path)
    (tmp_path / "outside.py").write_text("outside\n")
    (driver / "entry.py").symlink_to(target)
    with pytest.raises(PermissionDenied, match="runtime symlink"):
        adapter._runtime_digest(run)


def test_runtime_fingerprint_binds_intermediate_link_topology(tmp_path):
    driver, run, adapter = _adapter(tmp_path)
    (driver / "entry.py").symlink_to("current.py")
    middle = driver / "current.py"
    middle.symlink_to("one.py")
    before = adapter._runtime_digest(run)
    middle.unlink()
    middle.symlink_to("two.py")
    assert adapter._runtime_digest(run) != before

"""Unpublished receipt fragments cannot become canonical recovery blockers."""

import os
import signal
import subprocess
import sys

import pytest

from arw.kernel.ledger import journal
from arw.research_startup import load_plan, start


@pytest.mark.skipif(
    not hasattr(signal, "SIGKILL"), reason="real SIGKILL requires POSIX"
)
@pytest.mark.parametrize("phase", ["prepared", "committed"])
@pytest.mark.parametrize("written", [0, 18])
def test_actual_sigkill_during_receipt_write_resumes_exact_request(
    tmp_path, phase, written
):
    code = """import os,signal,sys
from pathlib import Path
from arw.research_startup import start
from arw.kernel.ledger import journal
target='.initialization-'+sys.argv[2]+'.json'
original=journal._write_exclusive
def write(path,data):
 if path.name==target or path.name.startswith(target+'.'):
  with path.open('xb') as stream:
   stream.write(data[:int(sys.argv[3])]);stream.flush();os.fsync(stream.fileno())
   os.kill(os.getpid(),signal.SIGKILL)
 original(path,data)
journal._write_exclusive=write
start(Path(sys.argv[1]),direction='Atomic receipt publication regression')
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), phase, str(written)],
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert process.returncode == -signal.SIGKILL, process.stderr.decode()
    plan = load_plan(tmp_path)
    run = tmp_path / plan.run_relative
    if phase == "committed":
        assert journal.replay_run(run).revision == 1
    recovered = start(tmp_path, resume=True)
    assert recovered["run"]["revision"] == 1
    events = journal.replay_run(run).events
    assert len(events) == 1
    assert events[0].event_id == plan.request.event_id
    assert (run / journal.INITIALIZATION_PREPARED).read_bytes() == (
        run / journal.INITIALIZATION_COMMITTED
    ).read_bytes()
    fragments = list((run / journal.INITIALIZATION_STAGING).iterdir())
    assert len(fragments) == 1
    assert len(fragments[0].read_bytes()) == written
    before = fragments[0].read_bytes()
    assert start(tmp_path, resume=True)["run"]["revision"] == 1
    assert fragments[0].read_bytes() == before


def test_receipt_publication_is_exclusive_and_preserves_existing_bytes(tmp_path):
    target = tmp_path / journal.INITIALIZATION_PREPARED
    target.write_bytes(b"existing untrusted receipt")
    with pytest.raises(FileExistsError):
        journal._publish_initialization_record(target, b"new receipt")
    assert target.read_bytes() == b"existing untrusted receipt"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink privilege is host-specific on Windows"
)
def test_receipt_staging_symlink_is_rejected_without_outside_write(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    (run / journal.INITIALIZATION_STAGING).symlink_to(outside, target_is_directory=True)
    with pytest.raises(journal.JournalError, match="staging"):
        journal._publish_initialization_record(
            run / journal.INITIALIZATION_PREPARED, b"data"
        )
    assert list(outside.iterdir()) == []

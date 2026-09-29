from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

CODEX_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = CODEX_ROOT / "scripts" / "check_fact_locked_revision.py"
FIXTURES = CODEX_ROOT / "tests" / "fixtures" / "fact_locked"


def _load():
    spec = importlib.util.spec_from_file_location("check_fact_locked_revision", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _audit(revision: str, **kwargs) -> dict:
    source = (FIXTURES / "source.tex").read_text(encoding="utf-8")
    text = (FIXTURES / f"revision_{revision}.tex").read_text(encoding="utf-8")
    return _load().audit(source, text, **kwargs)


def _failed(report: dict) -> list[str]:
    return [item["check"] for item in report["findings"] if item["severity"] == "fail"]


def test_restated_and_reordered_revision_passes() -> None:
    report = _audit("pass")
    assert report["passed"] is True
    assert report["findings"] == []
    assert report["table_rows"] == {"source": 2, "revision": 2}


def test_new_derived_value_fails() -> None:
    report = _audit("new_value")
    assert _failed(report) == ["F1"]
    assert report["findings"][0]["values"] == ["2.06"]


def test_value_moved_between_rows_fails_even_when_value_set_is_unchanged() -> None:
    report = _audit("row_swap")
    assert _failed(report) == ["F3"]


def test_dropped_fact_fails_unless_waived() -> None:
    report = _audit("dropped")
    assert _failed(report) == ["F2"]
    assert report["findings"][0]["values"] == ["99.74", "99.93"]
    waived = _audit("dropped", allow_drop=("99.74", "99.93"))
    assert waived["passed"] is True
    assert waived["waived_drops"] == ["99.74", "99.93"]


def test_citation_change_fails() -> None:
    source = (FIXTURES / "source.tex").read_text(encoding="utf-8")
    revision = source.replace("\\cite{r4}", "\\cite{r5}")
    report = _load().audit(source, revision)
    assert _failed(report) == ["F4"]
    assert report["findings"][0]["values"] == ["-\\cite{r4}", "+\\cite{r5}"]


def test_new_label_only_row_is_a_warning_not_a_failure() -> None:
    source = (
        (FIXTURES / "source.tex")
        .read_text(encoding="utf-8")
        .replace("\\section{Results}", "\\section{Results}\nSee rank-1.")
    )
    revision = source.replace(
        "\\begin{tabular}{lrrr}",
        "\\begin{tabular}{ll}\nComparison & Reference \\\\\nLLM vs rank-1 & first candidate \\\\\n"
        "\\end{tabular}\n\\begin{tabular}{lrrr}",
    )
    report = _load().audit(source, revision)
    assert report["passed"] is True
    assert [item["severity"] for item in report["findings"]] == ["warn"]


def test_markdown_values_swapped_between_arms_fail() -> None:
    source = "| Arm | F1 |\n|---|---:|\n| L | 27.55 |\n| G | 56.71 |\n"
    swapped = "| Arm | F1 |\n|---|---:|\n| L | 56.71 |\n| G | 27.55 |\n"
    assert _failed(_load().audit(source, swapped)) == ["F3"]
    reordered = "| F1 | Arm |\n|---:|---|\n| **56.71** | G |\n| 27.55 | L |\n"
    assert _load().audit(source, reordered.replace("**", ""))["passed"] is True


def test_latex_bold_and_column_reorder_are_layout_only() -> None:
    source = (FIXTURES / "source.tex").read_text(encoding="utf-8")
    revision = source.replace(
        "G & 13,124 & 9,104 & 56.71 \\\\", "\\textbf{56.71} & G & 13,124 & 9,104 \\\\"
    )
    assert revision != source
    assert _load().audit(source, revision)["passed"] is True


def test_semantic_checklist_is_always_reported() -> None:
    report = _audit("pass")
    assert len(report["semantic_checklist"]) == 5
    assert any("causal" in item for item in report["semantic_checklist"])


def test_cli_exit_codes_and_json() -> None:
    ok = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(FIXTURES / "source.tex"),
            "--revision",
            str(FIXTURES / "revision_pass.tex"),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0
    assert json.loads(ok.stdout)["schema"] == "arw.fact-locked-revision-report.v1"
    bad = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(FIXTURES / "source.tex"),
            "--revision",
            str(FIXTURES / "revision_new_value.tex"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1
    missing = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(FIXTURES / "absent.tex"),
            "--revision",
            str(FIXTURES / "revision_pass.tex"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2

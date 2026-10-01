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


def test_unwrapped_markdown_rows_preserve_values_with_their_arms() -> None:
    source = "Arm | Value\n--- | ---:\nL | 27.55\nG | 56.71\n"
    swapped = "Arm | Value\n--- | ---:\nL | 56.71\nG | 27.55\n"
    module = _load()
    report = module.audit(source, swapped)
    assert _failed(report) == ["F3"]
    assert report["table_rows"] == {"source": 2, "revision": 2}
    assert module.audit(source, source)["passed"] is True
    reordered = "Value | Arm\n---: | ---\n56.71 | G\n27.55 | L\n"
    assert module.audit(source, reordered)["passed"] is True


def test_pipe_prose_without_markdown_table_context_is_not_a_row() -> None:
    for text in (
        "L | 27.55\nG | 56.71\n",
        "| L | 27.55 |\n| G | 56.71 |\n",
        "Arm | Value\nnot a separator | here\nL | 27.55\n",
    ):
        assert _load().audit(text, text)["table_rows"] == {"source": 0, "revision": 0}


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


def test_explicit_citation_migration_preserves_identity() -> None:
    for citation in ("[4]", "{[}4{]}"):
        source = f"Score 27.55, following {citation}."
        revision = r"Score 27.55, following \cite{r4}."
        assert "F4" in _failed(_load().audit(source, revision, allow_drop=("4",)))
        report = _load().audit(source, revision, citation_map=("[4]=r4",))
        assert report["passed"]
        assert report["citation_mapping"] == {"[4]": "r4"}
        assert report["waived_drops"] == []


def test_citation_mapping_does_not_waive_same_valued_reported_fact() -> None:
    report = _load().audit(
        "Score 4. See [4].", r"See \cite{ref_4}.", citation_map=("[4]=ref_4",)
    )
    assert _failed(report) == ["F2"]
    assert report["findings"][0]["values"] == ["4"]


def test_citation_mapping_preserves_table_cells() -> None:
    source = "| Arm | Value | Source |\n|---|---|---|\n| A | 27.55 | {[}4{]} |"
    revision = source.replace("{[}4{]}", r"\cite{r4}")
    assert _load().audit(source, revision, citation_map=("[4]=r4",))["passed"]


def test_citation_mapping_cannot_hide_wrong_or_unrelated_citations() -> None:
    for source, revision in (
        ("[4]", r"\cite{wrong}"),
        (r"[4] \cite{other}", r"\cite{r4} \cite{wrong}"),
        ("[4] [5]", r"\cite{r4} [6]"),
        ("[4] [4]", r"\cite{r4}"),
        ("[4]", r"\cite{r4} \cite{r4}"),
        (r"[4] \cite{r4}", r"\cite{r4}"),
        ("[4]", r"<!-- \cite{r4} -->"),
        ("[4, 5]", r"\cite{r4} [5]"),
        ("[4-6]", r"\cite{r4} [6]"),
    ):
        report = _load().audit(source, revision, citation_map=("[4]=r4",))
        assert "F4" in _failed(report), (source, revision, report)


def test_mapping_allows_partial_migration_and_grouped_latex_keys() -> None:
    report = _load().audit(
        "[4] [4] [5]", r"[4] \cite{r4,r5}", citation_map=("[4]=r4", "[5]=r5")
    )
    assert report["passed"]


def test_mapping_rejects_ambiguous_or_broad_entries() -> None:
    import pytest

    for entries in (
        ("[4]=r4", "[4]=r5"),
        ("[4]=r4", "[5]=r4"),
        ("[4]=r4", "[4]=r4"),
        ("Score 4=r4",),
        ("[4,5]=r4",),
        ("[4]=r4,r5",),
        ("[4]=",),
        ("[4]=\\cite{r4}",),
    ):
        with pytest.raises(ValueError):
            _load().audit("[4]", r"\cite{r4}", citation_map=entries)


def test_citation_mapping_cli(tmp_path: Path) -> None:
    source, revision = tmp_path / "source.tex", tmp_path / "revision.tex"
    source.write_text("See {[}4{]}.", encoding="utf-8")
    revision.write_text(r"See \cite{r4}.", encoding="utf-8")
    command = [
        sys.executable,
        str(SCRIPT),
        "--source",
        str(source),
        "--revision",
        str(revision),
        "--json",
        "--citation-map",
    ]
    result = subprocess.run(
        command + ["[4]=r4"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["citation_mapping"] == {"[4]": "r4"}
    result = subprocess.run(
        command + ["[4]=r4,r5"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "invalid citation mapping" in result.stderr


def test_citation_mapping_preserves_existing_optional_argument_and_key() -> None:
    source = r"See [4] and \cite[4]{other}."
    revision = r"See \cite{r4} and \cite{r4}."
    report = _load().audit(source, revision, citation_map=("[4]=r4",))
    assert "F4" in _failed(report)
    assert "F2" in _failed(report)
    assert _load().audit(
        source, r"See \cite{r4} and \cite[4]{other}.", citation_map=("[4]=r4",)
    )["passed"]


def test_mapped_table_citation_command_variants_are_equivalent() -> None:
    for command in ("cite", "citep", "citet", "citep*"):
        source = "| Arm | Value | Source |\n|---|---|---|\n| A | 27.55 | [4] |"
        revision = source.replace("[4]", "\\" + command + "{r4}")
        assert _load().audit(source, revision, citation_map=("[4]=r4",))["passed"]


def test_mapped_table_variants_keep_unmapped_keys_and_locator_facts() -> None:
    module = _load()
    assert (
        module._mapped_table_citation_forms(r"\citep{other}", {"r4"})
        == r"\citep{other}"
    )
    assert (
        module._mapped_table_citation_forms(r"\citep[4]{r4}", {"r4"}) == r"\cite[4]{r4}"
    )
    report = module.audit(
        "| Arm | Value | Source |\n|---|---|---|\n" r"| A | 27.55 | \citep[4]{r4} |",
        "| Arm | Value | Source |\n|---|---|---|\n" r"| A | 27.55 | \cite{r4} |",
        citation_map=("[4]=r4",),
    )
    assert "F2" in _failed(report)
    assert "F3" in _failed(report)

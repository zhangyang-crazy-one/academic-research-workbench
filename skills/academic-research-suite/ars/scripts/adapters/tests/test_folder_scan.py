"""Tests for scripts/adapters/folder_scan.py."""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = REPO_ROOT / "scripts/adapters/folder_scan.py"
FIXTURE_DIR = REPO_ROOT / "scripts/adapters/examples/folder_scan/input_fixture"
EXPECTED_PASSPORT = REPO_ROOT / "scripts/adapters/examples/folder_scan/expected_passport.yaml"
EXPECTED_REJECTION = REPO_ROOT / "scripts/adapters/examples/folder_scan/expected_rejection_log.yaml"

# folder_scan emits machine-dependent absolute paths in source_pointer and
# input_source; widen clean_timestamps for these tests only. T8/T9 must NOT
# widen — their logical URIs are deterministic and broken pointers should
# fail the golden test.
_FOLDER_SCAN_EXTRA = {"source_pointer", "input_source"}


def _load_json(path: Path):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"invalid JSON fixture: {path}") from error
    assert isinstance(document, dict)
    return document


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(ADAPTER)] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
    )


def _load_adapter_module():
    spec = importlib.util.spec_from_file_location("folder_scan_adapter", ADAPTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_adapter_exists():
    assert ADAPTER.exists()

def test_ascii_hyphenated_family_preserves_legacy_citation_key(
    tmp_path, load_yaml
):
    source = tmp_path / "ascii-legacy"
    source.mkdir()
    (source / "Smith-Jones_2024_Paper.pdf").touch()
    passport_out = tmp_path / "passport.yaml"
    rejection_out = tmp_path / "rejection.yaml"
    result = _run(
        "--input",
        str(source),
        "--passport",
        str(passport_out),
        "--rejection-log",
        str(rejection_out),
    )
    assert result.returncode == 0, result.stderr
    entry = load_yaml(passport_out)["literature_corpus"][0]
    assert entry["authors"] == [{"family": "Smith"}]
    assert entry["citation_key"] == "smith2024"


def test_cjk_family_year_filename_is_accepted_with_original_display_text(
    tmp_path, load_yaml
):
    source = tmp_path / "cjk"
    source.mkdir()
    (source / "中文檔名_2024.pdf").touch()
    passport_out = tmp_path / "passport.yaml"
    rejection_out = tmp_path / "rejection.yaml"

    result = _run(
        "--input",
        str(source),
        "--passport",
        str(passport_out),
        "--rejection-log",
        str(rejection_out),
    )
    assert result.returncode == 0, result.stderr
    entries = load_yaml(passport_out)["literature_corpus"]
    assert entries, "CJK family/year filename was rejected instead of accepted"
    entry = entries[0]
    assert entry["authors"] == [{"family": "中文檔名"}]
    assert entry["title"] == "中文檔名_2024"
    assert entry["year"] == 2024
    assert entry["citation_key"].startswith("ref2024")

    import jsonschema

    schema = _load_json(
        REPO_ROOT / "shared/contracts/passport/literature_corpus_entry.schema.json"
    )
    jsonschema.validate(entry, schema)


def test_unicode_family_rejects_control_separator_and_emoji_only_tokens() -> None:
    adapter = _load_adapter_module()
    assert hasattr(adapter, "_is_unicode_family"), (
        "the explicit Unicode family-token security grammar is missing"
    )
    assert adapter._is_unicode_family("张三")
    assert adapter._is_unicode_family("O’Neil")
    for unsafe in (
        "",
        "张\u200b三",
        "张 三",
        "🙂",
        "张🙂",
        "张\ue000三",
        "张\ud800三",
    ):
        assert not adapter._is_unicode_family(unsafe)


def test_unicode_citekey_nfkc_equivalence_distinction_and_collision_suffixes() -> None:
    adapter = _load_adapter_module()
    composed = adapter._unicode_citation_key_base(
        family="é", year=2024, title="é_2024_étude"
    )
    decomposed = adapter._unicode_citation_key_base(
        family="e\u0301", year=2024, title="e\u0301_2024_e\u0301tude"
    )
    assert composed == decomposed
    assert composed != adapter._unicode_citation_key_base(
        family="李", year=2024, title="李_2024_研究"
    )
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_:-]*", composed)

    existing = set()
    assert adapter._unique_ascii_citation_key(composed, existing) == composed
    assert adapter._unique_ascii_citation_key(composed, existing) == f"{composed}a"


def test_documented_unicode_separators_and_malformed_families(tmp_path, load_yaml):
    source = tmp_path / "unicode"
    source.mkdir()
    accepted = (
        "张_2024_研究.pdf",
        "李-2024-研究.pdf",
        "欧阳.2023.研究.pdf",
        "赵 2022 研究.pdf",
    )
    rejected = (
        "张\u200b三_2024_研究.pdf",
        "🙂_2024_研究.pdf",
        "张🙂_2024_研究.pdf",
        "张_研究.pdf",
    )
    for name in accepted + rejected:
        (source / name).touch()
    passport_out = tmp_path / "passport.yaml"
    rejection_out = tmp_path / "rejection.yaml"
    result = _run(
        "--input",
        str(source),
        "--passport",
        str(passport_out),
        "--rejection-log",
        str(rejection_out),
    )
    assert result.returncode == 0, result.stderr
    entries = load_yaml(passport_out)["literature_corpus"]
    assert {entry["title"] for entry in entries} == {
        Path(name).stem for name in accepted
    }
    assert {entry["authors"][0]["family"] for entry in entries} == {
        "张",
        "李",
        "欧阳",
        "赵",
    }
    keys = [entry["citation_key"] for entry in entries]
    assert len(keys) == len(set(keys)) == 4
    assert all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_:-]*", key) for key in keys)
    rejected_rows = load_yaml(rejection_out)["rejected"]
    assert {row["source"] for row in rejected_rows} == set(rejected)


def test_nfkc_equivalent_filenames_share_base_without_losing_display_text(
    tmp_path, load_yaml
):
    source = tmp_path / "nfkc"
    source.mkdir()
    names = ("é_2024_étude.pdf", "e\u0301_2024_e\u0301tude.pdf")
    for name in names:
        (source / name).touch()
    passport_out = tmp_path / "passport.yaml"
    rejection_out = tmp_path / "rejection.yaml"
    result = _run(
        "--input",
        str(source),
        "--passport",
        str(passport_out),
        "--rejection-log",
        str(rejection_out),
    )
    assert result.returncode == 0, result.stderr
    entries = load_yaml(passport_out)["literature_corpus"]
    adapter = _load_adapter_module()
    base = adapter._unicode_citation_key_base(
        family="é", year=2024, title="é_2024_étude"
    )
    assert {entry["citation_key"] for entry in entries} == {base, f"{base}a"}
    assert {entry["authors"][0]["family"] for entry in entries} == {
        "é",
        "e\u0301",
    }
    assert {entry["title"] for entry in entries} == {
        "é_2024_étude",
        "e\u0301_2024_e\u0301tude",
    }


def test_happy_path(tmp_path, load_yaml, clean_timestamps):
    passport_out = tmp_path / "passport.yaml"
    rejection_out = tmp_path / "rejection_log.yaml"
    r = _run(
        "--input", str(FIXTURE_DIR),
        "--passport", str(passport_out),
        "--rejection-log", str(rejection_out),
    )
    assert r.returncode == 0, r.stderr

    got = load_yaml(passport_out)
    expected = load_yaml(EXPECTED_PASSPORT)
    assert clean_timestamps(got, _FOLDER_SCAN_EXTRA) == clean_timestamps(
        expected, _FOLDER_SCAN_EXTRA
    )

    got_rej = load_yaml(rejection_out)
    expected_rej = load_yaml(EXPECTED_REJECTION)
    assert clean_timestamps(got_rej, _FOLDER_SCAN_EXTRA) == clean_timestamps(
        expected_rej, _FOLDER_SCAN_EXTRA
    )


def test_empty_folder_emits_empty_passport(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    passport_out = tmp_path / "p.yaml"
    rej_out = tmp_path / "r.yaml"
    r = _run(
        "--input", str(empty),
        "--passport", str(passport_out),
        "--rejection-log", str(rej_out),
    )
    assert r.returncode == 0
    import yaml
    with passport_out.open() as f:
        doc = yaml.safe_load(f)
    assert doc == {"literature_corpus": []}


def test_missing_input_dir_fails_loud(tmp_path):
    r = _run(
        "--input", str(tmp_path / "does-not-exist"),
        "--passport", str(tmp_path / "p.yaml"),
        "--rejection-log", str(tmp_path / "r.yaml"),
    )
    assert r.returncode == 1
    assert "not found" in r.stderr.lower() or "exist" in r.stderr.lower()


def test_deterministic_output(tmp_path, load_yaml, clean_timestamps):
    p1 = tmp_path / "p1.yaml"
    r1_log = tmp_path / "r1.yaml"
    p2 = tmp_path / "p2.yaml"
    r2_log = tmp_path / "r2.yaml"
    _run("--input", str(FIXTURE_DIR), "--passport", str(p1), "--rejection-log", str(r1_log))
    _run("--input", str(FIXTURE_DIR), "--passport", str(p2), "--rejection-log", str(r2_log))
    assert clean_timestamps(load_yaml(p1), _FOLDER_SCAN_EXTRA) == clean_timestamps(
        load_yaml(p2), _FOLDER_SCAN_EXTRA
    )
    assert clean_timestamps(load_yaml(r1_log), _FOLDER_SCAN_EXTRA) == clean_timestamps(
        load_yaml(r2_log), _FOLDER_SCAN_EXTRA
    )


def test_duplicate_collision_handled(tmp_path):
    # Two files that would produce the same base citation_key should each be
    # accepted with a disambiguating suffix.
    dup_dir = tmp_path / "dup"
    dup_dir.mkdir()
    (dup_dir / "Smith2024_alpha.pdf").touch()
    (dup_dir / "Smith2024_beta.pdf").touch()
    passport_out = tmp_path / "p.yaml"
    rej_out = tmp_path / "r.yaml"
    r = _run(
        "--input", str(dup_dir),
        "--passport", str(passport_out),
        "--rejection-log", str(rej_out),
    )
    assert r.returncode == 0
    import yaml
    with passport_out.open() as f:
        doc = yaml.safe_load(f)
    keys = {e["citation_key"] for e in doc["literature_corpus"]}
    assert len(keys) == 2  # no collisions


def test_filename_with_spaces_produces_valid_uri(tmp_path):
    # Codex P1: spaces and reserved chars in filenames must be percent-encoded
    # in source_pointer so it is a valid RFC 8089 file:// URI.
    d = tmp_path / "sp"
    d.mkdir()
    (d / "Lee 2024 paper with spaces.pdf").touch()
    p_out = tmp_path / "p.yaml"
    r_out = tmp_path / "r.yaml"
    r = _run("--input", str(d), "--passport", str(p_out), "--rejection-log", str(r_out))
    assert r.returncode == 0, r.stderr
    import yaml
    with p_out.open() as f:
        doc = yaml.safe_load(f)
    if doc["literature_corpus"]:
        ptr = doc["literature_corpus"][0]["source_pointer"]
        assert ptr.startswith("file://")
        assert " " not in ptr  # raw spaces would be illegal in a URI
        assert "%20" in ptr


def test_chen2024_no_tail_uses_empty_title_hint(tmp_path):
    # Codex P3: empty title_hint exercises make_citation_key fallback path.
    d = tmp_path / "notail"
    d.mkdir()
    (d / "Chen2024.pdf").touch()
    p_out = tmp_path / "p.yaml"
    r_out = tmp_path / "r.yaml"
    r = _run("--input", str(d), "--passport", str(p_out), "--rejection-log", str(r_out))
    assert r.returncode == 0, r.stderr
    import yaml
    with p_out.open() as f:
        doc = yaml.safe_load(f)
    assert len(doc["literature_corpus"]) == 1
    e = doc["literature_corpus"][0]
    assert e["citation_key"] == "chen2024"
    # citation_key must satisfy schema's leading-letter constraint
    assert e["citation_key"][0].isalpha()


def test_mixed_valid_invalid_in_nested_tree(tmp_path):
    # Codex P3: mixed valid+invalid across subdirs. Also covers Codex P2b:
    # rejected entries with the same basename in different subdirs must be
    # distinguishable via a relative-path `source` field.
    root = tmp_path / "root"
    (root / "sub1").mkdir(parents=True)
    (root / "sub2").mkdir(parents=True)
    (root / "Park2022_main.pdf").touch()
    (root / "sub1" / "Lee2021_review.pdf").touch()
    (root / "sub1" / "draft.pdf").touch()
    (root / "sub2" / "draft.pdf").touch()  # same basename, different subdir
    p_out = tmp_path / "p.yaml"
    r_out = tmp_path / "r.yaml"
    r = _run("--input", str(root), "--passport", str(p_out), "--rejection-log", str(r_out))
    assert r.returncode == 0, r.stderr
    import yaml
    with p_out.open() as f:
        passport = yaml.safe_load(f)
    with r_out.open() as f:
        rej = yaml.safe_load(f)
    keys = {e["citation_key"] for e in passport["literature_corpus"]}
    assert keys == {"park2022main", "lee2021review"}
    # Two rejected drafts should each be uniquely identifiable by their source.
    rejected_sources = sorted(r["source"] for r in rej["rejected"])
    assert len(rejected_sources) == 2
    assert len(set(rejected_sources)) == 2, (
        f"basename collisions lost: {rejected_sources}"
    )


def test_symlink_pointing_outside_input_does_not_crash(tmp_path):
    # Symlinks escaping the scanned root can disclose files the user did not
    # intend to include, so they are rejected instead of followed.
    import os
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Smith2024_real.pdf").touch()
    inside = tmp_path / "inside"
    inside.mkdir()
    os.symlink(outside / "Smith2024_real.pdf", inside / "Smith2024_link.pdf")
    p_out = tmp_path / "p.yaml"
    r_out = tmp_path / "r.yaml"
    r = _run("--input", str(inside), "--passport", str(p_out), "--rejection-log", str(r_out))
    assert r.returncode == 0, r.stderr

    import jsonschema
    import yaml
    with p_out.open() as f:
        passport = yaml.safe_load(f)
    with r_out.open() as f:
        rejection = yaml.safe_load(f)
    assert passport == {"literature_corpus": []}
    assert rejection["rejected"] == [{
        "detail": "symlink resolves outside the input root",
        "missing_fields": [],
        "raw": "Smith2024_link.pdf",
        "reason": "other",
        "source": "Smith2024_link.pdf",
    }]
    # The emitted rejection log must satisfy the rejection-log contract, not
    # just be crash-free — a non-enum reason would pass the run but break the
    # schema (Codex follow-up to #310).
    schema = _load_json(
        REPO_ROOT / "shared/contracts/passport/rejection_log.schema.json"
    )
    jsonschema.validate(rejection, schema)


def test_parseable_non_pdf_extension(tmp_path):
    # Codex P3: filename parser is extension-agnostic — non-PDF parseable
    # files should still be accepted (e.g. .epub, .djvu, .ps).
    d = tmp_path / "ext"
    d.mkdir()
    (d / "Kim2020_book.epub").touch()
    p_out = tmp_path / "p.yaml"
    r_out = tmp_path / "r.yaml"
    r = _run("--input", str(d), "--passport", str(p_out), "--rejection-log", str(r_out))
    assert r.returncode == 0, r.stderr
    import yaml
    with p_out.open() as f:
        doc = yaml.safe_load(f)
    assert len(doc["literature_corpus"]) == 1
    assert doc["literature_corpus"][0]["citation_key"] == "kim2020book"


# --- v3.10 venue_type always unknown/unknown (spec §3 PR-B item 13) ---

def test_folder_scan_venue_type_always_unknown(tmp_path, load_yaml):
    """A filename scan carries no structured type → every entry is unknown/unknown,
    never inferred from the filename (R-L3-2-D)."""
    passport_out = tmp_path / "passport.yaml"
    rejection_out = tmp_path / "rejection_log.yaml"
    r = _run(
        "--input", str(FIXTURE_DIR),
        "--passport", str(passport_out),
        "--rejection-log", str(rejection_out),
    )
    assert r.returncode == 0, r.stderr
    got = load_yaml(passport_out)
    entries = got["literature_corpus"]
    assert entries, "fixture should produce at least one accepted entry"
    for e in entries:
        assert e["venue_type"] == "unknown"
        assert e["venue_type_provenance"] == "unknown"

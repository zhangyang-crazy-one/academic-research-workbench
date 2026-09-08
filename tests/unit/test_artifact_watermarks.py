"""Bytes-first diagnostics and deliberately selected Unicode transformations."""

import pytest
from arw_artifact_integrity.inspection import ArtifactIntegrityInspector


def test_families_offsets_and_counts():
    result = ArtifactIntegrityInspector().inspect_bytes(
        "中\u200b\u202e\U000e0061\u00a0".encode()
    )
    assert result.status == "inspected"
    assert result.total_findings == 4
    assert [f.category for f in result.findings] == [
        "invisible",
        "bidi",
        "tag",
        "exotic_space",
    ]
    assert [f.character_offset for f in result.findings] == [1, 2, 3, 4]
    assert result.findings[0].byte_offset == 3
    assert result.detectors["statistical"].status == "unsupported"


def test_output_is_bounded_and_deterministic():
    inspector = ArtifactIntegrityInspector()
    data = ("\u200b" * 1000).encode()
    first = inspector.inspect_bytes(data)
    assert first == inspector.inspect_bytes(data)
    assert first.total_findings == 1000
    assert len(first.findings) == 256 and first.truncated
    assert first.category_counts["invisible"] == 1000
    assert "snippet" not in first.model_dump_json()


def test_explicit_cleanup_preserves_linguistic_and_manuscript_bytes():
    text = "中文\r\nمی\u200cروم 👩\u200d🔬\ufe0f x=3.14 [@Smith2024] \u202aquote\u202c\u200b"
    result = ArtifactIntegrityInspector().sanitize_bytes(
        text.encode(), privacy=True, remove_codepoints=["U+200B"]
    )
    assert result.derived_text == text[:-1]
    assert result.only_selected_changed
    assert result.removed_counts == {"U+200B": 1}
    assert result.after.total_findings > 0


@pytest.mark.parametrize(
    "privacy,selection",
    [(False, ["U+200B"]), (True, []), (True, ["U+0041"]), (True, ["garbage"])],
)
def test_cleanup_requires_authorization_and_supported_selection(privacy, selection):
    with pytest.raises(ValueError):
        ArtifactIntegrityInspector().sanitize_bytes(
            b"text", privacy=privacy, remove_codepoints=selection
        )


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7\n",
        b"PK\x03\x04text",
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",
        b"hello\x00there",
        b"\xff",
        b"{\\rtf1 text}",
    ],
)
def test_unsupported_bytes_never_report_clean(data):
    result = ArtifactIntegrityInspector().inspect_bytes(data)
    assert result.status == "unsupported"
    assert result.detectors["unicode"].status == "unsupported"
    with pytest.raises(ValueError):
        ArtifactIntegrityInspector().sanitize_bytes(
            data, privacy=True, remove_codepoints=["U+200B"]
        )


def test_size_limit_and_unknown_detector():
    inspector = ArtifactIntegrityInspector()
    assert (
        inspector.inspect_bytes(b"a" * (1024 * 1024 + 1)).reason_code
        == "input_too_large"
    )
    assert (
        inspector.inspect_bytes(b"plain", detectors=["invented"])
        .detectors["invented"]
        .status
        == "unsupported"
    )


def test_clean_text_scopes_negative_result():
    result = ArtifactIntegrityInspector().inspect_bytes("中文 x=2 [1]\r\n".encode())
    assert result.detectors["unicode"].status == "not_detected"
    assert result.detectors["c2pa"].status == "unsupported"
    assert result.detectors["exif"].status == "unsupported"


@pytest.mark.parametrize(
    "content",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><metadata>xmp</metadata></svg>',
        b'<?xpacket begin=""?><x:xmpmeta>private metadata</x:xmpmeta>',
    ],
)
def test_utf8_metadata_carriers_never_imply_metadata_absence(content):
    result = ArtifactIntegrityInspector().inspect_bytes(content)
    for name in ("exif", "xmp", "pdf_properties", "docx_properties", "c2pa"):
        assert result.detectors[name].status == "unsupported"


def test_duplicate_detector_requests_cannot_evade_bound():
    with pytest.raises(ValueError, match="excessive"):
        ArtifactIntegrityInspector().inspect_bytes(b"plain", detectors=["unicode"] * 33)

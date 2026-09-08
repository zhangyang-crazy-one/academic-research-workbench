"""Positive, negative and adversarial format qualification using real containers."""

import base64
import io
import json
import struct
import zipfile
import zlib

import pytest
from arw_artifact_integrity.binary import invoke
from arw_artifact_integrity.inspection import ArtifactIntegrityInspector
from arw_artifact_integrity.service import (
    ArtifactIntegrityService,
    ArtifactOperationError,
)

from arw.kernel.state.models import ArtifactAcceptanceRequest

from .test_precise_source_locators import seed
from .test_research_artifacts import request


def box(kind, data):
    return struct.pack(">I4s", len(data) + 8, kind) + data


def manifest():
    return box(
        b"jumb",
        box(b"jumd", bytes.fromhex("6332706100110010800000aa00389b71") + b"\x03c2pa\0"),
    )


def chunk(kind, data):
    return (
        struct.pack(">I4s", len(data), kind)
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><private>author</private></x:xmpmeta>'


def image_bytes(kind, *, provenance=False, orientation=1):
    from PIL import Image

    image = Image.new("RGB", (4, 3), (30, 50, 80))
    exif = Image.Exif()
    exif[315] = "Fixture Author"
    exif[274] = orientation
    output = io.BytesIO()
    image.save(output, format=kind.upper(), exif=exif)
    raw = output.getvalue()
    if kind == "png":
        return (
            raw[:33]
            + chunk(b"iTXt", b"XML:com.adobe.xmp\0\0\0\0\0" + XMP)
            + (chunk(b"caBX", manifest()) if provenance else b"")
            + raw[33:]
        )
    app = b"http://ns.adobe.com/xap/1.0/\0" + XMP
    extra = b"\xff\xe1" + struct.pack(">H", len(app) + 2) + app
    if provenance:
        data = b"JP" + struct.pack(">HI", 1, 1) + manifest()
        extra += b"\xff\xeb" + struct.pack(">H", len(data) + 2) + data
    return raw[:2] + extra + raw[2:]


def document(kind, *, provenance=False, encrypted=False):
    if kind == "docx":
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            )
            z.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>中文 x=2 [1]</w:t></w:r></w:p></w:body></w:document>',
            )
            z.writestr(
                "docProps/core.xml",
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Fixture Author</dc:creator><dc:title>Retained title</dc:title></cp:coreProperties>',
            )
        return out.getvalue()
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        TextStringObject,
    )

    w = PdfWriter()
    page = w.add_blank_page(width=100, height=100)
    content = DecodedStreamObject()
    content.set_data(b"0 0 10 10 re f\n")
    page[NameObject("/Contents")] = w._add_object(content)
    w.add_metadata({"/Author": "Fixture Author", "/Title": "Retained title"})
    xmp = DecodedStreamObject()
    xmp.set_data(XMP)
    w.root_object[NameObject("/Metadata")] = w._add_object(xmp)
    if provenance:
        stream = DecodedStreamObject()
        stream.set_data(manifest())
        stream[NameObject("/Subtype")] = NameObject("/application/c2pa")
        spec = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Filespec"),
                NameObject("/AFRelationship"): NameObject("/C2PA_Manifest"),
                NameObject("/Subtype"): NameObject("/application/c2pa"),
                NameObject("/F"): TextStringObject("manifest.c2pa"),
                NameObject("/EF"): DictionaryObject(
                    {NameObject("/F"): w._add_object(stream)}
                ),
            }
        )
        reference = w._add_object(spec)
        w.root_object[NameObject("/AF")] = ArrayObject([reference])
        w.root_object[NameObject("/Names")] = DictionaryObject(
            {
                NameObject("/EmbeddedFiles"): DictionaryObject(
                    {
                        NameObject("/Names"): ArrayObject(
                            [TextStringObject("manifest.c2pa"), reference]
                        )
                    }
                )
            }
        )
    if encrypted:
        w.encrypt("fixture-password")
    output = io.BytesIO()
    w.write(output)
    return output.getvalue()


@pytest.mark.parametrize("kind", ["png", "jpeg", "docx", "pdf"])
def test_inspect_sanitize_reopen_and_receipt(tmp_path, kind):
    raw = image_bytes(kind) if kind in ("png", "jpeg") else document(kind)
    family = {
        "png": "exif",
        "jpeg": "exif",
        "docx": "docx_properties",
        "pdf": "pdf_properties",
    }[kind]
    report = ArtifactIntegrityInspector().inspect_bytes(raw)
    assert report.status == "inspected", report
    assert report.detectors[family].status == "detected"
    root, _ = seed(tmp_path)
    source = root / ("original." + kind)
    source.write_bytes(raw)
    parent = request(root, 50)
    req = ArtifactAcceptanceRequest.model_validate(
        {
            **parent.model_dump(mode="json"),
            "artifact_id": "artifact.sanitized",
            "artifact_kind": "placeholder",
            "media_type": "application/json",
            "content_path": "placeholder.json",
            "content_sha256": "0" * 64,
            "base_revision": parent.expected_revision,
            "consumed_sha256": [],
        }
    )
    kwargs = {
        "run_root": root,
        "request": req,
        "privacy": True,
        "remove_codepoints": [],
        "treatment": "metadata",
        "remove_metadata": [family],
        "strip_provenance": kind in ("png", "jpeg"),
    }
    service = ArtifactIntegrityService()
    result = service.sanitize(root, source.name, **kwargs)
    assert result["accepted"], result
    assert (
        result["verification"]["body_verified"]
        and result["verification"]["remaining_selected_fields"][family] == 0
    )
    assert source.read_bytes() == raw
    assert service.sanitize(root, source.name, **kwargs)["status"] == "already_accepted"
    body = json.loads((root / result["bundle_path"]).read_text())
    derived = (root / result["export_path"]).read_bytes()
    assert base64.b64decode(body["source"]["base64"]) == raw
    assert base64.b64decode(body["derived"]["base64"]) == derived
    assert ArtifactIntegrityInspector().inspect_bytes(derived).detectors[
        family
    ].status == ("detected" if kind in {"pdf", "docx"} else "not_detected")
    kwargs["privacy"] = False
    with pytest.raises(ArtifactOperationError, match="authorization"):
        service.sanitize(root, source.name, **kwargs)


@pytest.mark.parametrize("kind", ["png", "jpeg", "pdf"])
def test_c2pa_presence_separate_authorization_and_xmp_removal(kind):
    raw = (
        image_bytes(kind, provenance=True)
        if kind != "pdf"
        else document(kind, provenance=True)
    )
    before = invoke(raw)
    assert before["status"] == "ok", before
    assert before["detectors"]["c2pa"]["status"] == "detected"
    assert before["signature_validation"] == "not_performed"
    refused = invoke(raw, ["xmp"], False)
    assert refused["reason"] == "separate_provenance_authorization_required"
    result = invoke(raw, ["xmp"], True)
    assert result["status"] == "ok", result
    assert result["after_counts"]["xmp"] == result["after_counts"]["c2pa"] == 0
    derived = base64.b64decode(result["derived_base64"])
    assert invoke(derived)["detectors"]["c2pa"]["status"] == "not_detected"


@pytest.mark.parametrize(
    "raw", [b"%PDF-1.7\n", b"PK\x03\x04text", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"]
)
def test_malformed_never_clean(raw):
    result = invoke(raw)
    assert result["status"] in ("unknown", "unsupported")


def test_encryption_bomb_crc_and_orientation():
    assert invoke(document("pdf", encrypted=True))["reason"] == "encrypted_container"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "x" * 1_000_000)
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
    assert invoke(out.getvalue())["reason"] == "archive_ratio_limit"
    raw = bytearray(image_bytes("png"))
    raw[-5] ^= 1
    assert invoke(bytes(raw))["reason"] == "png_crc_invalid"
    assert (
        invoke(image_bytes("jpeg", orientation=6), ["exif"], True)["reason"]
        == "orientation_preservation_required"
    )


def test_unavailable_dependency_and_timeout(monkeypatch):
    import subprocess

    from arw_artifact_integrity import binary

    monkeypatch.setattr(
        binary.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 0, b'{"status":"unsupported","reason":"missing_format_dependency"}', b""
        ),
    )
    assert (
        binary.inspect_binary(b"%PDF-1.7").detectors["pdf_properties"].status
        == "unsupported"
    )

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("fixture", 8)

    monkeypatch.setattr(binary.subprocess, "run", timeout)
    assert binary.invoke(b"%PDF-1.7")["reason"] == "parser_timeout_or_invalid_output"

"""Bounded container metadata editing; image codestreams/body parts stay identical.

Invoked in a resource-limited child. No filesystem inputs, network or canonical writes.
"""

import base64
import io
import struct
import zipfile
import zlib
from xml.etree import ElementTree as ET

from arw.kernel.core.canonical import sha256_hex

MAX_EXPANDED = 8 * 1024 * 1024
MAX_PARTS = 512
FAMILIES = ("exif", "xmp", "pdf_properties", "docx_properties", "c2pa")


class FormatFault(ValueError):
    pass


def require(condition, reason="malformed_container"):
    if not condition:
        raise FormatFault(reason)


def xml(raw):
    require(
        len(raw) <= MAX_EXPANDED
        and b"<!DOCTYPE" not in raw.upper()
        and b"<!ENTITY" not in raw.upper(),
        "unsafe_xml",
    )
    return ET.fromstring(raw)


def inflate(raw):
    decoder = zlib.decompressobj()
    result = decoder.decompress(raw, MAX_EXPANDED + 1)
    require(
        len(result) <= MAX_EXPANDED
        and decoder.eof
        and not decoder.unused_data
        and not decoder.unconsumed_tail,
        "decompression_limit",
    )
    return result


def family_result(family, count, applicable=True):
    return {
        "status": ("detected" if count else "not_detected")
        if applicable
        else "unsupported",
        "reason_code": "container_presence_only"
        if applicable
        else "format_not_applicable",
    }


def jumbf_c2pa(raw):
    # Validate top-level JUMBF box and its description box, then the C2PA label.
    require(len(raw) >= 8)
    size, kind = struct.unpack(">I4s", raw[:8])
    require(kind == b"jumb" and size == len(raw))
    offset, descriptions = 8, []
    while offset < len(raw):
        require(offset + 8 <= len(raw))
        length, kind = struct.unpack(">I4s", raw[offset : offset + 8])
        require(length >= 8 and offset + length <= len(raw))
        if kind == b"jumd":
            descriptions.append(raw[offset + 8 : offset + length])
        offset += length
    require(len(descriptions) == 1 and len(descriptions[0]) >= 17)
    desc = descriptions[0]
    require(
        desc[:16] == bytes.fromhex("6332706100110010800000aa00389b71"),
        "unknown_jumbf_uuid",
    )
    # ISO JUMBF toggles bit 1 declares a NUL-terminated label after UUID/toggles.
    if desc[16] & 2:
        require(b"\0" in desc[17:])
        return desc[17:].split(b"\0", 1)[0] == b"c2pa"
    return False


def png(raw, selection, strip):
    require(raw.startswith(b"\x89PNG\r\n\x1a\n"))
    offset, parts, counts = 8, [], {f: 0 for f in FAMILIES}
    image, width, height = [], 0, 0
    while offset < len(raw):
        require(len(parts) < MAX_PARTS and offset + 12 <= len(raw))
        n, kind = struct.unpack(">I4s", raw[offset : offset + 8])
        end = offset + n + 12
        require(end <= len(raw))
        data = raw[offset + 8 : end - 4]
        require(
            zlib.crc32(kind + data) & 0xFFFFFFFF
            == struct.unpack(">I", raw[end - 4 : end])[0],
            "png_crc_invalid",
        )
        if not parts:
            require(kind == b"IHDR" and n == 13)
            width, height = struct.unpack(">II", data[:8])
            require(0 < width * height <= 16_000_000, "pixel_limit")
        family = None
        if kind == b"eXIf":
            require(data[:4] in (b"II*\0", b"MM\0*"), "invalid_exif")
            family = "exif"
        elif kind == b"iTXt":
            fields = data.split(b"\0", 1)
            require(len(fields) == 2)
            if fields[0] == b"XML:com.adobe.xmp":
                rest = fields[1]
                require(len(rest) >= 4)
                flag, method = rest[:2]
                require(flag in (0, 1) and method == 0)
                _language, _translated, payload = rest[2:].split(b"\0", 2)
                xml(inflate(payload) if flag else payload)
                family = "xmp"
        elif kind == b"caBX":
            require(jumbf_c2pa(data), "unknown_jumbf_carrier")
            family = "c2pa"
        if family:
            counts[family] += 1
        if kind in (
            b"IHDR",
            b"PLTE",
            b"IDAT",
            b"tRNS",
            b"IEND",
            b"iCCP",
            b"gAMA",
            b"cHRM",
            b"sRGB",
        ):
            image.append(raw[offset:end])
        parts.append((family, raw[offset:end]))
        offset = end
        if kind == b"IEND":
            require(n == 0 and offset == len(raw))
            break
    require(
        parts and parts[-1][1][4:8] == b"IEND" and any(p[4:8] == b"IDAT" for p in image)
    )
    require(not selection or selection <= {"exif", "xmp"}, "treatment_not_applicable")
    derived = raw[:8] + b"".join(
        p for f, p in parts if f not in selection and not (f == "c2pa" and strip)
    )
    return (
        derived,
        counts,
        sha256_hex(b"".join(image)),
        {
            "pixel_codestream": "byte-identical compressed image/color chunks",
            "width": width,
            "height": height,
        },
        {"exif", "xmp", "c2pa"},
    )


def jpeg(raw, selection, strip):
    require(raw.startswith(b"\xff\xd8"))
    offset, parts, counts = 2, [], {f: 0 for f in FAMILIES}
    image, app11 = [], []
    while offset < len(raw):
        start = offset
        require(raw[offset] == 255)
        while offset < len(raw) and raw[offset] == 255:
            offset += 1
        require(offset < len(raw))
        marker = raw[offset]
        offset += 1
        if marker == 0xD9:
            parts.append((None, raw[start:offset]))
            image.append(raw[start:offset])
            require(offset == len(raw))
            break
        require(marker not in (0, 0xD8) and offset + 2 <= len(raw))
        length = struct.unpack(">H", raw[offset : offset + 2])[0]
        require(length >= 2 and offset + length <= len(raw))
        end = offset + length
        data = raw[offset + 2 : end]
        family = None
        if marker == 0xE1 and data.startswith(b"Exif\0\0"):
            require(data[6:10] in (b"II*\0", b"MM\0*"), "invalid_exif")
            family = "exif"
        elif marker == 0xE1 and data.startswith(b"http://ns.adobe.com/xap/1.0/\0"):
            xml(data.split(b"\0", 1)[1])
            family = "xmp"
        elif marker == 0xE1 and data.startswith(
            b"http://ns.adobe.com/xmp/extension/\0"
        ):
            raise FormatFault("extended_xmp_unsupported")
        elif marker == 0xEB:
            require(len(data) >= 8 and data[:2] == b"JP", "unknown_app11_carrier")
            app11.append(
                (
                    struct.unpack(">H", data[2:4])[0],
                    struct.unpack(">I", data[4:8])[0],
                    data[8:],
                )
            )
            family = "c2pa"
        if family:
            counts[family] += 1
        if marker == 0xDA:
            # Retain entropy bytes verbatim, including stuffed bytes and restart markers.
            scan_end = end
            while scan_end < len(raw) - 1:
                if raw[scan_end] == 255 and raw[scan_end + 1] not in (
                    0,
                    0xFF,
                    *range(0xD0, 0xD8),
                ):
                    break
                scan_end += 1
            require(scan_end < len(raw) - 1)
            end = scan_end
        segment = raw[start:end]
        if family is None:
            image.append(segment)
        parts.append((family, segment))
        offset = end
        require(len(parts) <= MAX_PARTS, "part_limit")
    require(
        parts
        and parts[-1][1].endswith(b"\xff\xd9")
        and any(b"\xff\xda" == p[:2] for _, p in parts)
    )
    if app11:
        require(
            len({x[0] for x in app11}) == 1
            and [x[1] for x in app11] == list(range(1, len(app11) + 1)),
            "fragmented_jumbf_unsupported",
        )
        require(jumbf_c2pa(b"".join(x[2] for x in app11)), "unknown_jumbf_carrier")
    require(not selection or selection <= {"exif", "xmp"}, "treatment_not_applicable")
    derived = raw[:2] + b"".join(
        p for f, p in parts if f not in selection and not (f == "c2pa" and strip)
    )
    return (
        derived,
        counts,
        sha256_hex(b"".join(image)),
        {"pixel_codestream": "byte-identical JPEG coding/entropy segments"},
        {"exif", "xmp", "c2pa"},
    )


def docx(raw, selection, strip):
    counts = {f: 0 for f in FAMILIES}
    private_count = 0
    body = []
    changes = {}
    parts = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(
            len(entries) <= MAX_PARTS
            and sum(e.file_size for e in entries) <= MAX_EXPANDED,
            "archive_limit",
        )
        require(
            len({e.filename for e in entries}) == len(entries),
            "duplicate_archive_entry",
        )
        for info in entries:
            require(not info.flag_bits & 1, "encrypted_container")
            require(
                not info.filename.startswith("/")
                and "\\" not in info.filename
                and ".." not in info.filename.split("/"),
                "unsafe_archive_path",
            )
            require(
                info.file_size <= MAX_EXPANDED
                and info.file_size <= max(info.compress_size, 1) * 200,
                "archive_ratio_limit",
            )
            part = archive.read(info)
            parts[info.filename] = part
            require(len(part) == info.file_size)
        require(
            "[Content_Types].xml" in parts and "word/document.xml" in parts,
            "unsupported_zip",
        )
        types = xml(parts["[Content_Types].xml"])
        document = xml(parts["word/document.xml"])
        require(
            types.tag
            == "{http://schemas.openxmlformats.org/package/2006/content-types}Types"
            and document.tag
            == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document",
            "invalid_docx_structure",
        )
        require(
            any(
                node.get("PartName") == "/word/document.xml"
                and node.get("ContentType")
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                for node in types
            ),
            "invalid_docx_content_type",
        )
        # Unknown signatures/provenance relationships cannot be silently removed.
        require(
            not any(n.startswith("_xmlsignatures/") for n in parts),
            "signed_docx_unsupported",
        )
        for name, part in parts.items():
            if name in {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"}:
                element = xml(part)
                private = [
                    node
                    for node in list(element)
                    if node.tag.rsplit("}", 1)[-1]
                    in {
                        "creator",
                        "lastModifiedBy",
                        "created",
                        "modified",
                        "Company",
                        "Manager",
                    }
                ]
                counts["docx_properties"] += len(element)
                private_count += len(private)
                # Non-private property values are also part of the preservation proof.
                retained = [
                    (
                        node.tag,
                        sorted(node.attrib.items()),
                        ET.tostring(node, encoding="unicode"),
                    )
                    for node in element
                    if node not in private
                ]
                from arw.kernel.core.canonical import canonical_json_bytes

                body.append(name.encode() + b"\0" + canonical_json_bytes(retained))
                if "docx_properties" in selection:
                    for node in private:
                        element.remove(node)
                    changes[name] = ET.tostring(
                        element, encoding="utf-8", xml_declaration=True
                    )
            else:
                body.append(name.encode() + b"\0" + part)
        require(
            not selection or selection <= {"docx_properties"},
            "treatment_not_applicable",
        )
        # DOCX has no qualified embedded C2PA mapping here; report unsupported.
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for info in entries:
                target.writestr(info, changes.get(info.filename, parts[info.filename]))
    return (
        output.getvalue(),
        counts,
        sha256_hex(b"".join(body)),
        {
            "private_property_count": private_count,
            "document_body": "all non-property ZIP members byte-identical; non-private properties retained",
        },
        {"docx_properties"},
    )


PDF_PRIVATE = {"/Author", "/Creator", "/Producer", "/CreationDate", "/ModDate"}


def pdf(raw, selection, strip):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    reader = PdfReader(io.BytesIO(raw), strict=True)
    require(not reader.is_encrypted, "encrypted_container")
    require(len(reader.pages) <= 100, "page_limit")
    # Refuse active content, forms/signatures and embedded files; no silent removal.
    root = reader.trailer["/Root"]
    require(
        not any(k in root for k in ("/AcroForm", "/OpenAction", "/AA", "/Perms")),
        "active_or_signed_pdf_unsupported",
    )
    names = root.get("/Names", {})
    if hasattr(names, "get_object"):
        names = names.get_object()

    def c2pa_spec(value):
        value = value.get_object()
        require(
            value.get("/AFRelationship") == "/C2PA_Manifest", "unknown_pdf_attachment"
        )
        stream = value["/EF"]["/F"]
        require(
            value.get("/Subtype", stream.get("/Subtype"))
            in ("/application/c2pa", "application/c2pa"),
            "unknown_pdf_attachment",
        )
        require(jumbf_c2pa(stream.get_data()), "unknown_pdf_manifest")

    manifests = []
    if "/AF" in root:
        af = root["/AF"]
        manifests = list(af) if isinstance(af, list) else [af]
        for item in manifests:
            c2pa_spec(item)
    if "/EmbeddedFiles" in names:
        tree = names["/EmbeddedFiles"].get_object()
        require(
            "/Kids" not in tree and len(tree.get("/Names", [])) <= 32,
            "pdf_name_tree_unsupported",
        )
        for item in tree.get("/Names", [])[1::2]:
            c2pa_spec(item)
        require(bool(manifests), "unassociated_pdf_attachment")
    counts = {f: 0 for f in FAMILIES}
    counts["c2pa"] = len(manifests)
    counts["pdf_properties"] = len(reader.metadata or {})
    private_count = sum(k in PDF_PRIVATE for k in (reader.metadata or {}))
    counts["xmp"] = int("/Metadata" in root)
    if "/Metadata" in root:
        xml(root["/Metadata"].get_data())

    def fingerprint(document):
        # Recursively resolve page objects; IDs may change when the writer clones.
        budget = [0]
        visiting = set()

        def freeze(obj, depth=0):
            require(depth <= 32, "pdf_graph_depth_limit")
            budget[0] += 1
            require(budget[0] <= 50000, "pdf_object_limit")
            obj = obj.get_object() if hasattr(obj, "get_object") else obj
            ident = id(obj)
            if isinstance(obj, (dict, list)):
                require(ident not in visiting, "pdf_object_cycle")
                visiting.add(ident)
                try:
                    if isinstance(obj, dict):
                        require(
                            "/AF" not in obj and "/AA" not in obj,
                            "object_provenance_or_action_unsupported",
                        )
                        result = {
                            str(k): freeze(v, depth + 1)
                            for k, v in sorted(obj.items())
                            if k not in ("/Parent", "/Length")
                        }
                        if hasattr(obj, "get_data"):
                            # Bound decoded streams via resource-isolated worker.
                            data = obj.get_data()
                            require(len(data) <= MAX_EXPANDED, "pdf_stream_limit")
                            result["__stream_sha256"] = sha256_hex(data)
                        return result
                    return [freeze(v, depth + 1) for v in obj]
                finally:
                    visiting.remove(ident)
            return str(obj)

        from arw.kernel.core.canonical import canonical_json_bytes

        return sha256_hex(canonical_json_bytes([freeze(p) for p in document.pages]))

    digest = fingerprint(reader)
    require(
        not selection or selection <= {"pdf_properties", "xmp"},
        "treatment_not_applicable",
    )
    writer = PdfWriter(clone_from=reader)
    if "pdf_properties" in selection:
        writer.metadata = {
            k: v for k, v in (reader.metadata or {}).items() if k not in PDF_PRIVATE
        }
    if "xmp" in selection:
        writer.root_object.pop(NameObject("/Metadata"), None)
    if strip and manifests:
        writer.root_object.pop(NameObject("/AF"), None)
        if "/Names" in writer.root_object:
            writer.root_object["/Names"].pop(NameObject("/EmbeddedFiles"), None)
    output = io.BytesIO()
    writer.write(output)
    derived = output.getvalue()
    require(
        fingerprint(PdfReader(io.BytesIO(derived), strict=True)) == digest,
        "pdf_body_changed",
    )
    return (
        derived,
        counts,
        digest,
        {
            "pages": len(reader.pages),
            "private_property_count": private_count,
            "document_body": "resolved page dictionaries/resources and decoded stream digests unchanged",
        },
        {"pdf_properties", "xmp", "c2pa"},
    )


def pixels(raw, removing_exif=False):
    import warnings

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 16_000_000
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with Image.open(io.BytesIO(raw), formats=("PNG", "JPEG")) as image:
            require(
                image.width * image.height <= 16_000_000
                and getattr(image, "n_frames", 1) == 1,
                "pixel_or_frame_limit",
            )
            exif = image.getexif()
            list(exif.items())
            if removing_exif:
                require(exif.get(274, 1) == 1, "orientation_preservation_required")
            image.load()
            return sha256_hex(image.convert("RGBA").tobytes()), image.size


def process(raw, *, selection=(), strip=False):
    require(len(raw) <= 1024 * 1024, "input_too_large")
    selection = set(selection)
    require(selection <= set(FAMILIES) - {"c2pa"}, "unsupported_metadata_selection")
    kind = (
        "pdf"
        if raw.startswith(b"%PDF-")
        else "docx"
        if raw.startswith(b"PK")
        else "png"
        if raw.startswith(b"\x89PNG")
        else "jpeg"
        if raw.startswith(b"\xff\xd8")
        else None
    )
    require(kind is not None, "unsupported_container")
    parser = {"pdf": pdf, "docx": docx, "png": png, "jpeg": jpeg}[kind]
    derived, counts, body, details, applicable = parser(raw, selection, strip)
    if kind in {"png", "jpeg"}:
        pixel_digest, dimensions = pixels(raw, "exif" in selection)
        require(pixels(derived)[0] == pixel_digest, "decoded_pixels_changed")
        details.update(
            decoded_pixels_sha256=pixel_digest,
            width=dimensions[0],
            height=dimensions[1],
        )
    if selection:
        # Whole EXIF/XMP blocks may contain attribution/provenance, independent of C2PA.
        require(
            strip or not ((selection & {"exif", "xmp"}) or counts["c2pa"]),
            "separate_provenance_authorization_required",
        )
        require(
            any(
                details.get("private_property_count", 0)
                if f in {"pdf_properties", "docx_properties"}
                else counts[f]
                for f in selection
            )
            or (strip and counts["c2pa"]),
            "selected_metadata_not_found",
        )
        require(len(derived) <= 1024 * 1024, "output_too_large")
        _, after, after_body, after_details, _ = parser(derived, set(), False)
        require(after_body == body, "binary_body_changed")
        remaining = {
            f: after_details.get("private_property_count", 0)
            if f in {"pdf_properties", "docx_properties"}
            else after[f]
            for f in selection
        }
        require(all(value == 0 for value in remaining.values()), "metadata_remains")
        require(not strip or after["c2pa"] == 0, "provenance_remains")
    else:
        derived = raw
        after = counts
        remaining = {}
    from importlib.metadata import version

    versions = {
        name: version(name)
        for name in (
            ("pypdf",)
            if kind == "pdf"
            else ("Pillow",)
            if kind in {"png", "jpeg"}
            else ()
        )
    }
    return {
        "dependency_versions": versions,
        "format": kind,
        "detectors": {
            f: family_result(f, counts[f], f in applicable) for f in FAMILIES
        },
        "counts": counts,
        "body_sha256": body,
        "verification": details,
        "derived_base64": base64.b64encode(derived).decode(),
        "after_counts": after,
        "remaining_selected_fields": remaining,
        "selected_metadata": sorted(selection),
        "strip_provenance": strip,
        "signature_validation": "not_performed",
        "body_verified": True,
    }

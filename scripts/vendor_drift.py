"""Read-only upstream release observations and bounded drift reports.

Source commits in the manifest are provenance identities, not Python dependency pins.
Commit ancestry is used because the ARS manifest version is the adapter
version (0.1.27), not the upstream suite's v3.x release number. Only commit
list metadata is requested; the compare endpoint would include source patches.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

SOURCES = {
    "academic-research-skills": "Imbad0202/academic-research-skills",
    "file-base": "DeusData/codebase-memory-mcp",
}
MARKER = "<!-- arw:upstream-drift:v1 -->"
TITLE = "upstream-drift: pinned source releases"
TAG = re.compile(r"v?\d+\.\d+\.\d+$")
SHA = re.compile(r"[0-9a-f]{40}$")
KEYWORDS = ("security", "cve", "vulnerability", "citation", "license", "sandbox")
MAX_NOTES = 500
MAX_BODY = 5000
MAX_API_RESPONSE = 10_000_000
MAX_HISTORY_PAGES = 30


def sources(source_manifest: dict, mcp_manifest: dict) -> list[dict]:
    components = source_manifest["components"]
    result = []
    for component_id, repo in SOURCES.items():
        matches = [item for item in components if item.get("id") == component_id]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {component_id} source")
        item = matches[0]
        url = f"https://github.com/{repo}.git"
        revision = item.get("revision")
        if (
            item.get("upstream_url") != url
            or not isinstance(revision, str)
            or not SHA.fullmatch(revision)
        ):
            raise ValueError(f"unexpected {component_id} source identity")
        if component_id == "file-base" and (
            mcp_manifest.get("arw_component_id") != component_id
            or mcp_manifest.get("upstream_url") != url
            or mcp_manifest.get("upstream_commit") != revision
        ):
            raise ValueError("file-base MCP/source manifests disagree")
        result.append(
            {
                "id": component_id,
                "repository": repo,
                "revision": revision,
                "manifest_version": str(item.get("version", ""))[:40],
                "source_url": f"https://github.com/{repo}/commit/{revision}",
            }
        )
    return result


def clean_text(value: object, limit: int = MAX_NOTES) -> str:
    if not isinstance(value, str):
        return ""
    value = "".join(
        ch
        for ch in value
        if ch.isprintable()
        and ch not in "\u202a\u202b\u202d\u202e\u2066\u2067\u2068\u2069"
    )
    value = " ".join(value.split())[:limit]
    value = html.escape(value, quote=True).replace("@", "＠")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)[:limit]


def report(source_manifest: dict, mcp_manifest: dict, observations: dict) -> dict:
    rows = []
    for source in sources(source_manifest, mcp_manifest):
        component_id = source["id"]
        observed = observations.get(component_id, {})
        release = observed.get("release") if isinstance(observed, dict) else None
        compare = observed.get("compare") if isinstance(observed, dict) else None
        reason = (
            "query_error"
            if isinstance(observed, dict) and observed.get("error") == "query_error"
            else "metadata_unavailable"
        )
        row = {**source, "status": "unknown", "reason": reason}
        if isinstance(release, dict):
            tag = release.get("tag_name")
            if (
                release.get("draft") is False
                and release.get("prerelease") is False
                and isinstance(tag, str)
                and TAG.fullmatch(tag)
            ):
                row["release_tag"] = tag
                row["release_url"] = (
                    f"https://github.com/{source['repository']}/releases/tag/{tag}"
                )
                date = release.get("published_at")
                row["published_at"] = (
                    date
                    if isinstance(date, str)
                    and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", date)
                    else "unknown"
                )
                row["summary"] = clean_text(release.get("body"))
                lower = str(release.get("body", ""))[:10000].lower()
                row["keyword_hits"] = [
                    word for word in KEYWORDS if re.search(rf"\b{word}\b", lower)
                ]
                if isinstance(compare, dict) and compare.get("status") in (
                    "ahead",
                    "identical",
                    "behind",
                ):
                    row["status"] = (
                        "drift" if compare["status"] == "ahead" else "current"
                    )
                    row.pop("reason")
                elif isinstance(compare, dict) and compare.get("status") == "diverged":
                    row["reason"] = "release_diverged_from_source"
                else:
                    row["reason"] = "comparison_unavailable"
            else:
                row["reason"] = "no_stable_release"
        rows.append(row)
    result = {
        "schema": "arw.vendor-drift.v1",
        "has_drift": any(row["status"] == "drift" for row in rows),
        "sources": rows,
    }
    result["issue_body"] = issue_body(result)
    return result


def issue_body(result: dict) -> str:
    lines = [
        MARKER,
        "# Upstream source drift",
        "",
        "Observed release metadata only. Vendor admission requires explicit source, license, patch, manifest, and qualification review.",
        "",
    ]
    for row in result["sources"]:
        lines += [
            f"## {row['repository']}",
            f"- Status: {row['status']}",
            f"- Declared source: [{row['revision']}]({row['source_url']}) (manifest version: {clean_text(row['manifest_version'], 40)})",
        ]
        if "release_tag" in row:
            lines += [
                f"- Stable release: [{row['release_tag']}]({row['release_url']}) ({row['published_at']})"
            ]
        if "reason" in row:
            lines += [f"- Reason: {row['reason']}"]
        if row.get("keyword_hits"):
            lines += [
                f"- Keyword hits (screening only): {', '.join(row['keyword_hits'])}"
            ]
        if row.get("summary"):
            lines += [f"- Release notes excerpt: {row['summary']}"]
        lines.append("")
    body = "\n".join(lines)
    if len(body) > MAX_BODY:
        raise ValueError("drift report exceeds issue body cap")
    return body


def get_json(url: str, token: str = "") -> dict:
    value = get_api(url, token)
    if not isinstance(value, dict):
        raise TypeError("unexpected API response")
    return value


def get_api(url: str, token: str = "") -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "arw-vendor-drift/1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        data = response.read(MAX_API_RESPONSE + 1)
    if len(data) > MAX_API_RESPONSE:
        raise ValueError("API response exceeds cap")
    value = json.loads(data)
    if not isinstance(value, (dict, list)):
        raise TypeError("unexpected API response")
    return value


def history(
    base: str, ref: str, target: str, token: str
) -> tuple[bool, bool, str | None]:
    """Return (found, first-is-target, head SHA), capped at 3000 commits."""
    head = None
    for page in range(1, MAX_HISTORY_PAGES + 1):
        commits = get_api(f"{base}/commits?sha={ref}&per_page=100&page={page}", token)
        if not isinstance(commits, list):
            raise TypeError("unexpected commit list")
        for index, item in enumerate(commits):
            sha = item.get("sha") if isinstance(item, dict) else None
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise ValueError("invalid commit identity")
            if head is None:
                head = sha
            if sha == target:
                return True, page == 1 and index == 0, head
        if len(commits) < 100:
            break
    return False, False, head


def ancestry_status(base: str, revision: str, tag: str, token: str) -> str | None:
    found, identical, release_head = history(base, tag, revision, token)
    if found:
        return "identical" if identical else "ahead"
    if release_head is None:
        return None
    found, _, _ = history(base, revision, release_head, token)
    return "behind" if found else None


def online_observations(
    source_manifest: dict, mcp_manifest: dict, token: str = ""
) -> dict:
    observations = {}
    for source in sources(source_manifest, mcp_manifest):
        base = f"https://api.github.com/repos/{source['repository']}"
        try:
            release = get_json(f"{base}/releases/latest", token)
            tag = release.get("tag_name")
            compare = None
            if (
                release.get("draft") is False
                and release.get("prerelease") is False
                and isinstance(tag, str)
                and TAG.fullmatch(tag)
            ):
                status = ancestry_status(base, source["revision"], tag, token)
                compare = {"status": status} if status else None
            observations[source["id"]] = {"release": release, "compare": compare}
        except (urllib.error.URLError, TimeoutError, ValueError, TypeError):
            observations[source["id"]] = {"error": "query_error"}
    return observations


def load_manifests(root: Path) -> tuple[dict, dict]:
    return (
        json.loads((root / "vendor/source-manifest.json").read_text(encoding="utf-8")),
        json.loads((root / "vendor/mcp-manifest.json").read_text(encoding="utf-8")),
    )

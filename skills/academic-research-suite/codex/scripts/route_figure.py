#!/usr/bin/env python3
"""Plan role-scoped figure instructions; never render or admit evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "references/figure_role_rules.json"
MAX_BYTES = 65536
REQUIRED = {
    "role",
    "visual_argument",
    "scientific_objects",
    "relationship",
    "target_mm",
    "font_family",
    "backend",
    "requires",
}
OPTIONAL = {
    "strict_box",
    "style_profile",
    "depth",
    "depth_source",
    "panels",
    "venue_format",
    "internal_title",
}


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError(f"invalid_{label}")
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def read_brief(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("brief_too_large")
    return json.loads(raw, object_pairs_hook=_unique)


def route_figure(brief, *, _child=False):
    if (
        not isinstance(brief, dict)
        or REQUIRED - brief.keys()
        or brief.keys() - REQUIRED - OPTIONAL
    ):
        raise ValueError("invalid_brief_fields")
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    role = brief["role"]
    if role not in matrix["roles"] or (_child and role == "composite"):
        raise ValueError("invalid_figure_role")
    for key in ("visual_argument", "relationship", "font_family", "backend"):
        _text(brief[key], key)
    objects = brief["scientific_objects"]
    if not isinstance(objects, list) or not 1 <= len(objects) <= 40:
        raise ValueError("invalid_scientific_objects")
    for item in objects:
        _text(item, "scientific_object")
    size = brief["target_mm"]
    if (
        not isinstance(size, dict)
        or set(size) != {"width", "height"}
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 20 <= v <= 500
            for v in size.values()
        )
    ):
        raise ValueError("invalid_physical_size")
    requested = brief["requires"]
    if (
        not isinstance(requested, list)
        or len(requested) > 30
        or any(not isinstance(v, str) or not v for v in requested)
    ):
        raise ValueError("invalid_capabilities")
    if type(brief.get("strict_box", False)) is not bool:
        raise ValueError("invalid_strict_box")
    if type(brief.get("internal_title", False)) is not bool:
        raise ValueError("invalid_internal_title")
    style = brief.get("style_profile", "content_led")
    if style not in {"content_led", "flat_minimal_muted"}:
        raise ValueError("invalid_style_profile")
    depth = brief.get("depth", "none")
    if depth not in {"none", "spatial_mechanism", "comparison_perspective"}:
        raise ValueError("invalid_depth")
    if depth == "spatial_mechanism":
        _text(brief.get("depth_source"), "depth_source")
    children = brief.get("panels", [])
    if (
        not isinstance(children, list)
        or (role == "composite" and not 2 <= len(children) <= 4)
        or (role != "composite" and children)
    ):
        raise ValueError("invalid_panels")
    rules = dict(matrix["common"])
    rules.update(matrix["roles"][role])
    if brief.get("internal_title", False):
        rules["caption_boundary"] = (
            "The author explicitly selected an internal figure title; keep it manuscript-safe and do not claim venue approval."
        )
    if brief.get("strict_box"):
        rules["strict_box"] = matrix["optional"]["strict_box"]
    if style == "flat_minimal_muted":
        rules[style] = matrix["optional"][style]
    all_rules = set(matrix["optional"])
    for group in matrix["roles"].values():
        all_rules.update(group)
    backend = matrix["backends"].get(brief["backend"])
    needs = set(requested)
    if role == "composite":
        needs.add("multi_panel")
    if depth != "none":
        needs.add("spatial_depth")
    if brief.get("strict_box"):
        needs.add("strict_box")
    if brief.get("internal_title", False):
        needs.add("internal_title")
    gaps = needs - set(backend["capabilities"] if backend else [])
    if backend is None or role not in backend["roles"]:
        gaps.add("role_backend")
    if backend is None or brief["font_family"] != backend["font_family"]:
        gaps.add("font_family")
    conflicts = []
    if role == "quantitative" and depth == "comparison_perspective":
        conflicts.append("misleading_quantitative_perspective")
    venue = brief.get("venue_format")
    if venue is not None:
        if (
            not isinstance(venue, dict)
            or set(venue) != {"source", "checked_at", "font_family", "internal_title"}
            or type(venue["internal_title"]) is not bool
        ):
            raise ValueError("invalid_venue_format")
        for key in ("source", "checked_at", "font_family"):
            _text(venue[key], "venue_" + key)
        # A supplied source/date is not independent verification authority.
        conflicts.append("venue_reference_requires_verification")
        if venue["font_family"] != brief["font_family"] or venue[
            "internal_title"
        ] != brief.get("internal_title", False):
            conflicts.append("format_conflict_requires_resolution")
    panel_routes = [route_figure(child, _child=True) for child in children]
    if any(c["status"] != "backend_supported" for c in panel_routes):
        gaps.add("child_backend")
    return {
        "routing_version": matrix["version"],
        "role": role,
        "status": "blocked"
        if conflicts
        else ("unavailable" if gaps else "backend_supported"),
        "brief": brief,
        "priority": matrix["priority"],
        "rules": rules,
        "excluded_rules": sorted(all_rules - rules.keys()),
        "format": {
            "font_family": brief["font_family"],
            "internal_figure_title": brief.get("internal_title", False),
            "target_mm": size,
        },
        "backend": brief["backend"],
        "backend_contract": backend,
        "capability_gaps": sorted(gaps),
        "conflicts": conflicts,
        "panels": panel_routes,
        "rendered": False,
        "scientific_admission": "not_evaluated",
        "visual_acceptance": "not_evaluated",
        "load": ["codex/references/figure_role_routing.md"],
        "excluded_global_checklists": [
            "visualization_agent.All Figures",
            "ai_scientific_image_generation.generic_style_defaults",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = route_figure(read_brief(args.brief))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "error", "code": str(error)}))
        return 65
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

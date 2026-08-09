#!/usr/bin/env python3
"""Validate the source-audited annual venue profile registry."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT = Path(__file__).resolve()
DEFAULT_PROFILE = SCRIPT.parents[1] / "references" / "annual_venue_profiles.json"
DATE_STATUSES = {"confirmed", "provisional", "not_announced"}
PROFILE_KINDS = {"review_system", "publication_venue"}
MILESTONE_SOURCE_AUTHORITIES = {"official_venue_year", "official_review_system"}
STYLE_EXEMPLAR_ROLES = {
    "direct_writing_and_method_exemplar",
    "supporting_exemplar",
    "adjacent_presentation_only_not_baseline",
}
EDITORIAL_PRECEDENCE = [
    "official_target_venue_requirements",
    "topic_matched_full_text_accepted_paper_audit",
    "generic_cross_venue_heuristic",
]
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _source_refs(
    value: Any, path: str, known_sources: set[str], errors: list[str]
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "source_id":
                if not isinstance(child, str):
                    errors.append(f"{child_path}: must be a string")
                elif child not in known_sources:
                    errors.append(f"{child_path}: unknown source {child!r}")
            elif key == "source_ids":
                if not isinstance(child, list) or not child:
                    errors.append(f"{child_path}: must be a non-empty list")
                else:
                    for index, source_id in enumerate(child):
                        source_path = f"{child_path}[{index}]"
                        if not isinstance(source_id, str):
                            errors.append(f"{source_path}: must be a string")
                        elif source_id not in known_sources:
                            errors.append(
                                f"{source_path}: unknown source {source_id!r}"
                            )
            else:
                _source_refs(child, child_path, known_sources, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _source_refs(child, f"{path}[{index}]", known_sources, errors)


def _validate_milestones(
    profile: dict[str, Any],
    path: str,
    sources: dict[str, Any],
    errors: list[str],
) -> None:
    milestones = profile.get("milestones")
    if not isinstance(milestones, dict) or not milestones:
        errors.append(f"{path}.milestones: must be a non-empty object")
        return

    for name, milestone in milestones.items():
        milestone_path = f"{path}.milestones.{name}"
        if not isinstance(milestone, dict):
            errors.append(f"{milestone_path}: must be an object")
            continue
        status = milestone.get("status")
        if status not in DATE_STATUSES:
            errors.append(f"{milestone_path}.status: invalid status {status!r}")
        milestone_date = milestone.get("date")
        if status in {"confirmed", "provisional"} and not _is_iso_date(milestone_date):
            errors.append(
                f"{milestone_path}.date: confirmed/provisional dates must use YYYY-MM-DD"
            )
        if status == "not_announced" and milestone_date is not None:
            errors.append(f"{milestone_path}.date: not_announced must use null")
        milestone_time = milestone.get("time")
        if milestone_time is not None and (
            not isinstance(milestone_time, str) or not TIME_RE.fullmatch(milestone_time)
        ):
            errors.append(f"{milestone_path}.time: must be HH:MM or null")
        if milestone_time is not None and not milestone.get("timezone"):
            errors.append(f"{milestone_path}.timezone: required when time is present")
        source_id = milestone.get("source_id")
        if not isinstance(source_id, str):
            errors.append(f"{milestone_path}.source_id: must be a string")
            continue
        source = sources.get(source_id)
        if not isinstance(source, dict):
            errors.append(f"{milestone_path}.source_id: unknown source {source_id!r}")
        elif (
            status in {"confirmed", "provisional"}
            and source.get("authority") not in MILESTONE_SOURCE_AUTHORITIES
        ):
            errors.append(
                f"{milestone_path}.source_id: dated milestones require an official "
                "venue-year or review-system schedule source"
            )


def validate_document(document: dict[str, Any]) -> list[str]:
    """Return validation errors without mutating *document*."""

    errors: list[str] = []
    if document.get("schema_version") != "1.0":
        errors.append("schema_version: expected '1.0'")
    if not _is_iso_date(document.get("verified_on")):
        errors.append("verified_on: expected an ISO date")

    precedence = document.get("source_precedence")
    required_prefix = ["official_venue_year_page", "official_review_system_page"]
    if not isinstance(precedence, list) or precedence[:2] != required_prefix:
        errors.append(
            "source_precedence: venue-year official source must precede review-system source"
        )

    refresh_policy = document.get("refresh_policy", {})
    if refresh_policy.get("always_recheck_before_submission") is not True:
        errors.append(
            "refresh_policy: submission-time official recheck must be required"
        )
    max_age = refresh_policy.get("max_age_days_for_planning")
    if not isinstance(max_age, int) or max_age <= 0:
        errors.append(
            "refresh_policy.max_age_days_for_planning: expected a positive integer"
        )

    sources = document.get("sources")
    if not isinstance(sources, dict) or not sources:
        errors.append("sources: must be a non-empty object")
        sources = {}
    for source_id, source in sources.items():
        path = f"sources.{source_id}"
        if not isinstance(source, dict):
            errors.append(f"{path}: must be an object")
            continue
        parsed = urlparse(str(source.get("url", "")))
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"{path}.url: expected an HTTPS URL")
        if not source.get("authority"):
            errors.append(f"{path}.authority: required")
        if not _is_iso_date(source.get("accessed_on")):
            errors.append(f"{path}.accessed_on: expected an ISO date")

    profiles: list[tuple[str, dict[str, Any], str]] = []
    for collection in ("review_systems", "venues"):
        values = document.get(collection)
        if not isinstance(values, list) or not values:
            errors.append(f"{collection}: must be a non-empty list")
            continue
        for index, profile in enumerate(values):
            path = f"{collection}[{index}]"
            if not isinstance(profile, dict):
                errors.append(f"{path}: must be an object")
                continue
            profile_id = profile.get("id")
            if not isinstance(profile_id, str) or not profile_id:
                errors.append(f"{path}.id: required")
                continue
            profiles.append((profile_id, profile, path))

    ids = [profile_id for profile_id, _, _ in profiles]
    duplicate_ids = sorted(
        {profile_id for profile_id in ids if ids.count(profile_id) > 1}
    )
    if duplicate_ids:
        errors.append(f"profiles: duplicate ids: {', '.join(duplicate_ids)}")
    known_profiles = set(ids)

    for profile_id, profile, path in profiles:
        if profile.get("kind") not in PROFILE_KINDS:
            errors.append(f"{path}.kind: invalid profile kind")
        _validate_milestones(profile, path, sources, errors)
        contract = profile.get("format_contract")
        if not isinstance(contract, dict):
            errors.append(f"{path}.format_contract: required")
            continue
        mode = contract.get("mode")
        if mode == "inherit":
            parent = contract.get("review_system_id")
            if parent not in known_profiles:
                errors.append(
                    f"{path}.format_contract.review_system_id: unknown parent {parent!r}"
                )
            if profile.get("review_system_id") != parent:
                errors.append(f"{path}: inherited review-system identifiers disagree")
        elif mode == "direct":
            if not contract.get("template_family"):
                errors.append(f"{path}.format_contract.template_family: required")
            if contract.get("template_source_id") not in sources:
                errors.append(
                    f"{path}.format_contract.template_source_id: unknown template source"
                )
        else:
            errors.append(
                f"{path}.format_contract.mode: expected 'inherit' or 'direct'"
            )

    _source_refs(document, "$", set(sources), errors)

    by_id = {profile_id: profile for profile_id, profile, _ in profiles}
    arr = by_id.get("arr-2026-october", {})
    coling = by_id.get("coling-2027", {})
    naacl = by_id.get("naacl-2027", {})
    ecir = by_id.get("ecir-2027-full", {})
    if arr.get("milestones", {}).get("submission", {}).get("date") != "2026-10-12":
        errors.append("arr-2026-october: expected audited submission date 2026-10-12")
    if coling.get("milestones", {}).get("commitment", {}).get("date") != "2026-12-23":
        errors.append("coling-2027: venue-specific commitment date must be 2026-12-23")
    if (
        coling.get("milestones", {}).get("commitment", {}).get("source_id")
        != "coling-2027-home"
    ):
        errors.append(
            "coling-2027: commitment must cite the venue-year official source"
        )
    if (
        naacl.get("milestones", {}).get("commitment", {}).get("status")
        != "not_announced"
    ):
        errors.append("naacl-2027: unannounced commitment date must remain explicit")
    if (
        ecir.get("milestones", {}).get("paper_submission", {}).get("date")
        != "2026-10-05"
    ):
        errors.append("ecir-2027-full: expected audited paper deadline 2026-10-05")

    routing = document.get("project_routing")
    if not isinstance(routing, dict):
        errors.append("project_routing: required")
    else:
        expected_routes = {
            "primary": "coling-2027",
            "same_cycle_alternative": "naacl-2027",
            "conditional_backup": "ecir-2027-full",
        }
        for route_name, expected_id in expected_routes.items():
            route = routing.get(route_name, {})
            if route.get("venue_id") != expected_id:
                errors.append(f"project_routing.{route_name}: expected {expected_id}")

    style_learning = document.get("style_learning")
    if not isinstance(style_learning, dict):
        errors.append("style_learning: required")
    else:
        if style_learning.get("status") != "non_normative_editorial_inference":
            errors.append("style_learning.status: must remain non-normative")
        if style_learning.get("editorial_precedence") != EDITORIAL_PRECEDENCE:
            errors.append(
                "style_learning.editorial_precedence: expected official requirements, "
                "topic-matched full-text audit, then generic heuristic"
            )
        exemplar_roles: dict[str, str] = {}
        exemplars = style_learning.get("exemplars")
        if not isinstance(exemplars, list) or len(exemplars) < 2:
            errors.append(
                "style_learning.exemplars: at least two sourced papers are required"
            )
        else:
            exemplar_ids: list[str] = []
            for index, exemplar in enumerate(exemplars):
                source_id = (
                    exemplar.get("source_id") if isinstance(exemplar, dict) else None
                )
                if isinstance(source_id, str):
                    exemplar_ids.append(source_id)
                source = (
                    sources.get(source_id, {}) if isinstance(source_id, str) else {}
                )
                if source.get("authority") != "official_published_paper":
                    errors.append(
                        f"style_learning.exemplars[{index}]: expected an official published-paper source"
                    )
                role = exemplar.get("role") if isinstance(exemplar, dict) else None
                if role not in STYLE_EXEMPLAR_ROLES:
                    errors.append(
                        f"style_learning.exemplars[{index}].role: invalid role {role!r}"
                    )
                elif isinstance(source_id, str):
                    exemplar_roles[source_id] = role
            duplicate_exemplars = sorted(
                {
                    source_id
                    for source_id in exemplar_ids
                    if exemplar_ids.count(source_id) > 1
                }
            )
            if duplicate_exemplars:
                errors.append(
                    "style_learning.exemplars: duplicate source ids: "
                    + ", ".join(duplicate_exemplars)
                )

        boundary = style_learning.get("direct_vs_adjacent")
        if not isinstance(boundary, dict):
            errors.append("style_learning.direct_vs_adjacent: required")
        else:
            direct = boundary.get("direct_exemplars")
            adjacent = boundary.get("adjacent_not_direct_baselines")
            valid_direct = (
                isinstance(direct, list)
                and bool(direct)
                and all(isinstance(source_id, str) for source_id in direct)
            )
            valid_adjacent = (
                isinstance(adjacent, list)
                and bool(adjacent)
                and all(isinstance(source_id, str) for source_id in adjacent)
            )
            if not valid_direct:
                errors.append(
                    "style_learning.direct_vs_adjacent.direct_exemplars: "
                    "expected a non-empty list of source ids"
                )
            if not valid_adjacent:
                errors.append(
                    "style_learning.direct_vs_adjacent.adjacent_not_direct_baselines: "
                    "expected a non-empty list of source ids"
                )
            if valid_direct and valid_adjacent:
                overlap = sorted(set(direct) & set(adjacent))
                if overlap:
                    errors.append(
                        "style_learning.direct_vs_adjacent: direct and adjacent sets overlap: "
                        + ", ".join(overlap)
                    )
                for source_id in direct:
                    if (
                        exemplar_roles.get(source_id)
                        != "direct_writing_and_method_exemplar"
                    ):
                        errors.append(
                            "style_learning.direct_vs_adjacent.direct_exemplars: "
                            f"{source_id!r} must name a direct exemplar"
                        )
                for source_id in adjacent:
                    if (
                        exemplar_roles.get(source_id)
                        != "adjacent_presentation_only_not_baseline"
                    ):
                        errors.append(
                            "style_learning.direct_vs_adjacent.adjacent_not_direct_baselines: "
                            f"{source_id!r} must name an adjacent non-baseline exemplar"
                        )

        artifact_contract = style_learning.get("artifact_contract")
        if not isinstance(artifact_contract, dict):
            errors.append("style_learning.artifact_contract: required")
        else:
            figure_sequence = artifact_contract.get("default_figure_sequence")
            if not isinstance(figure_sequence, list) or len(figure_sequence) != 2:
                errors.append(
                    "style_learning.artifact_contract.default_figure_sequence: "
                    "expected the two-figure task-then-method sequence"
                )
            required_settings = {
                "fully_unseen_labels",
                "partially_seen_labels",
                "cross_domain",
            }
            settings = artifact_contract.get("main_result_settings")
            if (
                not isinstance(settings, list)
                or not all(isinstance(setting, str) for setting in settings)
                or not required_settings.issubset(set(settings))
            ):
                errors.append(
                    "style_learning.artifact_contract.main_result_settings: "
                    "must separate fully unseen, partially seen, and cross-domain settings"
                )

    return errors


def validate_path(path: Path = DEFAULT_PROFILE) -> list[str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: {exc}"]
    if not isinstance(document, dict):
        return [f"{path}: top-level JSON value must be an object"]
    return validate_document(document)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    args = parser.parse_args()

    errors = validate_path(args.path)
    result = {"ok": not errors, "path": str(args.path), "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif errors:
        for error in errors:
            print(f"FAIL {error}")
    else:
        print(f"OK annual venue profiles: {args.path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Keep the installed STORM skill aligned with the explicit-provider CLI."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills/academic-research-workbench/SKILL.md"


def test_storm_examples_use_explicit_provider_and_named_environment_key() -> None:
    document = SKILL.read_text(encoding="utf-8")
    examples = [
        shlex.split(line)
        for line in document.splitlines()
        if line.startswith('"<installed-plugin-root>/bin/arw" storm ')
    ]
    assert len(examples) == 3
    for args in examples:
        provider = args[args.index("--provider") + 1]
        model = args[args.index("--model") + 1]
        key_env = args[args.index("--api-key-env") + 1]
        assert provider in {"openai", "gemini", "openai-compatible"}
        assert model.startswith("gemini/" if provider == "gemini" else "openai/")
        assert re.fullmatch(r"[A-Z_][A-Z0-9_]*", key_env)
        if provider == "openai-compatible":
            assert args[args.index("--api-base") + 1].startswith("https://")
        else:
            assert "--api-base" not in args
    assert {args[args.index("--provider") + 1] for args in examples} == {
        "openai", "gemini", "openai-compatible"
    }
    assert "TAVILY_API_KEY" in document
    assert "--retriever duckduckgo" in document


def test_storm_skill_does_not_recommend_legacy_credentials_or_endpoint() -> None:
    document = SKILL.read_text(encoding="utf-8")
    assert not re.search(r"--backend\s+session\b", document)
    assert not re.search(r"(?<![\w-])--api-key(?=\s|=|$)", document, re.MULTILINE)
    for legacy_reference in (
        "session credential",
        "credential-store",
        "auth.json",
        "chatgpt.com/backend-api",
    ):
        assert legacy_reference not in document.lower()

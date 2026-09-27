"""Optional STORM deep-research integration.

STORM (https://github.com/stanford-oval/storm) is a retrieval-grounded
Wikipedia-style article synthesis pipeline.  ARW exposes it as an explicit
opt-in command for experiment planning and deep-thinking passes: it is never
part of the default route, never touches the run ledger, and only writes into
an operator-chosen output directory.

Model access requires an explicitly selected provider. Credentials come from
named environment variables and are never persisted. Retrieval defaults to
Tavily (official STORM retriever) with DuckDuckGo as a keyless fallback.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RETRIEVERS = Literal["tavily", "duckduckgo"]
PROVIDERS = Literal["openai", "gemini", "openai-compatible"]
_PROVIDER_DEFAULTS = {
    "openai": ("openai/gpt-4o-mini", "OPENAI_API_KEY"),
    "gemini": ("gemini/gemini-2.5-flash", "GEMINI_API_KEY"),
}
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")


class StormRunError(RuntimeError):
    """Storm execution failed before or during the STORM pipeline."""


class StormConfig(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    output_dir: Path
    backend: Literal["litellm"] = "litellm"
    provider: PROVIDERS | None = None
    model: str | None = None
    api_key_env: str | None = None
    api_base: str | None = None
    retriever: RETRIEVERS = "tavily"
    max_conv_turn: int = Field(default=4, ge=1, le=20)
    max_perspective: int = Field(default=5, ge=1, le=20)
    search_top_k: int = Field(default=5, ge=1, le=20)
    retrieve_top_k: int = Field(default=5, ge=1, le=20)
    max_thread_num: int = Field(default=3, ge=1, le=16)
    do_research: bool = True
    do_generate_outline: bool = True
    do_generate_article: bool = True
    do_polish_article: bool = False
    remove_duplicate: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_raw_key(cls, value: object) -> object:
        if isinstance(value, dict) and "api_key" in value:
            raise StormRunError(
                "raw model API keys are not supported; configure --api-key-env"
            )
        return value

    @field_validator("output_dir")
    @classmethod
    def output_dir_safe(cls, value: Path) -> Path:
        if str(value).strip() in {"", "/"} or value == Path.home():
            raise ValueError("output_dir must be a dedicated non-home directory")
        return value

    def resolve_api_key(self, role: Literal["model", "retriever"]) -> str:
        """Resolve only the selected provider's named environment variable."""
        if role == "model":
            return self.resolve_provider()[1]
        value = os.getenv("TAVILY_API_KEY")
        if not value:
            raise StormRunError("Tavily API key missing: set TAVILY_API_KEY")
        return value

    def resolve_provider(self) -> tuple[str, str, str | None]:
        """Validate provider routing and credential before constructing a model."""
        provider = self.provider
        if provider is None:
            raise StormRunError(
                "model provider missing: select --provider openai, gemini, or openai-compatible"
            )
        if provider == "openai-compatible":
            if not self.api_base or not self.model or not self.api_key_env:
                raise StormRunError(
                    "openai-compatible requires --api-base, --model, and --api-key-env"
                )
            try:
                endpoint = urlsplit(self.api_base)
            except ValueError as error:
                raise StormRunError("--api-base must be a valid HTTPS URL") from error
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or endpoint.hostname == "chatgpt.com"
            ):
                raise StormRunError(
                    "--api-base must be a public HTTPS endpoint without embedded credentials"
                )
            model = self.model
            env_name = self.api_key_env
        else:
            default_model, default_env = _PROVIDER_DEFAULTS[provider]
            if self.api_base:
                raise StormRunError(
                    "--api-base requires --provider openai-compatible"
                )
            model = self.model or default_model
            env_name = self.api_key_env or default_env
        prefix = "openai/" if provider != "gemini" else "gemini/"
        if not model.startswith(prefix):
            raise StormRunError(f"model for {provider} must start with {prefix}")
        if not _ENV_NAME.fullmatch(env_name):
            raise StormRunError("--api-key-env must name an environment variable")
        api_key = os.getenv(env_name)
        if not api_key or not api_key.strip():
            hint = (
                env_name
                if self.api_key_env is None
                else "the variable named by --api-key-env"
            )
            raise StormRunError(
                f"model credential missing: set {hint} for provider {provider}"
            )
        return model, api_key, self.api_base


class StormRunReceipt(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["arw.storm-run-receipt.v1"]
    topic: str
    topic_directory: str
    backend: str
    model: str
    retriever: str
    started_at: str
    finished_at: str
    parameters: dict[str, object]
    artifacts: list[str]
    model_usage: dict[str, dict[str, int]]


def sanitize_topic(topic: str) -> str:
    topic = re.sub(r"[^A-Za-z0-9_-]+", "_", topic.replace(" ", "_")).strip("_")
    return topic or "unnamed_topic"


def _build_lm_configs(
    config: StormConfig,
    resolved_provider: tuple[str, str, str | None] | None = None,
):
    # Preflight before importing or constructing any provider model.
    model, api_key, api_base = resolved_provider or config.resolve_provider()
    from knowledge_storm import STORMWikiLMConfigs
    from knowledge_storm.lm import LitellmModel

    lm_configs = STORMWikiLMConfigs()
    lm_kwargs: dict[str, object] = {"api_key": api_key, "temperature": 1.0, "top_p": 0.9}
    if api_base:
        lm_kwargs["api_base"] = api_base
    lm_configs.set_conv_simulator_lm(LitellmModel(model=model, max_tokens=500, **lm_kwargs))
    lm_configs.set_question_asker_lm(LitellmModel(model=model, max_tokens=500, **lm_kwargs))
    lm_configs.set_outline_gen_lm(LitellmModel(model=model, max_tokens=400, **lm_kwargs))
    lm_configs.set_article_gen_lm(LitellmModel(model=model, max_tokens=700, **lm_kwargs))
    lm_configs.set_article_polish_lm(LitellmModel(model=model, max_tokens=4000, **lm_kwargs))
    return lm_configs, model


def run_storm_research(config: StormConfig) -> StormRunReceipt:
    """Run the STORM wiki pipeline and return an ARW audit receipt."""
    if not config.do_research and not config.do_generate_outline and not config.do_generate_article:
        raise StormRunError("at least one pipeline stage must be enabled")

    resolved_provider = config.resolve_provider()

    try:
        from knowledge_storm import STORMWikiRunner, STORMWikiRunnerArguments
        from knowledge_storm.rm import DuckDuckGoSearchRM, TavilySearchRM
    except ImportError as error:
        raise StormRunError(
            "knowledge-storm is not installed in this runtime; run "
            "`uv add --group storm knowledge-storm` (source checkout) or "
            "install the plugin's optional storm dependency group"
        ) from error

    lm_configs, effective_model = _build_lm_configs(config, resolved_provider)

    engine_args = STORMWikiRunnerArguments(
        output_dir=str(config.output_dir),
        max_conv_turn=config.max_conv_turn,
        max_perspective=config.max_perspective,
        search_top_k=config.search_top_k,
        retrieve_top_k=config.retrieve_top_k,
        max_thread_num=config.max_thread_num,
    )

    if config.retriever == "tavily":
        retriever = TavilySearchRM(
            tavily_search_api_key=config.resolve_api_key("retriever"),
            k=config.search_top_k,
            include_raw_content=True,
        )
    else:
        retriever = DuckDuckGoSearchRM(
            k=config.search_top_k, safe_search="On", region="us-en"
        )

    started_at = datetime.now(UTC).isoformat()
    runner = STORMWikiRunner(engine_args, lm_configs, retriever)
    runner.run(
        topic=config.topic,
        do_research=config.do_research,
        do_generate_outline=config.do_generate_outline,
        do_generate_article=config.do_generate_article,
        do_polish_article=config.do_polish_article,
        remove_duplicate=config.remove_duplicate,
    )
    runner.post_run()
    # STORM accumulates per-module token usage in lm_cost during run();
    # aggregate it here instead of resetting the LMs (which summary()
    # itself prints from lm_cost).
    usage: dict[str, dict[str, int]] = {}
    for module_cost in runner.lm_cost.values():
        for model_name, tokens in module_cost.items():
            entry = usage.setdefault(
                model_name, {"prompt_tokens": 0, "completion_tokens": 0}
            )
            entry["prompt_tokens"] += int(tokens.get("prompt_tokens", 0))
            entry["completion_tokens"] += int(tokens.get("completion_tokens", 0))
    runner.summary()
    finished_at = datetime.now(UTC).isoformat()

    topic_directory = config.output_dir / sanitize_topic(config.topic)
    artifacts = sorted(
        path.name for path in topic_directory.iterdir() if path.is_file()
    )
    receipt = StormRunReceipt(
        schema_version="arw.storm-run-receipt.v1",
        topic=config.topic,
        topic_directory=sanitize_topic(config.topic),
        backend=config.backend,
        model=effective_model,
        retriever=config.retriever,
        started_at=started_at,
        finished_at=finished_at,
        parameters={
            "max_conv_turn": config.max_conv_turn,
            "max_perspective": config.max_perspective,
            "search_top_k": config.search_top_k,
            "retrieve_top_k": config.retrieve_top_k,
            "do_polish_article": config.do_polish_article,
            "remove_duplicate": config.remove_duplicate,
        },
        artifacts=artifacts,
        model_usage=usage,
    )
    receipt_path = topic_directory / "arw-storm-receipt.json"
    receipt_path.write_text(
        receipt.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return receipt


class StormWorkflowProvider:
    """WorkflowProvider-compatible execution adapter; no canonical workflow registered.

    STORM produces advisory files outside the run state machine. Advertising a
    canonical definition here would falsely imply scientific admission.
    """
    def registry(self):
        return ()

    def resolve(self, definition_id):
        return None

    def run(self, config):
        return run_storm_research(config)

    def __call__(self, config):
        return self.run(config)

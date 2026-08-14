"""Optional STORM deep-research integration.

STORM (https://github.com/stanford-oval/storm) is a retrieval-grounded
Wikipedia-style article synthesis pipeline.  ARW exposes it as an explicit
opt-in command for experiment planning and deep-thinking passes: it is never
part of the default route, never touches the run ledger, and only writes into
an operator-chosen output directory.

Model access is delegated to LiteLLM (``knowledge-storm`` >= 1.1), so any
OpenAI-compatible endpoint works.  Keys are read from the environment or the
CLI and are never persisted.  Retrieval defaults to Tavily (official STORM
retriever) with DuckDuckGo as a keyless fallback.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RETRIEVERS = Literal["tavily", "duckduckgo"]
_DEFAULT_MODEL = "openai/gemini-2.5-flash"


class StormRunError(RuntimeError):
    """Storm execution failed before or during the STORM pipeline."""


class StormConfig(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    output_dir: Path
    model: str = _DEFAULT_MODEL
    api_key: str | None = None
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

    @field_validator("output_dir")
    @classmethod
    def output_dir_safe(cls, value: Path) -> Path:
        if str(value).strip() in {"", "/"} or value == Path.home():
            raise ValueError("output_dir must be a dedicated non-home directory")
        return value

    def resolve_api_key(self, role: Literal["model", "retriever"]) -> str:
        """Resolve a credential from config or environment; fail closed."""
        if role == "model":
            value = self.api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not value:
                raise StormRunError(
                    "model API key missing: pass --api-key or set GEMINI_API_KEY"
                )
            return value
        value = os.getenv("TAVILY_API_KEY")
        if not value:
            raise StormRunError("Tavily API key missing: set TAVILY_API_KEY")
        return value

    def resolve_api_base(self) -> str | None:
        if self.api_base:
            return self.api_base
        return os.getenv("GOOGLE_GEMINI_BASE_URL") or os.getenv("OPENAI_API_BASE")


class StormRunReceipt(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["arw.storm-run-receipt.v1"]
    topic: str
    topic_directory: str
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


def run_storm_research(config: StormConfig) -> StormRunReceipt:
    """Run the STORM wiki pipeline and return an ARW audit receipt."""
    if not config.do_research and not config.do_generate_outline and not config.do_generate_article:
        raise StormRunError("at least one pipeline stage must be enabled")

    try:
        from knowledge_storm import STORMWikiLMConfigs, STORMWikiRunner, STORMWikiRunnerArguments
        from knowledge_storm.lm import LitellmModel
        from knowledge_storm.rm import DuckDuckGoSearchRM, TavilySearchRM
    except ImportError as error:
        raise StormRunError(
            "knowledge-storm is not installed in this runtime; run "
            "`uv add --group storm knowledge-storm` (source checkout) or "
            "install the plugin's optional storm dependency group"
        ) from error

    api_key = config.resolve_api_key("model")
    api_base = config.resolve_api_base()

    lm_kwargs: dict[str, object] = {"api_key": api_key, "temperature": 1.0, "top_p": 0.9}
    if api_base:
        lm_kwargs["api_base"] = api_base

    lm_configs = STORMWikiLMConfigs()
    lm_configs.set_conv_simulator_lm(LitellmModel(model=config.model, max_tokens=500, **lm_kwargs))
    lm_configs.set_question_asker_lm(LitellmModel(model=config.model, max_tokens=500, **lm_kwargs))
    lm_configs.set_outline_gen_lm(LitellmModel(model=config.model, max_tokens=400, **lm_kwargs))
    lm_configs.set_article_gen_lm(LitellmModel(model=config.model, max_tokens=700, **lm_kwargs))
    lm_configs.set_article_polish_lm(LitellmModel(model=config.model, max_tokens=4000, **lm_kwargs))

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
    summary = runner.summary()
    finished_at = datetime.now(UTC).isoformat()

    topic_directory = config.output_dir / sanitize_topic(config.topic)
    artifacts = sorted(
        path.name for path in topic_directory.iterdir() if path.is_file()
    )

    usage: dict[str, dict[str, int]] = {}
    for lm in (
        lm_configs.conv_simulator_lm,
        lm_configs.question_asker_lm,
        lm_configs.outline_gen_lm,
        lm_configs.article_gen_lm,
        lm_configs.article_polish_lm,
    ):
        if lm is not None:
            usage.update(lm.get_usage_and_reset())

    receipt = StormRunReceipt(
        schema_version="arw.storm-run-receipt.v1",
        topic=config.topic,
        topic_directory=sanitize_topic(config.topic),
        model=config.model,
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

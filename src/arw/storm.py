"""Optional STORM deep-research integration.

STORM (https://github.com/stanford-oval/storm) is a retrieval-grounded
Wikipedia-style article synthesis pipeline.  ARW exposes it as an explicit
opt-in command for experiment planning and deep-thinking passes: it is never
part of the default route, never touches the run ledger, and only writes into
an operator-chosen output directory.

Model access follows the session-first rule: by default STORM reuses the
model the current agent session is configured to use (pi/Codex OAuth over the
ChatGPT backend Responses API).  An explicit ``--api-base``/``--api-key`` (or
the GEMINI environment pair) switches to the LiteLLM path for any
OpenAI-compatible endpoint.  Keys are read from session files or the
environment and are never persisted.  Retrieval defaults to Tavily (official
STORM retriever) with DuckDuckGo as a keyless fallback.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RETRIEVERS = Literal["tavily", "duckduckgo"]
BACKENDS = Literal["session", "litellm"]
_DEFAULT_LITELLM_MODEL = "openai/gemini-2.5-flash"
_CODEX_BACKEND = "https://chatgpt.com/backend-api/codex"


class StormRunError(RuntimeError):
    """Storm execution failed before or during the STORM pipeline."""


class StormConfig(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    output_dir: Path
    backend: BACKENDS = "session"
    model: str = _DEFAULT_LITELLM_MODEL
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


class SessionModelConfig(BaseModel):
    """The model the current agent session is configured to use."""

    model_config = ConfigDict(strict=True, extra="forbid")

    provider: str
    model: str
    access_token: str


def resolve_session_model() -> SessionModelConfig | None:
    """Discover the current agent session's model configuration.

    Reads pi's session settings (default provider/model) and its OAuth
    credential store, then falls back to the Codex CLI credential store.
    Returns ``None`` when no session credential is available.
    """

    for settings_path, auth_path, provider_priority in (
        (Path.home() / ".pi/agent/settings.json", Path.home() / ".pi/agent/auth.json", ("openai-codex",)),
        (Path.home() / ".codex/settings.json", Path.home() / ".codex/auth.json", ()),
    ):
        if not settings_path.is_file() or not auth_path.is_file():
            continue
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        provider = settings.get("defaultProvider")
        model = settings.get("defaultModel") or ""
        if not provider or not model:
            continue
        entry = auth.get(provider, {})
        if isinstance(entry, dict):
            if entry.get("type") == "oauth" and entry.get("access"):
                return SessionModelConfig(
                    provider=provider, model=model, access_token=entry["access"]
                )
            if entry.get("type") == "api_key" and entry.get("key"):
                return SessionModelConfig(
                    provider=provider, model=model, access_token=entry["key"]
                )
    return None


class CodexResponsesLM:
    """STORM-compatible LM backed by the ChatGPT backend Responses API.

    Implements the ``knowledge_storm`` LM protocol (``__call__`` returning a
    list of output strings, ``get_usage_and_reset``, ``history``) so STORM's
    pipeline can run on the exact model the current session is using.
    """

    def __init__(
        self,
        model: str,
        access_token: str,
        *,
        temperature: float = 1.0,
        max_tokens: int = 500,
        cache: bool = True,
        **kwargs: object,
    ) -> None:
        self.model = model
        self.access_token = access_token
        self.cache = cache
        self.kwargs = dict(temperature=temperature, max_tokens=max_tokens, **kwargs)
        self.history: list[dict[str, object]] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._last_usage_tokens = 0
        self._lock = threading.Lock()

    def __call__(
        self, prompt: str | None = None, messages: list[dict[str, str]] | None = None, **kwargs: object
    ) -> list[str]:
        import httpx

        if messages is None:
            messages = [{"role": "user", "content": prompt or ""}]
        input_items = [
            {"type": "message", "role": m.get("role", "user"), "content": [{"type": "input_text", "text": str(m.get("content", ""))}]}
            for m in messages
        ]
        # The ChatGPT backend Responses endpoint only accepts the minimal
        # parameter set; temperature / max_output_tokens are rejected, so the
        # model defaults govern both.
        body = {
            "model": self.model,
            "input": input_items,
            "stream": True,
            "store": False,
        }

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                text = self._complete(body)
                break
            except (httpx.HTTPError, StormRunError) as error:
                last_error = error
                if attempt < 2:
                    import time as _time

                    _time.sleep(1.5 * (attempt + 1))
        else:
            raise StormRunError(
                f"session model backend failed after retries: {last_error}"
            ) from last_error
        usage_tokens = self._last_usage_tokens
        with self._lock:
            self.prompt_tokens += max(usage_tokens // 2, 0)
            self.completion_tokens += usage_tokens
            self.history.append(
                {
                    "prompt": prompt,
                    "messages": messages,
                    "outputs": [text],
                    "usage": {"total_tokens": usage_tokens},
                }
            )
        return [text]

    def _complete(self, body: dict[str, object]) -> str:
        import httpx

        text_parts: list[str] = []
        usage_tokens = 0
        with httpx.Client(timeout=600) as client:
            with client.stream(
                "POST",
                f"{_CODEX_BACKEND}/responses",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                    "Origin": "https://chatgpt.com",
                    "User-Agent": "Mozilla/5.0",
                },
            ) as response:
                if response.status_code != 200:
                    detail = next(response.iter_text()).strip()[:300]
                    raise StormRunError(
                        f"session model backend rejected the request "
                        f"(status {response.status_code}): {detail}"
                    )
                event_type = None
                for line in response.iter_lines():
                    if line.startswith("event: "):
                        event_type = line[len("event: ") :]
                    elif line.startswith("data: ") and event_type is not None:
                        event_data = line[len("data: ") :]
                        if event_type == "response.output_text.delta":
                            try:
                                text_parts.append(json.loads(event_data).get("delta", ""))
                            except ValueError:
                                pass
                        elif event_type == "response.completed":
                            try:
                                payload = json.loads(event_data)
                                resp = payload.get("response", {}) or {}
                                usage = resp.get("usage") or {}
                                usage_tokens = int(usage.get("total_tokens") or 0)
                                # Fallback: some responses carry the full text
                                # only in the completed output items.
                                for item in resp.get("output", []) or []:
                                    if item.get("type") == "message":
                                        for part in item.get("content", []) or []:
                                            if part.get("type") == "output_text":
                                                text_parts.append(part.get("text", ""))
                            except (ValueError, TypeError):
                                pass
                        event_type = None
        self._last_usage_tokens = usage_tokens
        text = "".join(text_parts)
        if not text.strip():
            raise StormRunError(
                "session model backend returned an empty response"
            )
        return text

    def get_usage_and_reset(self) -> dict[str, dict[str, int]]:
        with self._lock:
            usage = {
                self.model: {
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                }
            }
            self.prompt_tokens = 0
            self.completion_tokens = 0
        return usage

    def inspect_history(self, n: int = 1) -> None:  # pragma: no cover - debug helper
        for entry in self.history[-n:]:
            print(entry)


def _build_lm_configs(config: StormConfig):
    from knowledge_storm import STORMWikiLMConfigs

    lm_configs = STORMWikiLMConfigs()

    if config.backend == "session":
        session = resolve_session_model()
        if session is None:
            raise StormRunError(
                "no session model credential found (checked ~/.pi/agent/auth.json "
                "and ~/.codex/auth.json); pass --backend litellm with --api-key/--api-base"
            )
        model = config.model if config.model != _DEFAULT_LITELLM_MODEL else session.model

        def make_lm(max_tokens: int) -> CodexResponsesLM:
            return CodexResponsesLM(
                model=model, access_token=session.access_token, max_tokens=max_tokens
            )

        lm_configs.set_conv_simulator_lm(make_lm(500))
        lm_configs.set_question_asker_lm(make_lm(500))
        lm_configs.set_outline_gen_lm(make_lm(400))
        lm_configs.set_article_gen_lm(make_lm(700))
        lm_configs.set_article_polish_lm(make_lm(4000))
        return lm_configs, model

    from knowledge_storm.lm import LitellmModel

    api_key = config.resolve_api_key("model")
    api_base = config.resolve_api_base()
    lm_kwargs: dict[str, object] = {"api_key": api_key, "temperature": 1.0, "top_p": 0.9}
    if api_base:
        lm_kwargs["api_base"] = api_base
    lm_configs.set_conv_simulator_lm(LitellmModel(model=config.model, max_tokens=500, **lm_kwargs))
    lm_configs.set_question_asker_lm(LitellmModel(model=config.model, max_tokens=500, **lm_kwargs))
    lm_configs.set_outline_gen_lm(LitellmModel(model=config.model, max_tokens=400, **lm_kwargs))
    lm_configs.set_article_gen_lm(LitellmModel(model=config.model, max_tokens=700, **lm_kwargs))
    lm_configs.set_article_polish_lm(LitellmModel(model=config.model, max_tokens=4000, **lm_kwargs))
    return lm_configs, config.model


def run_storm_research(config: StormConfig) -> StormRunReceipt:
    """Run the STORM wiki pipeline and return an ARW audit receipt."""
    if not config.do_research and not config.do_generate_outline and not config.do_generate_article:
        raise StormRunError("at least one pipeline stage must be enabled")

    try:
        from knowledge_storm import STORMWikiRunner, STORMWikiRunnerArguments
        from knowledge_storm.rm import DuckDuckGoSearchRM, TavilySearchRM
    except ImportError as error:
        raise StormRunError(
            "knowledge-storm is not installed in this runtime; run "
            "`uv add --group storm knowledge-storm` (source checkout) or "
            "install the plugin's optional storm dependency group"
        ) from error

    lm_configs, effective_model = _build_lm_configs(config)

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

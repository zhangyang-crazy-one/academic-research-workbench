"""Unit tests for the opt-in STORM integration (no network, no model calls)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from arw.storm import StormConfig, StormRunError, sanitize_topic


def test_sanitize_topic() -> None:
    assert sanitize_topic("Deep RL for LLM Reasoning") == "Deep_RL_for_LLM_Reasoning"
    assert sanitize_topic(" 中文 主题 / test ") == "test"
    assert sanitize_topic("///") == "unnamed_topic"


def test_config_rejects_unsafe_output_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        StormConfig(topic="t", output_dir=Path("/"))
    with pytest.raises(ValueError):
        StormConfig(topic="t", output_dir=Path.home())
    StormConfig(topic="t", output_dir=tmp_path / "out")  # dedicated dir is fine


def test_config_requires_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = StormConfig(topic="t", output_dir=Path("build/storm"), api_key=None)
    with pytest.raises(StormRunError, match="GEMINI_API_KEY"):
        config.resolve_api_key("model")
    config2 = StormConfig(topic="t", output_dir=Path("build/storm"), api_key="k")
    assert config2.resolve_api_key("model") == "k"


def test_config_requires_tavily_key_for_tavily_retriever(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    config = StormConfig(topic="t", output_dir=Path("build/storm"), retriever="tavily")
    with pytest.raises(StormRunError, match="TAVILY_API_KEY"):
        config.resolve_api_key("retriever")


def test_run_requires_at_least_one_stage(tmp_path: Path) -> None:
    from arw.storm import run_storm_research

    config = StormConfig(
        topic="t",
        output_dir=tmp_path / "storm",
        do_research=False,
        do_generate_outline=False,
        do_generate_article=False,
    )
    with pytest.raises(StormRunError, match="at least one pipeline stage"):
        run_storm_research(config)


def _install_fake_storm_modules() -> None:
    """Inject fake knowledge_storm package tree so run_storm_research's
    function-local imports resolve without touching the heavy real deps."""

    fake_storm = types.ModuleType("knowledge_storm")

    class FakeRunner:
        last_topic: str | None = None

        def __init__(self, engine_args: object, *args: object, **kwargs: object) -> None:
            self.engine_args = engine_args

        def run(self, **kwargs: object) -> None:
            FakeRunner.last_topic = kwargs.get("topic")
            topic_dir = Path(self.engine_args["output_dir"]) / "Deep_RL"
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "storm_gen_article.txt").write_text("article\n", encoding="utf-8")
            (topic_dir / "url_to_info.json").write_text("{}\n", encoding="utf-8")

        def post_run(self) -> None:
            pass

        def summary(self) -> str:
            return "summary"

    fake_storm.STORMWikiRunner = FakeRunner
    fake_storm.STORMWikiRunnerArguments = lambda **kw: kw

    class FakeLMConfigs:
        def __init__(self) -> None:
            self.conv_simulator_lm = None
            self.question_asker_lm = None
            self.outline_gen_lm = None
            self.article_gen_lm = None
            self.article_polish_lm = None

        def set_conv_simulator_lm(self, lm: object) -> None:
            self.conv_simulator_lm = lm

        def set_question_asker_lm(self, lm: object) -> None:
            self.question_asker_lm = lm

        def set_outline_gen_lm(self, lm: object) -> None:
            self.outline_gen_lm = lm

        def set_article_gen_lm(self, lm: object) -> None:
            self.article_gen_lm = lm

        def set_article_polish_lm(self, lm: object) -> None:
            self.article_polish_lm = lm

    fake_storm.STORMWikiLMConfigs = FakeLMConfigs

    class FakeLM:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def get_usage_and_reset(self) -> dict[str, dict[str, int]]:
            return {
                "openai/gemini-2.5-flash": {"prompt_tokens": 10, "completion_tokens": 5}
            }

    fake_lm = types.ModuleType("knowledge_storm.lm")
    fake_lm.LitellmModel = FakeLM
    fake_rm = types.ModuleType("knowledge_storm.rm")
    fake_rm.TavilySearchRM = lambda **kw: ("tavily", kw)
    fake_rm.DuckDuckGoSearchRM = lambda **kw: ("duckduckgo", kw)

    sys.modules["knowledge_storm"] = fake_storm
    sys.modules["knowledge_storm.lm"] = fake_lm
    sys.modules["knowledge_storm.rm"] = fake_rm
    fake_storm.lm = fake_lm
    fake_storm.rm = fake_rm


def test_run_storm_research_writes_receipt_with_mocked_storm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the full ARW wrapper with fake knowledge_storm modules."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-model-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    _install_fake_storm_modules()

    from arw.storm import run_storm_research

    config = StormConfig(topic="Deep RL", output_dir=tmp_path / "storm")
    receipt = run_storm_research(config)

    assert receipt.model == "openai/gemini-2.5-flash"
    assert receipt.retriever == "tavily"
    assert receipt.schema_version == "arw.storm-run-receipt.v1"
    receipt_path = tmp_path / "storm" / "Deep_RL" / "arw-storm-receipt.json"
    assert receipt_path.is_file()
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["topic"] == "Deep RL"
    assert payload["model_usage"]["openai/gemini-2.5-flash"]["prompt_tokens"] == 10


def test_run_storm_research_duckduckgo_needs_no_tavily_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-model-key")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_storm_modules()

    from arw.storm import run_storm_research

    config = StormConfig(
        topic="Deep RL", output_dir=tmp_path / "storm", retriever="duckduckgo"
    )
    receipt = run_storm_research(config)
    assert receipt.retriever == "duckduckgo"

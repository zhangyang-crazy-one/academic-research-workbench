"""Unit tests for the opt-in STORM integration (no network, no model calls)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from arw_storm import StormConfig, StormRunError, sanitize_topic


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
    config = StormConfig(topic="t", output_dir=Path("build/storm"))
    with pytest.raises(StormRunError, match="select --provider"):
        config.resolve_api_key("model")
    monkeypatch.setenv("GEMINI_API_KEY", "unselected-provider-key")
    config2 = StormConfig(topic="t", output_dir=Path("build/storm"), provider="openai")
    with pytest.raises(StormRunError, match="set OPENAI_API_KEY") as error:
        config2.resolve_api_key("model")
    assert "unselected-provider-key" not in str(error.value)
    monkeypatch.setenv("OPENAI_API_KEY", "selected-provider-key")
    assert config2.resolve_api_key("model") == "selected-provider-key"


def test_explicit_compatible_provider_uses_named_environment_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = StormConfig(
        topic="t", output_dir=Path("build/storm"), provider="openai-compatible",
        model="openai/local-model", api_base="https://models.example.test/v1",
        api_key_env="STORM_TEST_KEY",
    )
    monkeypatch.setenv("STORM_TEST_KEY", "named-test-key")
    assert config.resolve_provider() == (
        "openai/local-model", "named-test-key", "https://models.example.test/v1"
    )
    monkeypatch.delenv("STORM_TEST_KEY")
    with pytest.raises(StormRunError, match="variable named by --api-key-env") as error:
        config.resolve_provider()
    assert "STORM_TEST_KEY" not in str(error.value)
    with pytest.raises(StormRunError, match="raw model API keys") as error:
        StormConfig(topic="t", output_dir=Path("build/storm"), api_key="raw-secret")
    assert "raw-secret" not in str(error.value)


def test_compatible_endpoint_rejects_embedded_credentials() -> None:
    config = StormConfig(
        topic="t", output_dir=Path("build/storm"), provider="openai-compatible",
        model="openai/local-model", api_base="https://secret@example.test/v1?key=value",
        api_key_env="STORM_TEST_KEY",
    )
    with pytest.raises(StormRunError, match="without embedded credentials") as error:
        config.resolve_provider()
    assert "secret" not in str(error.value)

    private_config = config.model_copy(
        update={"api_base": "https://chatgpt.com/backend-api/codex"}
    )
    with pytest.raises(StormRunError, match="public HTTPS endpoint"):
        private_config.resolve_provider()


def test_default_path_ignores_present_host_credential_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arw_storm import run_storm_research

    for parent in (tmp_path / ".codex", tmp_path / ".pi" / "agent"):
        parent.mkdir(parents=True)
        (parent / "settings.json").write_text('{"defaultProvider":"openai-codex"}')
        (parent / "auth.json").write_text('{"access":"host-store-secret"}')
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    original_is_file = Path.is_file
    original_read_text = Path.read_text

    def guarded_is_file(path: Path) -> bool:
        assert tmp_path not in path.parents, f"host credential store inspected: {path}"
        return original_is_file(path)

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        assert tmp_path not in path.parents, f"host credential store read: {path}"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    with pytest.raises(StormRunError, match="select --provider") as error:
        run_storm_research(StormConfig(topic="t", output_dir=tmp_path / "output"))
    assert "host-store-secret" not in str(error.value)


def test_missing_selected_provider_key_fails_before_model_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arw_storm import run_storm_research

    fake_runner = _install_fake_storm_modules()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "irrelevant-secret")
    config = StormConfig(topic="t", output_dir=tmp_path / "out", provider="openai")
    with pytest.raises(StormRunError, match="set OPENAI_API_KEY") as error:
        run_storm_research(config)
    assert "irrelevant-secret" not in str(error.value)
    assert fake_runner.last_lm_configs is None
    assert fake_runner.FakeLM.instances == 0


def test_config_requires_tavily_key_for_tavily_retriever(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    config = StormConfig(topic="t", output_dir=Path("build/storm"), retriever="tavily")
    with pytest.raises(StormRunError, match="TAVILY_API_KEY"):
        config.resolve_api_key("retriever")


def test_run_requires_at_least_one_stage(tmp_path: Path) -> None:
    from arw_storm import run_storm_research

    config = StormConfig(
        topic="t",
        output_dir=tmp_path / "storm",
        do_research=False,
        do_generate_outline=False,
        do_generate_article=False,
    )
    with pytest.raises(StormRunError, match="at least one pipeline stage"):
        run_storm_research(config)


def _install_fake_storm_modules() -> type:
    """Inject fake knowledge_storm package tree so run_storm_research's
    function-local imports resolve without touching the heavy real deps."""

    fake_storm = types.ModuleType("knowledge_storm")

    class FakeRunner:
        last_topic: str | None = None
        last_lm_configs: object | None = None

        def __init__(self, engine_args: object, lm_configs: object, *args: object, **kwargs: object) -> None:
            self.engine_args = engine_args
            FakeRunner.last_lm_configs = lm_configs
            self.lm_cost = {
                "run_knowledge_curation_module": {
                    "gemini/gemini-2.5-flash": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                    }
                }
            }

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
        instances = 0

        def __init__(self, **kwargs: object) -> None:
            FakeLM.instances += 1
            self.kwargs = kwargs

        def get_usage_and_reset(self) -> dict[str, dict[str, int]]:
            return {
                "gemini/gemini-2.5-flash": {"prompt_tokens": 10, "completion_tokens": 5}
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
    FakeRunner.FakeLM = FakeLM
    return FakeRunner


def test_run_storm_research_writes_receipt_with_mocked_storm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the full ARW wrapper with fake knowledge_storm modules."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-model-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    fake_runner = _install_fake_storm_modules()

    from arw_storm import run_storm_research

    config = StormConfig(
        topic="Deep RL", output_dir=tmp_path / "storm", provider="gemini"
    )
    receipt = run_storm_research(config)

    assert receipt.model == "gemini/gemini-2.5-flash"
    assert receipt.retriever == "tavily"
    assert receipt.schema_version == "arw.storm-run-receipt.v1"
    receipt_path = tmp_path / "storm" / "Deep_RL" / "arw-storm-receipt.json"
    assert receipt_path.is_file()
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["topic"] == "Deep RL"
    assert payload["model_usage"]["gemini/gemini-2.5-flash"]["prompt_tokens"] == 10
    assert fake_runner.last_lm_configs.conv_simulator_lm.kwargs["api_key"] == "test-model-key"
    assert "test-model-key" not in receipt_path.read_text(encoding="utf-8")


def test_run_storm_research_duckduckgo_needs_no_tavily_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-model-key")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_storm_modules()

    from arw_storm import run_storm_research

    config = StormConfig(
        topic="Deep RL",
        output_dir=tmp_path / "storm",
        retriever="duckduckgo",
        provider="gemini",
    )
    receipt = run_storm_research(config)
    assert receipt.retriever == "duckduckgo"


def test_session_backend_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="backend"):
        StormConfig(topic="t", output_dir=tmp_path / "storm", backend="session")


def test_private_session_transport_is_absent() -> None:
    import inspect
    import arw_storm

    source = inspect.getsource(arw_storm)
    assert "chatgpt.com/backend-api" not in source
    assert '"Origin"' not in source
    assert '"User-Agent"' not in source
    assert "resolve_session_model" not in source


@pytest.mark.parametrize("key_argument", ["--api-key", "--api-key=raw-secret"])
def test_cli_rejects_raw_api_key_without_echo(
    key_argument: str, capsys: pytest.CaptureFixture[str],
) -> None:
    from arw.cli import build_parser, main

    args = ["storm", "--topic", "Deep RL", "--provider", "gemini", key_argument]
    if key_argument == "--api-key":
        args.append("raw-secret")
    assert main(args) == 65
    captured = capsys.readouterr()
    assert "--api-key-env" in captured.err
    assert "raw-secret" not in captured.err + captured.out
    assert "api_key" not in vars(build_parser().parse_args(
        ["storm", "--topic", "Deep RL"]
    ))


def test_cli_default_fails_before_provider_invocation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arw.cli import main

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake_runner = _install_fake_storm_modules()
    args = ["storm", "--topic", "Deep RL", "--output-dir", str(tmp_path / "out")]
    assert main(args) == 65
    captured = capsys.readouterr()
    assert "select --provider" in captured.err
    assert "Traceback" not in captured.err
    assert fake_runner.last_lm_configs is None
    assert fake_runner.FakeLM.instances == 0


def test_cli_configured_public_provider_succeeds_without_secret_in_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arw.cli import main

    monkeypatch.setenv("GEMINI_API_KEY", "cli-test-model-secret")
    monkeypatch.setenv("TAVILY_API_KEY", "cli-test-retriever-secret")
    _install_fake_storm_modules()
    args = [
        "storm", "--topic", "Deep RL", "--output-dir", str(tmp_path / "out"),
        "--provider", "gemini",
    ]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["model"] == "gemini/gemini-2.5-flash"
    assert "cli-test-model-secret" not in str(args) + captured.out + captured.err
    assert "cli-test-retriever-secret" not in str(args) + captured.out + captured.err

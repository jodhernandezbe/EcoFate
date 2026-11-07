"""Tests for the chat model factory and the program run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.chat_model import build_chat_model, build_named_chat_model
from app.key_vault import KeyringVault, default_service_keys
from app.run import ask, program_model, run_config
from config.agent import AgentSettings, get_agent_settings
from tests.fakes import FakeCredentialStore

ROOT = Path(__file__).resolve().parents[2]

SETTINGS = AgentSettings(
    provider="openai",
    model="chat-test",
    api_key_env_var="TEST_KEY_VAR",  # pragma: allowlist secret
    timeout_seconds=5.0,
    recursion_limit=7,
    temperature=0.0,
    max_resumes_per_turn=3,
)
ENV = {"TEST_KEY_VAR": "not-a-real-key"}  # pragma: allowlist secret


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolModel:
        return self


def test_builds_the_configured_model() -> None:
    model = build_chat_model(SETTINGS, ENV)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "chat-test"


def test_temperature_reaches_the_model() -> None:
    model = build_chat_model(SETTINGS, ENV)
    assert isinstance(model, ChatOpenAI)
    assert model.temperature == 0.0


def test_no_temperature_keeps_the_provider_default() -> None:
    model = build_named_chat_model("openai", "m", "TEST_KEY_VAR", 5.0, ENV)
    assert isinstance(model, ChatOpenAI)
    assert model.temperature is None


def test_shipped_settings_build_their_model() -> None:
    settings = get_agent_settings()
    model = build_chat_model(settings, {settings.api_key_env_var: "not-a-real-key"})
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == settings.model


@pytest.mark.parametrize("env", [{}, {"TEST_KEY_VAR": "  "}])
def test_missing_key_raises(env: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="TEST_KEY_VAR is not set"):
        build_chat_model(SETTINGS, env)


def test_unsupported_provider_raises() -> None:
    with pytest.raises(ValueError, match="unsupported chat provider: other"):
        build_named_chat_model("other", "m", "TEST_KEY_VAR", 5.0, ENV)


def test_run_config_carries_the_step_limit() -> None:
    assert run_config(SETTINGS) == {"recursion_limit": 7}


def test_ask_returns_the_final_answer_of_an_injected_model() -> None:
    model = FakeToolModel(messages=iter([AIMessage(content="final answer")]))
    keys = default_service_keys(FakeCredentialStore())  # never the real keychain
    assert ask("Assess CAS 71-43-2", model, keys).answer == "final answer"


def test_injected_key_is_used_without_reading_the_environment() -> None:
    key = SecretStr("not-a-real-injected-key")  # pragma: allowlist secret
    model = build_chat_model(SETTINGS, {}, api_key=key)
    assert isinstance(model, ChatOpenAI)
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == "not-a-real-injected-key"


def test_injected_key_wins_over_the_environment() -> None:
    key = SecretStr("not-a-real-injected-key")  # pragma: allowlist secret
    model = build_chat_model(SETTINGS, ENV, api_key=key)
    assert isinstance(model, ChatOpenAI)
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == "not-a-real-injected-key"


def _program_key(vault: KeyringVault, env: dict[str, str]) -> str:
    model = program_model(SETTINGS, vault, env)
    assert isinstance(model, ChatOpenAI)
    assert isinstance(model.openai_api_key, SecretStr)
    return model.openai_api_key.get_secret_value()


def _vault(store: FakeCredentialStore) -> KeyringVault:
    return KeyringVault(service="svc", account="acct", max_length=64, store=store)


def test_program_prefers_the_stored_key() -> None:
    store = FakeCredentialStore()
    store.entries[("svc", "acct")] = "not-a-real-stored-key"  # pragma: allowlist secret
    assert _program_key(_vault(store), ENV) == "not-a-real-stored-key"


def test_program_falls_back_to_the_environment() -> None:
    assert _program_key(_vault(FakeCredentialStore()), ENV) == "not-a-real-key"


def test_program_falls_back_when_the_keychain_is_unavailable() -> None:
    assert _program_key(_vault(FakeCredentialStore(fail=True)), ENV) == "not-a-real-key"


def test_program_without_any_key_names_the_variable() -> None:
    with pytest.raises(RuntimeError, match="TEST_KEY_VAR is not set"):
        program_model(SETTINGS, _vault(FakeCredentialStore()), {})


def test_cli_does_not_import_the_web_api() -> None:
    code = (
        "import sys, app.__main__, app.run\n"
        "web = [m for m in sys.modules if m == 'api' or m.startswith('api.')]\n"
        "assert not web, web\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT)

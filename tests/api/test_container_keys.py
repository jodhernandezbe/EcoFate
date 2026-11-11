"""Container mode: the OpenAI key always comes from the user's row, never from the environment;
only the operator's Census and CompTox keys are read from it."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.redaction as redaction
from api.dependencies import AgentRuntime, get_runtime
from api.services.key_setup import KeyServices, load_key_config
from app.operator_keys import OperatorKeys, load_operator_keys
from config.agent import get_agent_settings
from config.byok import get_byok_settings
from config.loader import get_comptox_settings
from config.population import get_population_settings
from config.ui import UiSettings
from tests.api.auth_support import build_app
from tests.api.conftest import ORIGIN, make_user, sign_in_as
from tests.api.keys import OWNER
from tests.api.streams import parse_sse
from tests.fakes import KeyBench, scripted

OWN = {"Origin": ORIGIN}
ENV_KEY = "sk-proj-" + "e0N7v1R0n9" * 3  # pragma: allowlist secret
STORED_KEY = "sk-proj-" + "s7O2r3E4d5" * 3  # pragma: allowlist secret
CENSUS = "c3n5u5k3y" + "7f" * 16  # pragma: allowlist secret
COMPTOX = "ct0x-" + "9d" * 14  # pragma: allowlist secret
KEK_TEXT = base64.urlsafe_b64encode(bytes(range(32))).decode()


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment that holds an OpenAI key and both operator keys."""
    monkeypatch.setenv(get_agent_settings().api_key_env_var, ENV_KEY)
    monkeypatch.setenv(get_population_settings().api_key_env_var, CENSUS)
    monkeypatch.setenv(get_comptox_settings().api_key_env_var, COMPTOX)
    empty: set[str] = set()
    monkeypatch.setattr(redaction, "_PROCESS_LITERALS", empty)


def _operator() -> OperatorKeys:
    return load_operator_keys(
        {
            get_population_settings().api_key_env_var: CENSUS,
            get_comptox_settings().api_key_env_var: COMPTOX,
        },
        get_population_settings().api_key_env_var,
        get_comptox_settings().api_key_env_var,
    )


def _client(settings: UiSettings, bench: KeyBench, used: list[str]) -> Iterator[TestClient]:
    services = KeyServices(bench.vault, _operator())
    app = build_app(settings, keys_from_environment=True, keys=services)
    model = scripted("an answer")

    def build(key: SecretStr) -> object:
        used.append(key.get_secret_value())
        return model

    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(build, 10)  # pyright: ignore[reportArgumentType]
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        sign_in_as(app, client, make_user(app))
        yield client


@pytest.fixture
def used() -> list[str]:
    return []


@pytest.fixture
def keyless(settings: UiSettings, used: list[str]) -> Iterator[TestClient]:
    yield from _client(settings, KeyBench(), used)


@pytest.fixture
def keyed(settings: UiSettings, used: list[str]) -> Iterator[TestClient]:
    bench = KeyBench()
    bench.give(STORED_KEY, OWNER)
    yield from _client(settings, bench, used)


def _say(client: TestClient) -> list[dict[str, object]]:
    body = {"thread_id": "t1", "message": "hello"}
    return parse_sse(client.post("/api/v1/chat/stream", json=body, headers=OWN).text)


def test_the_environment_openai_key_is_not_a_users_key(keyless: TestClient) -> None:
    assert keyless.get("/api/v1/settings/openai-key").json() == {"configured": False}
    status = keyless.get("/api/v1/settings/keys")
    assert status.json()["openai"] == {"configured": False}
    assert ENV_KEY not in status.text


def test_a_turn_without_a_stored_key_ends_with_the_add_your_key_message(
    keyless: TestClient,
    used: list[str],
) -> None:
    events = _say(keyless)
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert used == []  # no model was built, with the environment key or any other


def test_a_turn_uses_the_stored_key_and_never_the_environment_one(
    keyed: TestClient,
    used: list[str],
) -> None:
    events = _say(keyed)
    assert [e for e in events if e["type"] == "error"] == []
    assert used and set(used) == {STORED_KEY}
    assert ENV_KEY not in str(events)


def test_the_operator_keys_still_come_from_the_environment(keyless: TestClient) -> None:
    services = keyless.get("/api/v1/settings/keys").json()["services"]
    assert services == {"census": {"available": True}, "comptox": {"available": True}}


def test_start_up_reads_the_operator_keys_and_no_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environ = {
        get_byok_settings().kek_env_var: KEK_TEXT,
        get_agent_settings().api_key_env_var: ENV_KEY,
        get_population_settings().api_key_env_var: CENSUS,
    }
    _, operator = load_key_config(environ)
    assert operator.census is not None and operator.census.get_secret_value() == CENSUS
    assert operator.comptox is None
    assert ENV_KEY not in repr(operator)
    assert ENV_KEY not in str(operator.values())

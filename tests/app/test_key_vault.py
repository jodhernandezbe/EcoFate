"""Tests for the OS-keychain API key vault."""

from __future__ import annotations

import pytest

from app.key_vault import (
    EnvironmentVault,
    InvalidKeyError,
    KeychainUnavailableError,
    KeyringVault,
    KeyStatus,
    default_service_keys,
    environment_service_keys,
)
from config.ui import KeyName
from tests.fakes import FakeCredentialStore

KEY = "sk-test" + "A" * 20 + "WXYZ"  # pragma: allowlist secret


def _vault(store: FakeCredentialStore) -> KeyringVault:
    return KeyringVault(service="svc", account="acct", max_length=64, store=store)


def test_save_calls_the_store_with_configured_names() -> None:
    store = FakeCredentialStore()
    status = _vault(store).save(KEY)
    assert store.calls == [("set", "svc", "acct")]
    assert store.entries == {("svc", "acct"): KEY}
    assert status == KeyStatus(configured=True)


def test_load_returns_a_secret() -> None:
    store = FakeCredentialStore()
    store.entries[("svc", "acct")] = KEY
    secret = _vault(store).load()
    assert secret is not None
    assert secret.get_secret_value() == KEY
    assert KEY not in repr(secret)


def test_load_without_key_is_none() -> None:
    assert _vault(FakeCredentialStore()).load() is None


def test_clear_deletes_and_tolerates_absent_key() -> None:
    store = FakeCredentialStore()
    store.entries[("svc", "acct")] = KEY
    vault = _vault(store)
    assert vault.clear() == KeyStatus(configured=False)
    assert vault.clear() == KeyStatus(configured=False)
    assert store.calls == [("delete", "svc", "acct"), ("delete", "svc", "acct")]


def test_status_never_contains_the_key() -> None:
    store = FakeCredentialStore()
    store.entries[("svc", "acct")] = KEY
    status = _vault(store).status()
    assert status.configured
    assert KEY not in repr(status)


@pytest.mark.parametrize("bad", ["", "   ", "sk-abc\ndef", "sk-abc def", "sk-\x00abc", "x" * 65])
def test_invalid_keys_are_rejected_without_storing(bad: str) -> None:
    store = FakeCredentialStore()
    with pytest.raises(InvalidKeyError) as info:
        _vault(store).save(bad)
    assert store.calls == []
    if bad.strip():
        assert bad not in str(info.value)


@pytest.mark.parametrize("op", ["save", "load", "clear"])
def test_unavailable_store_raises_a_safe_error(op: str) -> None:
    vault = _vault(FakeCredentialStore(fail=True))
    with pytest.raises(KeychainUnavailableError, match="keychain is unavailable"):
        vault.save(KEY) if op == "save" else getattr(vault, op)()


def test_service_keys_have_independent_entries() -> None:
    store = FakeCredentialStore()
    keys = default_service_keys(store)
    keys.vault("census").save("census-key-0123456789")
    keys.vault("comptox").save("comptox-key-0123456789")
    assert keys.vault("openai").load() is None
    assert {call[2] for call in store.calls if call[0] == "set"} == {
        "census_api_key",
        "comptox_api_key",
    }
    keys.vault("census").clear()
    comptox = keys.vault("comptox").load()
    assert comptox is not None
    assert comptox.get_secret_value() == "comptox-key-0123456789"


def test_service_keys_share_one_service_name() -> None:
    store = FakeCredentialStore()
    keys = default_service_keys(store)
    for name in ("openai", "census", "comptox"):
        keys.vault(name).save(f"{name}-key-0123456789")
    assert {service for (service, _), _ in store.entries.items()} == {"epa-chemical-risk-agent"}
    assert len(store.entries) == 3


def test_statuses_report_each_key_without_revealing_it() -> None:
    store = FakeCredentialStore()
    keys = default_service_keys(store)
    keys.vault("openai").save("sk-test" + "B" * 20 + "WXYZ")
    statuses = keys.statuses()
    assert statuses["openai"] == KeyStatus(configured=True)
    assert statuses["census"] == KeyStatus(configured=False)
    assert statuses["comptox"] == KeyStatus(configured=False)
    assert "BBBB" not in repr(statuses)


def test_statuses_raise_a_safe_error_when_the_keychain_is_unavailable() -> None:
    keys = default_service_keys(FakeCredentialStore(fail=True))
    with pytest.raises(KeychainUnavailableError):
        keys.statuses()


def test_environment_vault_reads_the_variable() -> None:
    vault = EnvironmentVault("MY_KEY", {"MY_KEY": f"  {KEY}  "})
    loaded = vault.load()
    assert loaded is not None
    assert loaded.get_secret_value() == KEY
    assert vault.status() == KeyStatus(configured=True)


@pytest.mark.parametrize("environ", [{}, {"MY_KEY": ""}, {"MY_KEY": "   "}])
def test_environment_vault_without_a_key(environ: dict[str, str]) -> None:
    vault = EnvironmentVault("MY_KEY", environ)
    assert vault.load() is None
    assert vault.status() == KeyStatus(configured=False)


def test_environment_vault_never_saves_or_clears() -> None:
    environ = {"MY_KEY": KEY}
    vault = EnvironmentVault("MY_KEY", environ)
    for action in (lambda: vault.save(KEY), vault.clear):
        with pytest.raises(KeychainUnavailableError) as info:
            action()
        assert ".env" in str(info.value)
        assert KEY not in str(info.value)
    assert environ == {"MY_KEY": KEY}


def test_environment_service_keys_map_each_key_to_its_variable() -> None:
    names: dict[KeyName, str] = {"openai": "A_KEY", "census": "B_KEY", "comptox": "C_KEY"}
    keys = environment_service_keys(names, {"A_KEY": KEY})
    assert keys.statuses() == {
        "openai": KeyStatus(configured=True),
        "census": KeyStatus(configured=False),
        "comptox": KeyStatus(configured=False),
    }

"""The provider API key, kept only in the OS credential store.

The key is saved, read and deleted through ``keyring`` (macOS Keychain, Linux Secret
Service, Windows Credential Locker) under a service and account named in ``[ui.keyring]``.
It is never written anywhere else and is handed out only as a ``SecretStr``. The CLI and the
web API share this vault, so both run on the same stored key.

Inside a container there is no OS keychain; the web program launched with ``--container``
uses ``EnvironmentVault`` instead, which reads each key from its environment variable and
never stores one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import SecretStr

from config.ui import KEY_NAMES, KeyName, get_ui_settings


class CredentialStore(Protocol):
    """The part of the ``keyring`` API the vault uses (the module itself satisfies it)."""

    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


ENVIRONMENT_ONLY = (
    "Keys come from the .env file on this installation (the OS keychain is unavailable); "
    "edit .env and restart to change them."
)


class KeyVault(Protocol):
    """Where one key is kept: save, read, clear and report it (never revealing it)."""

    def save(self, key: str) -> KeyStatus: ...

    def load(self) -> SecretStr | None: ...

    def clear(self) -> KeyStatus: ...

    def status(self) -> KeyStatus: ...


class KeychainUnavailableError(RuntimeError):
    """The OS credential store cannot be used; the message is safe to show to the user."""


class InvalidKeyError(ValueError):
    """A submitted key was rejected before storing; the message never contains the key."""


@dataclass(frozen=True)
class KeyStatus:
    """Whether a key is stored, and a hint that cannot be used to recover it."""

    configured: bool


def validate_key(key: str, max_length: int) -> str:
    """Return ``key`` if it is non-blank, printable without whitespace and not too long.

    Raises:
        InvalidKeyError: Naming the rule broken, never echoing the key.
    """
    if not key.strip():
        raise InvalidKeyError("The API key is empty.")
    if any(ch.isspace() or not ch.isprintable() for ch in key):
        raise InvalidKeyError("The API key must not contain spaces or control characters.")
    if len(key) > max_length:
        raise InvalidKeyError(f"The API key is longer than {max_length} characters.")
    return key


@dataclass(frozen=True)
class KeyringVault:
    """Save, read and clear the API key in the OS credential store.

    Attributes:
        service: Credential-store service name.
        account: Credential-store account name.
        max_length: Longest key accepted, characters.
        store: The credential store; defaults to the ``keyring`` module (inject a fake in tests).
    """

    service: str
    account: str
    max_length: int
    store: CredentialStore = keyring

    def save(self, key: str) -> KeyStatus:
        """Validate and store ``key``; returns the new status.

        Raises:
            InvalidKeyError: If the key is rejected (nothing is stored).
            KeychainUnavailableError: If the credential store cannot be used.
        """
        valid = validate_key(key, self.max_length)
        try:
            self.store.set_password(self.service, self.account, valid)
        except KeyringError as error:
            raise KeychainUnavailableError("The OS keychain is unavailable.") from error
        return KeyStatus(configured=True)

    def load(self) -> SecretStr | None:
        """Return the stored key, or None when there is none.

        Raises:
            KeychainUnavailableError: If the credential store cannot be used.
        """
        try:
            key = self.store.get_password(self.service, self.account)
        except KeyringError as error:
            raise KeychainUnavailableError("The OS keychain is unavailable.") from error
        return SecretStr(key) if key and key.strip() else None

    def clear(self) -> KeyStatus:
        """Delete the stored key; clearing an absent key succeeds.

        Raises:
            KeychainUnavailableError: If the credential store cannot be used.
        """
        try:
            self.store.delete_password(self.service, self.account)
        except PasswordDeleteError:
            pass  # nothing stored: already cleared
        except KeyringError as error:
            raise KeychainUnavailableError("The OS keychain is unavailable.") from error
        return KeyStatus(configured=False)

    def status(self) -> KeyStatus:
        """Return whether a key is stored (never any part of the key)."""
        key = self.load()
        if key is None:
            return KeyStatus(configured=False)
        return KeyStatus(configured=True)


@dataclass(frozen=True)
class EnvironmentVault:
    """A key read from an environment variable (``.env``); it cannot be saved or cleared here.

    Attributes:
        variable: Name of the environment variable holding the key.
        environ: The environment to read; ``os.environ`` when None (inject a dict in tests).
    """

    variable: str
    environ: Mapping[str, str] | None = None

    def save(self, key: str) -> KeyStatus:
        """Refuse: keys on this installation come from the environment.

        Raises:
            KeychainUnavailableError: Always, with a message saying where the keys come from.
        """
        raise KeychainUnavailableError(ENVIRONMENT_ONLY)

    def load(self) -> SecretStr | None:
        """Return the variable's key, or None when it is unset or blank."""
        environ = os.environ if self.environ is None else self.environ
        key = environ.get(self.variable, "").strip()
        return SecretStr(key) if key else None

    def clear(self) -> KeyStatus:
        """Refuse, like ``save``.

        Raises:
            KeychainUnavailableError: Always.
        """
        raise KeychainUnavailableError(ENVIRONMENT_ONLY)

    def status(self) -> KeyStatus:
        """Whether the variable holds a key (never any part of it)."""
        return KeyStatus(configured=self.load() is not None)


@dataclass(frozen=True)
class ServiceKeys:
    """The vaults of every key the interface stores (OpenAI, Census, CompTox), by name.

    Each key has its own credential-store entry, so saving or clearing one never touches
    another.
    """

    vaults: Mapping[KeyName, KeyVault]

    def vault(self, name: KeyName) -> KeyVault:
        """The vault of the key called ``name``."""
        return self.vaults[name]

    def statuses(self) -> dict[KeyName, KeyStatus]:
        """Whether each key is stored (never any part of a key).

        Raises:
            KeychainUnavailableError: If the credential store cannot be used.
        """
        return {name: vault.status() for name, vault in self.vaults.items()}


def default_service_keys(store: CredentialStore = keyring) -> ServiceKeys:
    """The vaults named by ``[ui.keyring]`` in the shipped settings (the outer edge)."""
    settings = get_ui_settings()
    return ServiceKeys(
        {
            name: KeyringVault(
                service=settings.keyring.service,
                account=settings.keyring.accounts[name],
                max_length=settings.max_key_length,
                store=store,
            )
            for name in KEY_NAMES
        },
    )


def environment_service_keys(
    variables: Mapping[KeyName, str],
    environ: Mapping[str, str] | None = None,
) -> ServiceKeys:
    """Vaults reading each key from its environment variable (containers have no keychain).

    Args:
        variables: Key name -> environment variable holding it (from the settings).
        environ: The environment to read; ``os.environ`` when None.
    """
    return ServiceKeys({name: EnvironmentVault(variables[name], environ) for name in KEY_NAMES})


def default_vault() -> KeyVault:
    """The OpenAI key's vault from the shipped settings (the outer edge)."""
    return default_service_keys().vault("openai")


def stored_key(vault: KeyVault) -> SecretStr | None:
    """Return the vault's key, or None when none is stored or the keychain is unavailable.

    For headless callers (CLI, CI) that may fall back to the environment variable.
    """
    try:
        return vault.load()
    except KeychainUnavailableError:
        return None

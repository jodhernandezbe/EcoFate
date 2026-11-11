"""Start-up of the key services: the key-encryption keys, the user vault and the operator keys.

The one place the web program reads its secrets from the environment and registers them for
redaction for the life of the process. A missing or malformed key-encryption key stops the
program with a message naming the variable (never its value).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

from app.operator_keys import OperatorKeys, load_operator_keys
from app.process_secrets import process_secret_values, process_secrets
from app.redaction import protect_for_process
from app.turns.keys import TurnKeys, load_turn_keys
from app.user_key_vault import (
    KekConfigurationError,
    KeyEncryptionKeys,
    SealedCredentialStore,
    UserKeyVault,
    load_keks,
)
from config.byok import get_byok_settings
from config.loader import get_comptox_settings
from config.population import get_population_settings
from config.ui import get_ui_settings

__all__ = [
    "KeyLoader",
    "KeyServices",
    "build_key_services",
    "load_key_config",
    "process_secret_values",
    "protect_process_secrets",
    "turn_key_loader",
]


@dataclass(frozen=True)
class KeyServices:
    """What the app keeps for keys: the user vault and the operator's service keys.

    Attributes:
        vault: Each user's sealed OpenAI key.
        operator: The Census and CompTox keys this installation provides.
    """

    vault: UserKeyVault
    operator: OperatorKeys


KeyLoader = Callable[[], Awaitable[TurnKeys]]


def turn_key_loader(services: KeyServices, user_id: UUID) -> KeyLoader:
    """The loader one turn of ``user_id`` calls once: their decrypted key plus the operator's."""
    return lambda: load_turn_keys(services.vault, services.operator, user_id)


def load_key_config(environ: Mapping[str, str]) -> tuple[KeyEncryptionKeys, OperatorKeys]:
    """Read the key-encryption keys and the operator keys; protect every process secret.

    Raises:
        SystemExit: With a message naming the variable when a key-encryption key is missing
            or malformed.
    """
    try:
        keks = load_keks(environ, get_byok_settings())
    except KekConfigurationError as error:
        raise SystemExit(str(error)) from None
    operator = load_operator_keys(
        environ,
        get_population_settings().api_key_env_var,
        get_comptox_settings().api_key_env_var,
    )
    protect_process_secrets(environ)
    return keks, operator


def protect_process_secrets(environ: Mapping[str, str], keys: KeyServices | None = None) -> None:
    """Redact the process's secret variables (and the operator keys of ``keys``) from logs for
    the life of the process."""
    protect_for_process(process_secrets(environ))
    if keys is not None:
        protect_for_process(keys.operator.values())


def build_key_services(
    keks: KeyEncryptionKeys,
    operator: OperatorKeys,
    store: SealedCredentialStore,
) -> KeyServices:
    """The vault over ``store`` with the configured maximum key length, and the operator keys."""
    return KeyServices(UserKeyVault(store, keks, get_ui_settings().max_key_length), operator)

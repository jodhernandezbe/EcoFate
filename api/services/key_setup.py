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
from app.redaction import protect_for_process
from app.turns.keys import TurnKeys, load_turn_keys
from app.user_key_vault import (
    KekConfigurationError,
    KeyEncryptionKeys,
    SealedCredentialStore,
    UserKeyVault,
    load_keks,
)
from config.agent import get_agent_settings
from config.auth import get_auth_settings
from config.byok import get_byok_settings
from config.database import get_database_settings
from config.loader import get_comptox_settings
from config.mail import get_mail_settings
from config.population import get_population_settings
from config.telemetry import get_telemetry_settings
from config.ui import get_ui_settings


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
    protect_for_process(_process_secrets(environ))
    if keys is not None:
        protect_for_process(keys.operator.values())


def _process_secrets(environ: Mapping[str, str]) -> list[str]:
    """Values of the secret variables that are set: never logged, never put in a span."""
    monitoring = get_telemetry_settings()
    names = (
        get_auth_settings().session_secret_env_var,
        get_mail_settings().variables.password,
        monitoring.write_token_env_var,
        monitoring.read_token_env_var,
        get_agent_settings().api_key_env_var,  # not used by the web program; still never shown
        get_database_settings().url_env_var,  # the URL carries the database password
    )
    return [value.strip() for name in names if (value := environ.get(name))]


def process_secret_values(environ: Mapping[str, str]) -> list[str]:
    """Every secret this program reads from the environment, for span scrubbing at set-up: the
    process secrets, the operator's service keys and the key-encryption keys (raw, as written)."""
    byok = get_byok_settings()
    names = (
        get_population_settings().api_key_env_var,
        get_comptox_settings().api_key_env_var,
        byok.kek_env_var,
        byok.previous_kek_env_var,
    )
    own = [value.strip() for name in names if (value := environ.get(name))]
    return [*_process_secrets(environ), *own]


def build_key_services(
    keks: KeyEncryptionKeys,
    operator: OperatorKeys,
    store: SealedCredentialStore,
) -> KeyServices:
    """The vault over ``store`` with the configured maximum key length, and the operator keys."""
    return KeyServices(UserKeyVault(store, keks, get_ui_settings().max_key_length), operator)

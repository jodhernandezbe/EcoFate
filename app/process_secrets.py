"""The secrets a web process (the API or a background worker) reads from its environment.

Their values are protected from the logs for the life of the process and scrubbed from spans;
only the names come from configuration. Never logged, never returned.
"""

from __future__ import annotations

from collections.abc import Mapping

from config.agent import get_agent_settings
from config.auth import get_auth_settings
from config.byok import get_byok_settings
from config.database import get_database_settings
from config.loader import get_comptox_settings
from config.mail import get_mail_settings
from config.population import get_population_settings
from config.telemetry import get_telemetry_settings
from config.worker import get_worker_settings


def _values(environ: Mapping[str, str], names: tuple[str, ...]) -> list[str]:
    return [value.strip() for name in names if (value := environ.get(name))]


def process_secrets(environ: Mapping[str, str]) -> list[str]:
    """Values of the process's own secret variables that are set (session secret, SMTP and
    Logfire tokens, the database and Redis URLs, which carry passwords)."""
    monitoring = get_telemetry_settings()
    names = (
        get_auth_settings().session_secret_env_var,
        get_mail_settings().variables.password,
        monitoring.write_token_env_var,
        monitoring.read_token_env_var,
        get_agent_settings().api_key_env_var,  # not used by the web program; still never shown
        get_database_settings().url_env_var,
        get_worker_settings().redis_url_env_var,
    )
    return _values(environ, names)


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
    return [*process_secrets(environ), *_values(environ, names)]

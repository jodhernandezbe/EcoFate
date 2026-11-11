"""The operator's service keys (Census, CompTox): read once from the server environment.

They belong to whoever runs the installation, never to a user: no route accepts, stores or
returns them. They are read at start-up, protected from logs and spans for the life of the
process, and given to the tools for each turn like the user's own key.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import SecretStr

from app.key_vault import EnvironmentVault
from app.redaction import protect_for_process


@dataclass(frozen=True)
class OperatorKeys:
    """The service keys this installation provides; None for a key that is not set.

    Attributes:
        census: The Census Data API key.
        comptox: The CompTox Chemicals Dashboard API key.
    """

    census: SecretStr | None = None
    comptox: SecretStr | None = None

    def available(self) -> dict[str, bool]:
        """Whether each service is available on this installation (never any key)."""
        return {"census": self.census is not None, "comptox": self.comptox is not None}

    def values(self) -> list[str]:
        """The raw values, for log protection only."""
        keys = (self.census, self.comptox)
        return [key.get_secret_value() for key in keys if key is not None]


def load_operator_keys(
    environ: Mapping[str, str],
    census_variable: str,
    comptox_variable: str,
) -> OperatorKeys:
    """Read the two keys from their environment variables and protect them for the process."""
    keys = OperatorKeys(
        census=EnvironmentVault(census_variable, environ).load(),
        comptox=EnvironmentVault(comptox_variable, environ).load(),
    )
    protect_for_process(keys.values())
    return keys

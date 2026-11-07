"""The keys of one turn: read once, given to the tools and kept out of the logs while it runs."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass

from pydantic import SecretStr

from app.key_vault import KeychainUnavailableError, ServiceKeys, stored_key
from app.redaction import protect_secrets
from app.turns.failures import FailureReason, KeysUnavailableError
from tools.credentials import HOLDERS


@dataclass(frozen=True)
class TurnKeys:
    """The keys read for one turn: the model key, and the service keys when stored."""

    openai: SecretStr
    census: SecretStr | None = None
    comptox: SecretStr | None = None

    def named(self) -> tuple[tuple[str, SecretStr], ...]:
        """Each present key with its holder name."""
        keys = (("openai", self.openai), ("census", self.census), ("comptox", self.comptox))
        return tuple((name, key) for name, key in keys if key is not None)

    def values(self) -> list[str]:
        """The raw values, for log protection (never stored anywhere)."""
        return [key.get_secret_value() for _, key in self.named()]


def load_turn_keys(keys: ServiceKeys) -> TurnKeys:
    """Read each stored key once. Only the model key is required.

    Raises:
        KeysUnavailableError: The keychain cannot be used, or no model key is stored.
    """
    try:
        openai = keys.vault("openai").load()
    except KeychainUnavailableError as error:
        raise KeysUnavailableError(FailureReason.KEYCHAIN_UNAVAILABLE) from error
    if openai is None:
        raise KeysUnavailableError(FailureReason.NO_KEY)
    return TurnKeys(
        openai=openai,
        census=stored_key(keys.vault("census")),
        comptox=stored_key(keys.vault("comptox")),
    )


@contextmanager
def provided(keys: TurnKeys) -> Generator[None]:
    """Give each key to the tools that need it, and keep them out of the logs, for the block.

    Released on every exit: success, failure and cancellation alike.
    """
    with ExitStack() as stack:
        stack.enter_context(protect_secrets(keys.values()))
        for name, key in keys.named():
            stack.enter_context(HOLDERS[name].provide(key))
        yield

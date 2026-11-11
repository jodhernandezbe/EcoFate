"""The keys of one turn: read once, given to the tools and kept out of the logs while it runs.

The user's model key is decrypted here and only here per turn; the operator's service keys come
from the environment through ``OperatorKeys``.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from app.operator_keys import OperatorKeys
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


class UserKeyReader(Protocol):
    """The one way to obtain a user's model key (``app.user_key_vault.UserKeyVault``)."""

    async def read(self, user_id: UUID) -> SecretStr | None: ...


async def load_turn_keys(
    vault: UserKeyReader,
    operator: OperatorKeys,
    user_id: UUID,
) -> TurnKeys:
    """Decrypt the user's model key once and add the operator's service keys.

    Only the model key is required; a service key the installation does not provide is None.

    Raises:
        KeysUnavailableError: The user has no usable model key; the operator keys are not
            consulted then, and no model is built.
    """
    openai = await vault.read(user_id)
    if openai is None:
        raise KeysUnavailableError(FailureReason.NO_KEY)
    return TurnKeys(openai=openai, census=operator.census, comptox=operator.comptox)


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

"""The keys of one job: the operator's service keys only, for the job's duration.

A job calls the data services (CompTox, Census) with the operator's keys and never uses the
user's model key: nothing here, or in the runner, reads the user's key vault.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from app.operator_keys import OperatorKeys
from app.redaction import protect_secrets
from tools.credentials import CENSUS_KEY, COMPTOX_KEY


@contextmanager
def provided_operator(keys: OperatorKeys) -> Generator[None]:
    """Give the operator's keys to the tools, and keep them out of the logs, for the block.

    Released on every exit: success, failure and cancellation alike. The user's model key
    (``PROVIDER_KEY``) is never provided.
    """
    with ExitStack() as stack:
        stack.enter_context(protect_secrets(keys.values()))
        for holder, key in ((CENSUS_KEY, keys.census), (COMPTOX_KEY, keys.comptox)):
            if key is not None:
                stack.enter_context(holder.provide(key))
        yield

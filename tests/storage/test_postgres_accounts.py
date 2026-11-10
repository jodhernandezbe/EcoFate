"""PostgreSQL behaviour of the account repositories and the 0003 migration (``postgres`` marker).

Each test works in its own migrated schema (``tests/postgres.py``), dropped afterwards.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.usage_meter import CallUsage
from storage.account_model import Role, TokenPurpose
from storage.auth_tokens import AuthTokenRepository
from storage.engine import create_engine
from storage.keys import ThreadKey
from storage.login_attempts import LoginAttemptRepository
from storage.tables import metadata
from storage.user_sessions import SessionRepository
from storage.users import UserRepository
from tests.postgres import SETTINGS, Database, database, migrated_schema, run_alembic, test_url

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@dataclass
class Repos:
    db: Database
    users: UserRepository
    sessions: SessionRepository
    tokens: AuthTokenRepository
    attempts: LoginAttemptRepository


@pytest.fixture
async def repos() -> AsyncGenerator[Repos]:
    async with database() as db:
        factory = async_sessionmaker(db.engine)
        yield Repos(
            db,
            UserRepository(factory),
            SessionRepository(factory),
            AuthTokenRepository(factory),
            LoginAttemptRepository(factory),
        )


async def _sql(engine: AsyncEngine, statement: str, **values: object) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(statement), values)


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        return int((await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())  # noqa: S608  # nosec B608


async def _user(repos: Repos, email: str = "a@example.test") -> UUID:
    user = await repos.users.create(email, "hash-a")
    assert user is not None
    return user.id


# --- users ----------------------------------------------------------------------------------


async def test_a_new_account_is_an_unverified_user(repos: Repos) -> None:
    user = await repos.users.create("a@example.test", "hash-a")
    assert user is not None
    assert (user.role, user.verified, user.password_hash) == (Role.USER, False, "hash-a")
    assert await repos.users.by_email("a@example.test") == user
    assert await repos.users.by_id(user.id) == user


async def test_a_second_account_with_the_same_email_is_refused_and_changes_nothing(
    repos: Repos,
) -> None:
    first = await repos.users.create("a@example.test", "hash-a")
    assert first is not None
    assert await repos.users.create("a@example.test", "hash-b", role=Role.ADMIN) is None
    assert await repos.users.by_email("a@example.test") == first


async def test_an_account_can_be_created_verified_as_admin(repos: Repos) -> None:
    admin = await repos.users.create("root@example.test", "h", role=Role.ADMIN, verified=True)
    assert admin is not None and admin.verified and admin.role is Role.ADMIN


async def test_unknown_accounts_are_absent(repos: Repos) -> None:
    assert await repos.users.by_email("nobody@example.test") is None
    assert await repos.users.by_id(uuid4()) is None
    assert not await repos.users.set_password(uuid4(), "h")
    assert not await repos.users.delete(uuid4())


async def test_password_role_and_verification_change(repos: Repos) -> None:
    user_id = await _user(repos)
    assert await repos.users.set_password(user_id, "hash-new")
    assert await repos.users.set_role(user_id, Role.ADMIN)
    assert await repos.users.mark_verified(user_id)
    first = await repos.users.by_id(user_id)
    assert first is not None and first.verified_at is not None
    assert (first.password_hash, first.role) == ("hash-new", Role.ADMIN)
    await repos.users.mark_verified(user_id)  # the first time stays
    again = await repos.users.by_id(user_id)
    assert again is not None and again.verified_at == first.verified_at


async def test_a_row_with_an_unknown_role_reads_as_absent(repos: Repos) -> None:
    user_id = await _user(repos)
    await _sql(repos.db.engine, "ALTER TABLE users DROP CONSTRAINT ck_users_role_known")
    await _sql(repos.db.engine, "UPDATE users SET role = 'root' WHERE id = :id", id=user_id)
    assert await repos.users.by_id(user_id) is None


async def test_emails_of_known_accounts_only(repos: Repos) -> None:
    first = await _user(repos, "a@example.test")
    gone = await _user(repos, "b@example.test")
    await repos.users.delete(gone)
    assert await repos.users.emails([first, gone, uuid4()]) == {first: "a@example.test"}
    assert await repos.users.emails([]) == {}


async def test_deleting_an_account_deletes_everything_that_refers_to_it(repos: Repos) -> None:
    user_id = await _user(repos)
    other = await _user(repos, "b@example.test")
    key = ThreadKey(user_id, "t1")
    await repos.sessions.create("hash-s", user_id, idle_seconds=60, absolute_seconds=60)
    await repos.tokens.issue(user_id, TokenPurpose.VERIFY_EMAIL, "hash-t", 60)
    await repos.db.store.claim(key)
    assert await repos.db.store.turns.begin(key) is not None
    await repos.db.store.add_usage(key, [CallUsage("m", 1, 0, 1)])
    await repos.db.store.record_answers(key, {"a": 1.0}, [])
    await repos.db.store.set_pending(key, None)
    keep = ThreadKey(other, "t1")
    await repos.db.store.claim(keep)
    assert await repos.users.delete(user_id)
    for table in ("sessions", "auth_tokens", "turns", "thread_usage", "thread_answers"):
        assert await _count(repos.db.engine, table) == (1 if table == "threads" else 0), table
    assert await _count(repos.db.engine, "threads") == 1
    assert await repos.db.store.holds(keep)


# --- sessions -------------------------------------------------------------------------------


async def test_a_live_session_resolves_to_its_account_and_stores_only_the_hash(
    repos: Repos,
) -> None:
    user_id = await _user(repos)
    await repos.sessions.create("hash-s", user_id, idle_seconds=60, absolute_seconds=3600)
    user = await repos.sessions.resolve("hash-s", 60)
    assert user is not None and user.id == user_id
    assert await repos.sessions.resolve("hash-s-other", 60) is None


async def test_an_idle_session_expires_and_its_row_is_deleted(repos: Repos) -> None:
    user_id = await _user(repos)
    await repos.sessions.create("hash-s", user_id, idle_seconds=60, absolute_seconds=3600)
    await _sql(
        repos.db.engine,
        "UPDATE sessions SET idle_expires_at = now() - interval '1 second'",
    )
    assert await repos.sessions.resolve("hash-s", 60) is None
    assert await _count(repos.db.engine, "sessions") == 0


async def test_an_absolutely_expired_session_ends_whatever_its_activity(repos: Repos) -> None:
    user_id = await _user(repos)
    await repos.sessions.create("hash-s", user_id, idle_seconds=60, absolute_seconds=3600)
    await _sql(
        repos.db.engine,
        "UPDATE sessions SET absolute_expires_at = now() - interval '1 second'",
    )
    assert await repos.sessions.resolve("hash-s", 10_000) is None
    assert await _count(repos.db.engine, "sessions") == 0


async def test_activity_moves_the_idle_expiry_but_never_past_the_absolute_one(
    repos: Repos,
) -> None:
    user_id = await _user(repos)
    await repos.sessions.create("hash-s", user_id, idle_seconds=60, absolute_seconds=120)
    await repos.sessions.resolve("hash-s", 100_000)
    async with repos.db.engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT idle_expires_at = absolute_expires_at FROM sessions"),
            )
        ).scalar_one()
    assert row is True


async def test_revoke_one_all_or_all_but_one(repos: Repos) -> None:
    user_id = await _user(repos)
    other = await _user(repos, "b@example.test")
    for name in ("s1", "s2", "s3"):
        await repos.sessions.create(name, user_id, idle_seconds=60, absolute_seconds=60)
    await repos.sessions.create("theirs", other, idle_seconds=60, absolute_seconds=60)
    assert await repos.sessions.revoke("s1")
    assert not await repos.sessions.revoke("s1")
    assert await repos.sessions.revoke_all(user_id, keep="s2") == 1
    assert await repos.sessions.resolve("s2", 60) is not None
    assert await repos.sessions.revoke_all(user_id) == 1
    assert await repos.sessions.resolve("theirs", 60) is not None


async def test_purge_expired_keeps_live_sessions(repos: Repos) -> None:
    user_id = await _user(repos)
    await repos.sessions.create("old", user_id, idle_seconds=60, absolute_seconds=60)
    await repos.sessions.create("new", user_id, idle_seconds=60, absolute_seconds=60)
    await _sql(
        repos.db.engine,
        "UPDATE sessions SET idle_expires_at = now() - interval '1 second' "
        "WHERE token_hash = 'old'",
    )
    assert await repos.sessions.purge_expired() == 1
    assert await _count(repos.db.engine, "sessions") == 1


# --- single-use tokens ----------------------------------------------------------------------


async def test_a_token_is_used_once(repos: Repos) -> None:
    user_id = await _user(repos)
    await repos.tokens.issue(user_id, TokenPurpose.VERIFY_EMAIL, "hash-t", 60)
    assert await repos.tokens.consume(TokenPurpose.VERIFY_EMAIL, "hash-t") == user_id
    assert await repos.tokens.consume(TokenPurpose.VERIFY_EMAIL, "hash-t") is None


async def test_an_expired_unknown_or_other_purpose_token_is_refused(repos: Repos) -> None:
    user_id = await _user(repos)
    await repos.tokens.issue(user_id, TokenPurpose.RESET_PASSWORD, "hash-t", 60)
    assert await repos.tokens.consume(TokenPurpose.VERIFY_EMAIL, "hash-t") is None
    assert await repos.tokens.consume(TokenPurpose.RESET_PASSWORD, "no-such-hash") is None
    await _sql(repos.db.engine, "UPDATE auth_tokens SET expires_at = now() - interval '1 second'")
    assert await repos.tokens.consume(TokenPurpose.RESET_PASSWORD, "hash-t") is None


async def test_a_newer_token_replaces_older_unused_ones_of_the_same_purpose(
    repos: Repos,
) -> None:
    user_id = await _user(repos)
    await repos.tokens.issue(user_id, TokenPurpose.RESET_PASSWORD, "first", 60)
    await repos.tokens.issue(user_id, TokenPurpose.VERIFY_EMAIL, "other-purpose", 60)
    await repos.tokens.issue(user_id, TokenPurpose.RESET_PASSWORD, "second", 60)
    assert await repos.tokens.consume(TokenPurpose.RESET_PASSWORD, "first") is None
    assert await repos.tokens.consume(TokenPurpose.RESET_PASSWORD, "second") == user_id
    assert await repos.tokens.consume(TokenPurpose.VERIFY_EMAIL, "other-purpose") == user_id


async def test_invalidate_drops_unused_tokens_of_one_purpose(repos: Repos) -> None:
    user_id = await _user(repos)
    await repos.tokens.issue(user_id, TokenPurpose.RESET_PASSWORD, "t", 60)
    assert await repos.tokens.invalidate(user_id, TokenPurpose.RESET_PASSWORD) == 1
    assert await repos.tokens.consume(TokenPurpose.RESET_PASSWORD, "t") is None


async def test_two_concurrent_uses_of_one_token_succeed_once(repos: Repos) -> None:
    user_id = await _user(repos)
    other_engine = create_engine(repos.db.url, SETTINGS, search_path=repos.db.schema)
    try:
        second = AuthTokenRepository(async_sessionmaker(other_engine))
        for trial in range(10):
            name = f"race-{trial}"
            await repos.tokens.issue(user_id, TokenPurpose.RESET_PASSWORD, name, 60)
            results = await asyncio.gather(
                repos.tokens.consume(TokenPurpose.RESET_PASSWORD, name),
                second.consume(TokenPurpose.RESET_PASSWORD, name),
            )
            assert sorted(result is None for result in results) == [False, True], name
    finally:
        await other_engine.dispose()


# --- login attempts -------------------------------------------------------------------------


async def test_failures_add_up_and_block_at_the_limit(repos: Repos) -> None:
    assert await repos.attempts.retry_after("email:a", 600, 3) is None
    for expected in (1, 2, 3):
        assert await repos.attempts.record_failure("email:a", 600) == expected
    wait = await repos.attempts.retry_after("email:a", 600, 3)
    assert wait is not None and 1 <= wait <= 600
    assert await repos.attempts.retry_after("email:a", 600, 4) is None
    assert await repos.attempts.retry_after("email:b", 600, 3) is None


async def test_a_failure_after_the_window_starts_a_new_one(repos: Repos) -> None:
    await repos.attempts.record_failure("ip:1", 600)
    await repos.attempts.record_failure("ip:1", 600)
    await _sql(
        repos.db.engine,
        "UPDATE login_attempts SET window_start = now() - interval '1 hour'",
    )
    assert await repos.attempts.retry_after("ip:1", 600, 2) is None
    assert await repos.attempts.record_failure("ip:1", 600) == 1


async def test_concurrent_failures_are_all_counted(repos: Repos) -> None:
    await asyncio.gather(*(repos.attempts.record_failure("email:c", 600) for _ in range(8)))
    assert await repos.attempts.record_failure("email:c", 600) == 9


async def test_clear_forgets_the_failures(repos: Repos) -> None:
    await repos.attempts.record_failure("email:a", 600)
    await repos.attempts.clear("email:a")
    assert await repos.attempts.record_failure("email:a", 600) == 1


# --- the migration --------------------------------------------------------------------------


def _differences(connection: Connection) -> list[object]:
    return list(compare_metadata(MigrationContext.configure(connection), metadata))


async def test_the_migrated_schema_matches_the_table_definitions() -> None:
    async with migrated_schema(test_url()) as engine, engine.connect() as connection:
        assert await connection.run_sync(_differences) == []


async def test_upgrading_deletes_threads_made_before_accounts() -> None:
    async with migrated_schema(test_url()) as engine:
        async with engine.begin() as connection:
            await connection.run_sync(run_alembic, "downgrade", "0002")
        await _sql(engine, "INSERT INTO threads (id) VALUES ('old')")
        await _sql(
            engine,
            "INSERT INTO turns (id, thread_id, status) VALUES ('t', 'old', 'queued')",
        )
        await _sql(
            engine,
            "INSERT INTO thread_answers (thread_id, key, value) VALUES ('old', 'k', 1.0)",
        )
        async with engine.begin() as connection:
            await connection.run_sync(run_alembic, "upgrade", "head")
        for table in ("threads", "turns", "thread_answers"):
            assert await _count(engine, table) == 0, table


async def test_the_database_refuses_a_thread_without_an_owner_or_with_an_unknown_one() -> None:
    from sqlalchemy.exc import IntegrityError

    async with migrated_schema(test_url()) as engine:
        with pytest.raises(IntegrityError):
            await _sql(engine, "INSERT INTO threads (id) VALUES ('t')")
        with pytest.raises(IntegrityError):
            await _sql(
                engine,
                "INSERT INTO threads (owner_id, id) VALUES (:owner, 't')",
                owner=uuid4(),
            )

"""The account flows over in-memory stores: one negative test per rule."""

from __future__ import annotations

from typing import cast

import pytest

from api.core.exceptions import FieldRejected, Refusal
from api.services.auth.flows import (
    INVALID_CREDENTIALS,
    INVALID_LINK,
    SIGNUP_CLOSED,
    SignedIn,
    VerificationRequired,
)
from api.services.auth.messages import EXISTING_SUBJECT, RESET_SUBJECT, VERIFY_SUBJECT
from storage.account_model import Role
from storage.keys import ThreadKey
from tests.api.auth_support import (
    ADDRESS,
    EMAIL,
    NORMAL_EMAIL,
    PASSWORD,
    AuthKit,
    fast_settings,
    make_auth,
    token_in,
)
from tests.fakes_accounts import InMemorySessions

pytestmark = pytest.mark.anyio


async def _registered(kit: AuthKit, *, verified: bool = True, email: str = NORMAL_EMAIL) -> str:
    """A signed-up (and, by default, verified) account; its normal email."""
    mail = await kit.service.sign_up(email, PASSWORD)
    if verified:
        await kit.service.verify_email(token_in(mail.body))
    return email


async def _sign_in(kit: AuthKit, email: str = NORMAL_EMAIL, password: str = PASSWORD) -> SignedIn:
    result = await kit.service.sign_in(email, password, None, ADDRESS)
    assert isinstance(result, SignedIn)
    return result


# --- sign up --------------------------------------------------------------------------------


async def test_sign_up_makes_an_unverified_user_with_a_hashed_password_and_mails_a_link() -> None:
    kit = make_auth()
    mail = await kit.service.sign_up(EMAIL, PASSWORD)
    user = await kit.accounts.users.by_email(NORMAL_EMAIL)
    assert user is not None and (user.role, user.verified) == (Role.USER, False)
    assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash
    assert (mail.to, mail.subject) == (NORMAL_EMAIL, VERIFY_SUBJECT)


async def test_signing_up_with_a_taken_email_makes_no_account_and_mails_its_owner() -> None:
    kit = make_auth()
    await _registered(kit)
    before = await kit.accounts.users.by_email(NORMAL_EMAIL)
    mail = await kit.service.sign_up(NORMAL_EMAIL, "another long password")
    assert (mail.to, mail.subject) == (NORMAL_EMAIL, EXISTING_SUBJECT)
    assert await kit.accounts.users.by_email(NORMAL_EMAIL) == before  # password unchanged
    assert "#" not in mail.body  # no token to take over the account


@pytest.mark.parametrize("password", ["short", "a" * 129, NORMAL_EMAIL])
async def test_sign_up_rejects_a_bad_password_naming_the_field(password: str) -> None:
    kit = make_auth()
    with pytest.raises(FieldRejected) as raised:
        await kit.service.sign_up(NORMAL_EMAIL, password)
    assert raised.value.field == "password"
    assert await kit.accounts.users.by_email(NORMAL_EMAIL) is None


async def test_sign_up_rejects_a_bad_email_naming_the_field() -> None:
    kit = make_auth()
    with pytest.raises(FieldRejected) as raised:
        await kit.service.sign_up("not an email", PASSWORD)
    assert raised.value.field == "email"


async def test_sign_up_when_closed_is_a_403_and_creates_nothing() -> None:
    kit = make_auth(fast_settings(signup_open=False))
    with pytest.raises(Refusal) as raised:
        await kit.service.sign_up(NORMAL_EMAIL, PASSWORD)
    assert (raised.value.status, raised.value.detail) == (403, SIGNUP_CLOSED)
    assert await kit.accounts.users.by_email(NORMAL_EMAIL) is None


# --- verification ---------------------------------------------------------------------------


async def test_verification_marks_the_account_and_cannot_be_reused() -> None:
    kit = make_auth()
    mail = await kit.service.sign_up(NORMAL_EMAIL, PASSWORD)
    token = token_in(mail.body)
    await kit.service.verify_email(token)
    user = await kit.accounts.users.by_email(NORMAL_EMAIL)
    assert user is not None and user.verified
    with pytest.raises(Refusal) as raised:
        await kit.service.verify_email(token)
    assert (raised.value.status, raised.value.detail) == (400, INVALID_LINK)


async def test_an_expired_verification_token_leaves_the_account_unverified() -> None:
    kit = make_auth()
    token = token_in((await kit.service.sign_up(NORMAL_EMAIL, PASSWORD)).body)
    kit.clock.advance(kit.settings.verification_token_hours * 3600 + 1)
    with pytest.raises(Refusal):
        await kit.service.verify_email(token)
    user = await kit.accounts.users.by_email(NORMAL_EMAIL)
    assert user is not None and not user.verified


async def test_resend_mails_only_an_unverified_account_and_supersedes_the_old_link() -> None:
    kit = make_auth()
    old = token_in((await kit.service.sign_up(NORMAL_EMAIL, PASSWORD)).body)
    mail = await kit.service.resend_verification(NORMAL_EMAIL, ADDRESS)
    assert mail is not None
    with pytest.raises(Refusal):
        await kit.service.verify_email(old)
    await kit.service.verify_email(token_in(mail.body))
    assert await kit.service.resend_verification(NORMAL_EMAIL, ADDRESS) is None  # verified
    assert await kit.service.resend_verification("nobody@example.com", "10.0.0.1") is None
    assert await kit.service.resend_verification("garbage", "10.0.0.2") is None


# --- sign in --------------------------------------------------------------------------------


async def test_sign_in_starts_a_session_for_a_verified_account() -> None:
    kit = make_auth()
    await _registered(kit)
    signed = await _sign_in(kit, EMAIL)  # the email is normalised
    assert signed.user.email == NORMAL_EMAIL
    assert await kit.sessions.resolve(signed.session_token) == signed.user


async def test_a_wrong_password_and_an_unknown_email_are_refused_identically() -> None:
    kit = make_auth()
    await _registered(kit)
    refusals = []
    for email, password in ((NORMAL_EMAIL, "wrong password!!"), ("nobody@example.com", PASSWORD)):
        with pytest.raises(Refusal) as raised:
            await kit.service.sign_in(email, password, None, ADDRESS)
        refusals.append((raised.value.status, raised.value.detail, raised.value.headers))
    assert refusals[0] == refusals[1] == (401, INVALID_CREDENTIALS, None)


async def test_an_unknown_email_still_costs_one_password_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = make_auth()
    calls: list[str] = []
    original = kit.passwords.verify_unknown

    async def spy(password: str) -> None:
        calls.append(password)
        await original(password)

    monkeypatch.setattr(kit.passwords, "verify_unknown", spy)
    with pytest.raises(Refusal):
        await kit.service.sign_in("nobody@example.com", PASSWORD, None, ADDRESS)
    with pytest.raises(Refusal):
        await kit.service.sign_in("not an email", PASSWORD, None, ADDRESS)
    assert calls == [PASSWORD, PASSWORD]


async def test_the_right_password_on_an_unverified_account_gives_no_session() -> None:
    kit = make_auth()
    await _registered(kit, verified=False)
    result = await kit.service.sign_in(NORMAL_EMAIL, PASSWORD, None, ADDRESS)
    assert result == VerificationRequired()
    assert cast(InMemorySessions, kit.accounts.sessions).rows == {}


async def test_the_wrong_password_on_an_unverified_account_does_not_say_it_is_unverified() -> None:
    kit = make_auth()
    await _registered(kit, verified=False)
    with pytest.raises(Refusal) as raised:
        await kit.service.sign_in(NORMAL_EMAIL, "wrong password!!", None, ADDRESS)
    assert raised.value.detail == INVALID_CREDENTIALS


async def test_signing_in_replaces_a_session_cookie_the_browser_already_had() -> None:
    kit = make_auth()
    await _registered(kit)
    planted = (await _sign_in(kit)).session_token
    fresh = await kit.service.sign_in(NORMAL_EMAIL, PASSWORD, planted, ADDRESS)
    assert isinstance(fresh, SignedIn) and fresh.session_token != planted
    assert await kit.sessions.resolve(planted) is None


async def test_sign_out_ends_the_session() -> None:
    kit = make_auth()
    await _registered(kit)
    token = (await _sign_in(kit)).session_token
    await kit.service.sign_out(token)
    assert await kit.sessions.resolve(token) is None
    await kit.service.sign_out(None)


async def test_sign_in_upgrades_a_hash_made_with_old_parameters() -> None:
    from dataclasses import replace

    from api.services.auth.passwords import Passwords
    from config.auth import Argon2Settings

    kit = make_auth()
    await _registered(kit)
    user = await kit.accounts.users.by_email(NORMAL_EMAIL)
    assert user is not None
    weak = Passwords(replace(kit.settings, argon2=Argon2Settings(2, 16, 1)))
    await kit.accounts.users.set_password(user.id, await weak.hash(PASSWORD))
    await _sign_in(kit)
    upgraded = await kit.accounts.users.by_email(NORMAL_EMAIL)
    assert upgraded is not None and not kit.passwords.needs_rehash(upgraded.password_hash)


# --- throttling -----------------------------------------------------------------------------


async def test_after_the_limit_even_the_right_password_gets_429_and_is_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit = make_auth()
    await _registered(kit)
    for _ in range(kit.settings.throttle.attempts):
        with pytest.raises(Refusal):
            await kit.service.sign_in(NORMAL_EMAIL, "wrong password!!", None, ADDRESS)
    checked: list[str] = []

    async def spy(stored: str, password: str) -> bool:
        checked.append(password)
        return True

    monkeypatch.setattr(kit.passwords, "verify", spy)
    with pytest.raises(Refusal) as raised:
        await kit.service.sign_in(NORMAL_EMAIL, PASSWORD, None, ADDRESS)
    assert raised.value.status == 429 and checked == []
    assert int(raised.value.headers["Retry-After"]) >= 1  # type: ignore[index]


async def test_the_address_limit_holds_across_different_emails() -> None:
    kit = make_auth()
    for index in range(kit.settings.throttle.attempts):
        with pytest.raises(Refusal):
            await kit.service.sign_in(f"u{index}@example.com", PASSWORD, None, ADDRESS)
    with pytest.raises(Refusal) as raised:
        await kit.service.sign_in("fresh@example.com", PASSWORD, None, ADDRESS)
    assert raised.value.status == 429
    with pytest.raises(Refusal) as elsewhere:
        await kit.service.sign_in("fresh@example.com", PASSWORD, None, "198.51.100.1")
    assert elsewhere.value.status == 401


async def test_the_email_limit_holds_across_addresses_and_ends_with_the_window() -> None:
    kit = make_auth()
    await _registered(kit)
    for index in range(kit.settings.throttle.attempts):
        with pytest.raises(Refusal):
            await kit.service.sign_in(NORMAL_EMAIL, "wrong password!!", None, f"10.0.0.{index}")
    with pytest.raises(Refusal) as raised:
        await kit.service.sign_in(NORMAL_EMAIL, PASSWORD, None, "10.9.9.9")
    assert raised.value.status == 429
    kit.clock.advance(kit.settings.throttle.window_seconds + 1)
    await _sign_in(kit)


async def test_a_success_forgives_the_accounts_failures_but_not_the_addresses() -> None:
    kit = make_auth()
    await _registered(kit)
    for _ in range(kit.settings.throttle.attempts - 1):
        with pytest.raises(Refusal):
            await kit.service.sign_in(NORMAL_EMAIL, "wrong password!!", None, ADDRESS)
    await _sign_in(kit)
    with pytest.raises(Refusal) as raised:  # the address already has attempts - 1 failures
        await kit.service.sign_in("other@example.com", PASSWORD, None, ADDRESS)
        await kit.service.sign_in("other@example.com", PASSWORD, None, ADDRESS)
    assert raised.value.status in (401, 429)


# --- recovery -------------------------------------------------------------------------------


async def test_forgot_password_mails_a_known_account_and_nobody_else() -> None:
    kit = make_auth()
    await _registered(kit)
    mail = await kit.service.forgot_password(EMAIL, ADDRESS)
    assert mail is not None and (mail.to, mail.subject) == (NORMAL_EMAIL, RESET_SUBJECT)
    assert await kit.service.forgot_password("nobody@example.com", ADDRESS) is None
    assert await kit.service.forgot_password("garbage", ADDRESS) is None


async def test_recovery_requests_are_throttled_like_sign_in() -> None:
    kit = make_auth()
    for _ in range(kit.settings.throttle.attempts):
        await kit.service.forgot_password("nobody@example.com", ADDRESS)
    with pytest.raises(Refusal) as raised:
        await kit.service.forgot_password("nobody@example.com", ADDRESS)
    assert raised.value.status == 429
    await _registered(kit, email="b@example.com")  # sign-in counters are separate
    await kit.service.sign_in("b@example.com", PASSWORD, None, ADDRESS)


async def test_reset_sets_the_password_ends_every_session_and_spends_the_token() -> None:
    kit = make_auth()
    await _registered(kit)
    session = (await _sign_in(kit)).session_token
    mail = await kit.service.forgot_password(NORMAL_EMAIL, ADDRESS)
    assert mail is not None
    token = token_in(mail.body)
    await kit.service.reset_password(token, "a brand new password")
    assert await kit.sessions.resolve(session) is None
    await _sign_in(kit, password="a brand new password")  # pragma: allowlist secret
    with pytest.raises(Refusal):
        await kit.service.sign_in(NORMAL_EMAIL, PASSWORD, None, "10.0.0.5")
    with pytest.raises(Refusal) as reused:
        await kit.service.reset_password(token, "yet another password")
    assert reused.value.status == 400


async def test_an_expired_reset_token_changes_nothing() -> None:
    kit = make_auth()
    await _registered(kit)
    mail = await kit.service.forgot_password(NORMAL_EMAIL, ADDRESS)
    assert mail is not None
    kit.clock.advance(kit.settings.reset_token_minutes * 60 + 1)
    with pytest.raises(Refusal):
        await kit.service.reset_password(token_in(mail.body), "a brand new password")
    await _sign_in(kit)


async def test_a_weak_new_password_is_refused_and_the_token_stays_usable() -> None:
    kit = make_auth()
    await _registered(kit)
    mail = await kit.service.forgot_password(NORMAL_EMAIL, ADDRESS)
    assert mail is not None
    token = token_in(mail.body)
    with pytest.raises(FieldRejected):
        await kit.service.reset_password(token, "short")
    await kit.service.reset_password(token, "a brand new password")


async def test_a_new_reset_link_supersedes_the_previous_one() -> None:
    kit = make_auth()
    await _registered(kit)
    first = await kit.service.forgot_password(NORMAL_EMAIL, ADDRESS)
    second = await kit.service.forgot_password(NORMAL_EMAIL, ADDRESS)
    assert first is not None and second is not None
    with pytest.raises(Refusal):
        await kit.service.reset_password(token_in(first.body), "a brand new password")
    await kit.service.reset_password(token_in(second.body), "a brand new password")


async def test_a_verification_token_cannot_reset_a_password() -> None:
    kit = make_auth()
    token = token_in((await kit.service.sign_up(NORMAL_EMAIL, PASSWORD)).body)
    with pytest.raises(Refusal):
        await kit.service.reset_password(token, "a brand new password")


# --- the signed-in account ------------------------------------------------------------------


async def test_changing_the_password_needs_the_current_one_and_ends_the_other_sessions() -> None:
    kit = make_auth()
    await _registered(kit)
    here, there = await _sign_in(kit), await _sign_in(kit)
    with pytest.raises(Refusal) as wrong:
        await kit.service.change_password(
            here.user,
            "wrong password!!",
            "a brand new password",
            here.session_token,
            ADDRESS,
        )
    assert wrong.value.status == 403
    await kit.service.change_password(
        here.user,
        PASSWORD,
        "a brand new password",
        here.session_token,
        ADDRESS,
    )
    kept = await kit.sessions.resolve(here.session_token)
    assert kept is not None and kept.id == here.user.id
    assert await kit.sessions.resolve(there.session_token) is None
    await _sign_in(kit, password="a brand new password")  # pragma: allowlist secret
    with pytest.raises(Refusal):
        await kit.service.sign_in(NORMAL_EMAIL, PASSWORD, None, "10.0.0.5")


async def test_a_bad_new_password_is_refused_before_anything_changes() -> None:
    kit = make_auth()
    await _registered(kit)
    here = await _sign_in(kit)
    with pytest.raises(FieldRejected):
        await kit.service.change_password(here.user, PASSWORD, "short", here.session_token, ADDRESS)
    await _sign_in(kit)


async def test_wrong_current_passwords_are_throttled() -> None:
    kit = make_auth()
    await _registered(kit)
    here = await _sign_in(kit)
    for _ in range(kit.settings.throttle.attempts):
        with pytest.raises(Refusal):
            await kit.service.change_password(
                here.user,
                "wrong password!!",
                "a brand new password",
                None,
                ADDRESS,
            )
    with pytest.raises(Refusal) as raised:
        await kit.service.change_password(
            here.user,
            PASSWORD,
            "a brand new password",
            None,
            ADDRESS,
        )
    assert raised.value.status == 429


async def test_sign_out_everywhere_ends_every_session() -> None:
    kit = make_auth()
    await _registered(kit)
    first, second = await _sign_in(kit), await _sign_in(kit)
    await kit.service.sign_out_everywhere(first.user)
    assert await kit.sessions.resolve(first.session_token) is None
    assert await kit.sessions.resolve(second.session_token) is None


async def test_deleting_the_account_needs_the_password_and_removes_everything() -> None:
    kit = make_auth()
    await _registered(kit)
    signed = await _sign_in(kit)
    key = ThreadKey(signed.user.id, "t1")
    await kit.threads.touch(key)
    with pytest.raises(Refusal) as wrong:
        await kit.service.delete_account(signed.user, "wrong password!!", ADDRESS)
    assert wrong.value.status == 403 and await kit.threads.holds(key)
    await kit.service.delete_account(signed.user, PASSWORD, ADDRESS)
    assert await kit.accounts.users.by_email(NORMAL_EMAIL) is None
    assert await kit.sessions.resolve(signed.session_token) is None
    assert not await kit.threads.holds(key)

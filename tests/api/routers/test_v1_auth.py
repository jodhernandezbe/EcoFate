"""The authentication routes end to end: enumeration, sign-in, cookies, tokens, throttling."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.messages import EXISTING_SUBJECT, RESET_SUBJECT, VERIFY_SUBJECT
from tests.api.auth_support import PASSWORD, fast_settings, token_in
from tests.api.conftest import ORIGIN, runtime_of
from tests.fakes_accounts import InMemorySessions, RecordingMailer

OWN = {"Origin": ORIGIN}
EMAIL = "ana@example.com"
AUTH = "/api/v1/auth"


def _post(client: TestClient, path: str, body: dict[str, Any], **headers: str) -> Any:
    return client.post(f"{AUTH}/{path}", json=body, headers={**OWN, **headers})


def _sign_up(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> Any:
    return _post(client, "signup", {"email": email, "password": password})


def _verify(client: TestClient, mailer: RecordingMailer) -> None:
    assert _post(client, "verify", {"token": token_in(mailer.sent[-1].body)}).status_code == 204


def _registered(client: TestClient, mailer: RecordingMailer, email: str = EMAIL) -> None:
    assert _sign_up(client, email).status_code == 202
    _verify(client, mailer)


def _signin(client: TestClient, email: str = EMAIL, password: str = PASSWORD, **h: str) -> Any:
    return _post(client, "signin", {"email": email, "password": password}, **h)


# --- 5.1 sign-up enumeration ----------------------------------------------------------------


def test_signing_up_answers_202_and_mails_a_verification_link(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    response = _sign_up(anonymous)
    assert (response.status_code, response.json()) == (202, {"status": "accepted"})
    assert [(m.to, m.subject) for m in mailer.sent] == [(EMAIL, VERIFY_SUBJECT)]


def test_signing_up_with_a_taken_email_looks_the_same_and_keeps_the_password(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    fresh = _sign_up(anonymous)
    _verify(anonymous, mailer)
    taken = _sign_up(anonymous, password="a completely different one")
    assert (taken.status_code, taken.json()) == (fresh.status_code, fresh.json())
    assert mailer.sent[-1].subject == EXISTING_SUBJECT and mailer.sent[-1].to == EMAIL
    assert _signin(anonymous).json()["state"] == "signed_in"  # the original password still works
    assert (
        _signin(
            anonymous,
            password="a completely different one",  # pragma: allowlist secret
        ).status_code  # pragma: allowlist secret
        == 401  # pragma: allowlist secret
    )  # pragma: allowlist secret


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": EMAIL, "password": "short"}, "password"),  # pragma: allowlist secret
        ({"email": "not an email", "password": PASSWORD}, "email"),
    ],
)
def test_signing_up_with_a_bad_field_is_422_naming_it_and_creates_nothing(
    anonymous: TestClient,
    mailer: RecordingMailer,
    body: dict[str, str],
    field: str,
) -> None:
    response = _post(anonymous, "signup", body)
    assert response.status_code == 422
    assert [f["loc"] for f in response.json()["fields"]] == [["body", field]]
    assert mailer.sent == []


def test_signing_up_when_closed_is_403(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    from dataclasses import replace

    runtime = runtime_of(app)
    closed = replace(runtime.settings, signup_open=False)
    object.__setattr__(runtime.service._p, "settings", closed)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    response = _sign_up(anonymous)
    assert response.status_code == 403 and mailer.sent == []


# --- 5.2 sign-in ----------------------------------------------------------------------------


def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    wrong = _signin(anonymous, password="wrong password!!")
    unknown = _signin(anonymous, "nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"] == unknown.json()["error"]
    assert set(wrong.json()) == set(unknown.json()) == {"error", "correlation_id"}


def test_the_right_password_on_an_unverified_account_gets_no_session(
    anonymous: TestClient,
    app: FastAPI,
) -> None:
    _sign_up(anonymous)
    response = _signin(anonymous)
    assert response.status_code == 200
    assert response.json() == {"state": "verification_required", "user": None}
    assert "set-cookie" not in response.headers
    assert cast(InMemorySessions, runtime_of(app).accounts.sessions).rows == {}


def test_a_successful_sign_in_sets_a_hardened_cookie_and_stores_only_a_hash(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    response = _signin(anonymous)
    body = response.json()
    assert body["state"] == "signed_in" and body["user"]["email"] == EMAIL
    assert set(body["user"]) == {"id", "email", "role", "verified"}
    cookie = response.headers["set-cookie"]
    assert cookie.lower().startswith("ecofate_session=")
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    assert "path=/" in cookie.lower()
    token = anonymous.cookies.get("ecofate_session")
    assert token is not None
    stored = cast(InMemorySessions, runtime_of(app).accounts.sessions).rows
    assert token not in stored and len(stored) == 1


def test_the_cookie_is_secure_when_the_setting_says_so(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    from dataclasses import replace

    runtime = runtime_of(app)
    secure = replace(runtime.settings, cookie_secure=True)
    object.__setattr__(runtime.sessions, "_settings", secure)
    _registered(anonymous, mailer)
    assert "secure" in _signin(anonymous).headers["set-cookie"].lower()


def test_a_stored_hash_is_not_accepted_as_a_cookie(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    _signin(anonymous)
    (stored_hash,) = cast(InMemorySessions, runtime_of(app).accounts.sessions).rows
    thief = TestClient(app, base_url=ORIGIN)
    thief.cookies.set("ecofate_session", stored_hash)
    assert thief.get(f"{AUTH}/me").status_code == 401


def test_signing_in_replaces_a_cookie_planted_before(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    _signin(anonymous)
    planted = anonymous.cookies.get("ecofate_session")
    assert planted is not None
    _signin(anonymous)  # the browser presented `planted`
    attacker = TestClient(app, base_url=ORIGIN)
    attacker.cookies.set("ecofate_session", planted)
    assert attacker.get(f"{AUTH}/me").status_code == 401
    assert anonymous.get(f"{AUTH}/me").status_code == 200


def test_signing_out_deletes_the_session_and_clears_the_cookie(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    _signin(anonymous)
    old = anonymous.cookies.get("ecofate_session")
    assert old is not None
    response = anonymous.post(f"{AUTH}/signout", headers=OWN)
    assert response.status_code == 204 and "ecofate_session=" in response.headers["set-cookie"]
    replay = TestClient(app, base_url=ORIGIN)
    replay.cookies.set("ecofate_session", old)
    assert replay.get(f"{AUTH}/me").status_code == 401


def test_an_expired_session_is_401(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
    clock: Any,
) -> None:
    _registered(anonymous, mailer)
    _signin(anonymous)
    clock.advance(fast_settings().session_idle_seconds + 1)
    assert anonymous.get(f"{AUTH}/me").status_code == 401


def test_me_describes_the_signed_in_user(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    _signin(anonymous)
    body = anonymous.get(f"{AUTH}/me").json()
    assert (body["email"], body["role"], body["verified"]) == (EMAIL, "user", True)


# --- 5.3 tokens -----------------------------------------------------------------------------


def test_a_verification_link_works_once_and_not_after_it_expired(
    anonymous: TestClient,
    mailer: RecordingMailer,
    clock: Any,
) -> None:
    _sign_up(anonymous)
    token = token_in(mailer.sent[-1].body)
    assert _post(anonymous, "verify", {"token": token}).status_code == 204
    assert _post(anonymous, "verify", {"token": token}).status_code == 400
    _post(anonymous, "resend", {"email": EMAIL})  # verified: nothing is mailed
    assert len(mailer.sent) == 1
    _sign_up(anonymous, "bo@example.com")
    stale = token_in(mailer.sent[-1].body)
    clock.advance(fast_settings().verification_token_hours * 3600 + 1)
    assert _post(anonymous, "verify", {"token": stale}).status_code == 400


def test_a_resent_link_supersedes_the_first(anonymous: TestClient, mailer: RecordingMailer) -> None:
    _sign_up(anonymous)
    first = token_in(mailer.sent[-1].body)
    assert _post(anonymous, "resend", {"email": EMAIL}).status_code == 202
    second = token_in(mailer.sent[-1].body)
    assert _post(anonymous, "verify", {"token": first}).status_code == 400
    assert _post(anonymous, "verify", {"token": second}).status_code == 204


def test_resend_and_forgot_answer_alike_for_known_unknown_and_garbage_emails(
    anonymous: TestClient,
    mailer: RecordingMailer,
    clock: Any,
) -> None:
    _registered(anonymous, mailer)
    for path in ("resend", "forgot"):
        answers = [
            _post(anonymous, path, {"email": email}, **{"X-Forwarded-For": str(i)})
            for i, email in enumerate((EMAIL, "nobody@example.com", "garbage"))
        ]
        assert {(r.status_code, r.text) for r in answers} == {(202, '{"status":"accepted"}')}
        clock.advance(fast_settings().throttle.window_seconds + 1)


def test_resetting_a_password_revokes_every_session_and_spends_the_link(
    app: FastAPI,
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    _signin(anonymous)
    other = TestClient(app, base_url=ORIGIN)
    _signin(other)
    assert _post(anonymous, "forgot", {"email": EMAIL}).status_code == 202
    mail = mailer.sent[-1]
    assert mail.subject == RESET_SUBJECT and "?" not in mail.body.split("\n\n")[1]
    token = token_in(mail.body)
    new = "a brand new password"
    assert _post(anonymous, "reset", {"token": token, "password": new}).status_code == 204
    assert anonymous.get(f"{AUTH}/me").status_code == 401
    assert other.get(f"{AUTH}/me").status_code == 401
    assert _post(anonymous, "reset", {"token": token, "password": new}).status_code == 400
    assert _signin(anonymous, password=new).json()["state"] == "signed_in"
    assert _signin(anonymous).status_code == 401


def test_an_expired_reset_link_changes_nothing(
    anonymous: TestClient,
    mailer: RecordingMailer,
    clock: Any,
) -> None:
    _registered(anonymous, mailer)
    _post(anonymous, "forgot", {"email": EMAIL})
    token = token_in(mailer.sent[-1].body)
    clock.advance(fast_settings().reset_token_minutes * 60 + 1)
    body = {"token": token, "password": "a brand new password"}  # pragma: allowlist secret
    assert _post(anonymous, "reset", body).status_code == 400
    assert _signin(anonymous).json()["state"] == "signed_in"


def test_a_token_in_the_query_string_is_not_how_the_api_takes_one(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _sign_up(anonymous)
    token = token_in(mailer.sent[-1].body)
    assert anonymous.post(f"{AUTH}/verify?token={token}", headers=OWN).status_code == 422


# --- 5.4 throttling -------------------------------------------------------------------------


def test_past_the_email_limit_the_right_password_gets_429_with_retry_after(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    _registered(anonymous, mailer)
    limit = fast_settings().throttle.attempts
    for index in range(limit):
        spoof = {"X-Forwarded-For": f"10.0.0.{index}"}
        assert (
            _signin(
                anonymous,
                password="wrong password!!",  # pragma: allowlist secret
                **spoof,  # pragma: allowlist secret
            ).status_code  # pragma: allowlist secret
            == 401  # pragma: allowlist secret
        )  # pragma: allowlist secret
    blocked = _signin(anonymous)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.json()["error"] and "state" not in blocked.json()


def test_past_the_address_limit_another_email_gets_429(anonymous: TestClient) -> None:
    for index in range(fast_settings().throttle.attempts):
        assert _signin(anonymous, f"u{index}@example.com").status_code == 401
    assert _signin(anonymous, "fresh@example.com").status_code == 429


def test_a_forged_forwarded_for_header_is_ignored_without_a_trusted_proxy(
    anonymous: TestClient,
) -> None:
    for index in range(fast_settings().throttle.attempts):
        _signin(anonymous, f"u{index}@example.com", **{"X-Forwarded-For": f"9.9.9.{index}"})
    forged = _signin(anonymous, "fresh@example.com", **{"X-Forwarded-For": "1.2.3.4"})
    assert forged.status_code == 429  # still the socket address, whatever the header says


def test_with_a_trusted_proxy_the_address_it_vouches_for_is_counted(
    app: FastAPI,
    anonymous: TestClient,
) -> None:
    from dataclasses import replace

    runtime = runtime_of(app)
    object.__setattr__(runtime, "settings", replace(runtime.settings, trusted_proxy_hops=1))
    limit = fast_settings().throttle.attempts
    for index in range(limit):
        _signin(anonymous, f"u{index}@example.com", **{"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
    same = _signin(anonymous, "x@example.com", **{"X-Forwarded-For": "7.7.7.7, 203.0.113.9"})
    other = _signin(anonymous, "x@example.com", **{"X-Forwarded-For": "7.7.7.7, 203.0.113.10"})
    assert (same.status_code, other.status_code) == (429, 401)


def test_recovery_requests_are_throttled(anonymous: TestClient) -> None:
    for _ in range(fast_settings().throttle.attempts):
        assert _post(anonymous, "forgot", {"email": "nobody@example.com"}).status_code == 202
    blocked = _post(anonymous, "forgot", {"email": "nobody@example.com"})
    assert blocked.status_code == 429 and "retry-after" in blocked.headers


def test_a_foreign_origin_is_refused_on_the_public_routes(anonymous: TestClient) -> None:
    response = anonymous.post(
        f"{AUTH}/signin",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403

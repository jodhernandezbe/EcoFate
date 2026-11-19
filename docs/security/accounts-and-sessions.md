[← Documentation index](../../README.md#documentation) · [Security](README.md)

# Accounts and sessions

- Sign-up with an email and a password of 12 to 128 characters (no composition rules); the address
  is verified with a single-use link (valid 24 hours). "Forgot password" sends a single-use reset
  link (valid 30 minutes). Limits are in `[auth]` of `config/settings.toml`.
- Passwords are stored as **Argon2id** hashes (`[auth.argon2]`: time cost 3, 64 MiB, parallelism 4).
- A session is a random token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` over HTTPS; loading
  the settings refuses `cookie_secure = false` when `[telemetry].environment` is `production`). The
  server keeps only a keyed hash of it (keyed with `ECOFATE_SESSION_SECRET`, at least 32
  characters; the program refuses to start without it), with an idle expiry (720 minutes) and an
  absolute one (14 days). Signing out, changing or resetting the password ends sessions.
- Wrong passwords and recovery requests are throttled per account and per client address (5
  attempts in 15 minutes, `[auth.throttle]`); answers never reveal whether an email has an
  account, and an unknown email still pays for one password verification. Emailed links carry the
  token in the URL fragment, and no route takes a token in a query string.
- State-changing requests must carry the API's own `Origin` (or `Referer`)
  (`api/core/origin_guard.py`); CORS allows only the own origin.
- The account menu offers change password, sign out everywhere and delete the account (which
  deletes its threads). `[auth].signup_open = false` closes sign-up.
- Only administrators see Monitoring; everyone else gets the 404 of an unknown page. An
  administrator is made only from a terminal with `python -m api create-admin` (the password is
  typed at a hidden prompt or piped with `--password-stdin`, never an argument).
- Behind Cloudflare, `[auth].trusted_proxy_hops = 1` (production overlay) makes the throttle use
  the visitor's address; [deployment](../deployment/teardown-and-security.md#security-notes) explains how it was verified.

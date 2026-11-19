[← Documentation index](../../README.md#documentation) · [API](../README.md)

# Accounts and email

## Accounts

The web interface needs an account. People sign up with an email and password (at least 12 characters), verify the address with a single-use link, and sign in; "Forgot password" sends a single-use reset link. Passwords are stored as Argon2id hashes. A session is a random token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` over HTTPS), kept on the server only as a keyed hash, with an idle and an absolute expiry; signing out, changing or resetting the password ends sessions. Wrong passwords and recovery requests are throttled per account and per client address (`[auth.throttle]`), and answers never reveal whether an email has an account. Each user sees only their own threads, reports and usage; another user's thread id answers 404, exactly like an id that does not exist. Account menu: change password, sign out everywhere, delete the account (deletes its threads too). Close sign-up with `[auth].signup_open = false`. The command line program (`python -m app`) needs no account.

Set `ECOFATE_SESSION_SECRET` in `.env` (a random string of at least 32 characters; the web program refuses to start without it). The first administrator is created, or an existing account promoted, from a terminal:

    uv run python -m api create-admin --email you@example.com      # asks for the password, hidden
    docker compose exec api python -m api create-admin --email you@example.com

The password is only ever typed at the prompt (or piped with `--password-stdin` for scripted deploys), never an argument. Only administrators see **Monitoring**; everyone else gets the 404 of an unknown page. Emails go to the SMTP server set in `.env` (see [Email: development and production](#email-development-and-production)). Upgrading from a version without accounts deletes the old local threads, which had no owner. <!-- pragma: allowlist secret -->

## Email: development and production

The SMTP server is configured only in `.env`, with six variables (the web program refuses to start without the first four, and names the one that is missing or wrong): `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_FROM`, `SMTP_USERNAME` and `SMTP_PASSWORD`. `SMTP_SECURITY` is `starttls` (port 587), `tls` (implicit TLS, port 465) or `none`. <!-- pragma: allowlist secret -->

| | Development (your machine) | Production (a deployed server) |
|---|---|---|
| Where mail goes | Mailpit, a mail catcher: nothing reaches a real inbox; read it at http://127.0.0.1:8025 | Your provider, to the real recipient |
| Start | `docker compose --profile dev up` (the `dev` profile adds Mailpit) | `docker compose up` (no Mailpit) |
| `SMTP_HOST` / `SMTP_PORT` | `127.0.0.1` / `1025` (in Docker a loopback host means the `mailpit` service, so the same `.env` works natively) | The provider's, e.g. `smtp.mx.cloudflare.net` / `465` |
| `SMTP_SECURITY` | `none` | `tls` or `starttls`, never `none` (a login over an unencrypted connection is refused) |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | empty | The provider's login and secret, e.g. `api_token` / a Cloudflare API token with *Email Sending: Edit* |
| `SMTP_FROM` | any address, e.g. `EcoFate <no-reply@ecofate.local>` | An address on a domain the provider verified, e.g. `EcoFate <no-reply@yourdomain.com>` |

`.env.example` ships the development values and shows the production ones for Cloudflare Email Service and for any provider on port 587 (Amazon SES, Resend, Gmail with an app password). For Cloudflare: put the domain on Cloudflare DNS, onboard it under Email → Email Service → Email Sending (Cloudflare adds the SPF and DKIM records), create an API token with *Email Sending: Edit*, and fill in the values above; while sending is in beta, check whether your plan lets you send to any address or only to verified ones.

A production deployment also changes these settings in `config/settings.toml`, which the program checks at start-up:

- `[telemetry].environment = "production"`: turns on the production checks below.
- `[auth].cookie_secure = true`: the session cookie is sent over HTTPS only (refused as `false` in production).
- `[mail].app_base_url = "https://your.domain"`: the address the emailed links open (must be `https` in production).
- `[auth].signup_open`: `true` lets anyone create an account; set `false` to close sign-up.

In both, `ECOFATE_SESSION_SECRET` must be set in `.env`. Use a different secret in production from the one on your machine.

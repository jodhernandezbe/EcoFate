[← Documentation index](../README.md#documentation) · [Architecture](../docs/architecture.md) · [Security](../docs/security/README.md)

# config/

Everything that is configuration rather than logic: URLs and endpoints, timings, data paths,
column names, units, model names, thresholds, limits and the fixed text the interface shows. It
lives in `config/settings.toml`; typed loaders read it. Nothing of this is hard-coded in Python.
`config/` imports nothing from the rest of the project.

## Contents

- [How it is organised](#how-it-is-organised)
- [Production overlay](#production-overlay)
- [Settings and secrets](#settings-and-secrets)
- [Adding a setting](#adding-a-setting)
- [Testing](#testing)

## How it is organised

- `settings.toml`: one file, one table per concern (for example `[comptox]`, `[tri]`, `[stack]`,
  `[meteorology]`, `[population]`, `[exposure]`, `[assessment]`, `[read_across]`, `[agent]`,
  `[database]`, `[worker]`, `[byok]`, `[limits]`, `[auth]`, `[mail]`, `[telemetry]`, `[evaluation]`,
  `[ui]`). Comments in the file say what each value means and where it came from.
- One typed loader module per concern, each returning frozen dataclasses (`agent.py`, `auth.py`,
  `database.py`, `worker.py`, `stack.py`, `retrieval.py`, `exposure.py`, `ui.py`,
  `telemetry.py`, `evaluation.py`, ...). `loader.py` holds the original chemical-property and
  toxicity loaders.
- `parsing.py`: the shared validators (`require_str`, `require_int`, `require_number`,
  `require_bool`, `section`, ...). Each raises `ValueError` naming the offending key, so a
  configuration error surfaces at load time and is never coerced.
- Loaders are cached (`lru_cache`), return copies of config-backed data and fail closed: a missing
  or malformed value stops the program with a message that names it.

## Production overlay

`config/settings.production.toml` is laid over `settings.toml` when the environment variable
`ECOFATE_SETTINGS_PROFILE=production` is set (the production compose file sets it). Only keys that
already exist in `settings.toml` may appear in it, and nothing secret. It currently sets the public
origin and email link base (`https://ecofate.org`), the secure cookie, `trusted_proxy_hops = 1`, the
production telemetry environment and the worker concurrency. See
[deployment](../docs/deployment/README.md).

## Settings and secrets

Settings name an environment variable where a secret is needed; the secret itself never appears in
the file. Examples: `[comptox].api_key_env_var` (`COMPTOX_API_KEY`), `[population].api_key_env_var`
(`CENSUS_API_KEY`), `[database].url_env_var` (`DATABASE_URL`), `[worker].redis_url_env_var`
(`REDIS_URL`), `[byok].kek_env_var` (`ECOFATE_KEY_ENCRYPTION_KEY`), `[auth].session_secret_env_var`
(`ECOFATE_SESSION_SECRET`), the `[mail]` variables (`SMTP_*`) and the `[telemetry]` tokens
(`LOGFIRE_TOKEN`, `LOGFIRE_READ_TOKEN`). The user's OpenAI key is not a setting: it is stored per
account ([security](../docs/security/README.md)).

## Adding a setting

1. Add the key to the right table of `settings.toml` with a comment saying what it means.
2. Read it in that concern's loader module with the `parsing.py` validators (a new concern gets its
   own module and `get_*_settings` function).
3. Pass the typed value to the code that needs it; do not read the file from the caller.
4. Add a test in `tests/config/` and a negative test for a bad value.

A new CompTox property or a new unit alias is only an entry in `settings.toml`.

## Testing

    uv run pytest tests/config

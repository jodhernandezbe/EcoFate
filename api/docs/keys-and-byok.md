[← Documentation index](../../README.md#documentation) · [API](../README.md)

# Keys and BYOK

The web program is bring-your-own-key: every user pays for their own model calls with their own OpenAI key, and the operator provides the data services.

- **Your OpenAI key** (required, it runs the assistant): click the gear (top right) and save it. It is stored in the database encrypted with AES-256-GCM, a fresh random nonce each time and your account and the key's purpose as associated data, so a copy of your row in another account does not decrypt. Settings only ever says whether a key is stored ("Key stored encrypted for your account"); no endpoint returns any part of it. It is decrypted once per turn, in the process that runs the turn, given to the model and tools for that turn only, and dropped when the turn ends. "Clear key" deletes it, and so does deleting your account.
- **Operator keys** (`CENSUS_API_KEY`, `COMPTOX_API_KEY`, `LOGFIRE_TOKEN`, `LOGFIRE_READ_TOKEN`): set by whoever runs the installation, in `.env` or the server environment. Users never type, see or receive them. Settings lists each data service as "Provided by this installation" or "Not available on this installation" (and what is missing without it).
- **Command line** (`python -m app`, the evaluations): unchanged. They keep using the OS keychain, with the environment variables as the fallback, for all three keys.

**The key-encryption key (KEK).** Required: the web program refuses to start without `ECOFATE_KEY_ENCRYPTION_KEY` (the variable name is `[byok].kek_env_var`), naming it in the message. Generate one (32 random bytes, base64url) and put it in `.env` or your secret store; never in the database, the image or the repository:

    python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

**Rotating the KEK** (no downtime, no user action):

1. Generate a new key. Set it as `ECOFATE_KEY_ENCRYPTION_KEY` and move the old value to `ECOFATE_KEY_ENCRYPTION_KEY_PREVIOUS`. Restart: every key still works (a key sealed with the previous KEK is re-sealed under the new one the first time it is read).
2. Run `uv run python -m api rotate-keys` (in Docker: `docker compose exec api python -m api rotate-keys`). It re-seals every stored key and prints counts only (re-sealed, already current, unreadable); it exits with an error when some row is unreadable.
3. Remove `ECOFATE_KEY_ENCRYPTION_KEY_PREVIOUS` and restart.

**If the KEK is lost**, every stored key becomes unreadable: the program treats those users as having no key (they see "No key configured" and the assistant asks them to add one) and nothing is guessed or deleted. Users save their key again; a key is replaceable by its owner, so nothing else is lost. Back the KEK up with the same care as the database password.

The server listens on loopback only (`[ui]` in `config/settings.toml`).

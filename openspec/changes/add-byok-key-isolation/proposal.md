## Why

Today every key lives in the OS keychain of the machine running the server
(`app/key_vault.py`), one entry per key, shared by whoever uses the page. In a container there
is no keychain, and on a shared deployment one keychain entry would make every user spend the
same person's OpenAI credits. The deployed service works under bring-your-own-key (BYOK):
each user pays for their own model calls with their own OpenAI key, while the data-service
keys (CompTox, Census) and the monitoring tokens (Logfire) belong to the operator and must
never be typed into, shown by, or echoed from the interface. Keys must stay isolated per
user, encrypted at rest, and out of every log, span, error and queued task. This is roadmap
step 5; it needs the accounts of step 4.

## What Changes

- **Per-user OpenAI key**: the only key the interface accepts. Stored in Postgres encrypted
  with AES-256-GCM (`cryptography`), a fresh 96-bit nonce per encryption, the user id and the
  key's purpose as associated data (a ciphertext copied to another user's row does not
  decrypt), under a key-encryption key (KEK) from `ECOFATE_KEY_ENCRYPTION_KEY`. Status says
  only whether a key is set. Decrypted once per turn in the process that runs the turn, held
  in the existing context-local holder, dropped when the turn ends.
- **Operator service keys**: `COMPTOX_API_KEY`, `CENSUS_API_KEY`, `LOGFIRE_TOKEN`,
  `LOGFIRE_READ_TOKEN` are read from the server environment only. The Census and CompTox
  routes (`/api/v1/settings/census-key`, `/comptox-key`) are **removed**; the combined status
  reports only whether each data service is available on this installation.
- **KEK rotation**: each ciphertext records the id (fingerprint) of the KEK that sealed it; a
  previous KEK may be supplied in `ECOFATE_KEY_ENCRYPTION_KEY_PREVIOUS` during a rotation, and
  `uv run python -m api rotate-keys` re-encrypts every stored key under the current KEK.
- **Deletion**: clearing the key deletes its row; deleting the account deletes it too.
- **Per-turn decrypt function**: `UserKeyVault.read(user_id) -> SecretStr | None` is the one
  way to obtain a user's key; the API runner uses it now and the Celery worker of step 7
  calls it at task start (its task payload carries the turn id only).
- **Redaction extended** (`commons/key_patterns.py`, used by logs and spans): cookie headers,
  `token=` in URL fragments (reset and verification links), and the exact values of the KEK,
  the session secret, the SMTP password and the operator keys protected for the life of the
  process. Database URL passwords and bound SQL parameters are already masked by
  `migrate-to-postgresql`. Every pattern has a negative test.
- **Queued work carries ids only**: any message handed to another process (the Celery tasks of
  step 7) holds user, thread and turn ids, never a key, token or password; a guard rejects a
  payload containing a protected value or a key-shaped string.
- **Settings drawer**: one Assistant section for the OpenAI key; the Data services section
  becomes read-only availability ("Provided by this installation" / "Not available on this
  installation"), with no input.
- **Command line unchanged in spirit**: `python -m app` and the evaluations keep using the OS
  keychain with the environment as fallback, for all three keys.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `api-key-vault`: from three keychain entries for one local user to one encrypted OpenAI key
  per user plus operator environment keys; extended redaction; KEK rotation; no keys in queued
  work.
- `web-ui-shell`: the Settings drawer accepts only the OpenAI key.
- `agent-telemetry`: the no-secrets rule covers the new secrets.

## Impact

- New: `commons/sealed_secret.py` (AES-GCM seal/open, key passed in, no I/O),
  `storage/` table `user_credentials(user_id, purpose, nonce, ciphertext, kek_id, updated_at)`
  + repository + migration, `app/user_key_vault.py` (per-user vault: KEK from the variable
  named in `[byok]`, used by the API now and the worker in step 7), `config/byok.py` and
  `[byok]` in `config/settings.toml`, `api/__main__.py rotate-keys`.
- Changed: `api/routers/v1_settings.py` (OpenAI routes scoped to the user, Census/CompTox
  routes removed, combined status), `api/services/agent_runner.py` (per-user key + operator
  keys), `app/redaction.py`, `commons/key_patterns.py`, `app/telemetry.py` scrubbing,
  `api/schemas/settings.py` + regenerated frontend types, `frontend/src/features/settings/`,
  `hooks/useKeyStatus.ts`, `.env.example`.
- Dependency: `cryptography` (already a transitive dependency; made direct).
- Dependency direction: `app -> storage` widens from the checkpointer to the user key vault
  (ROADMAP "Code layout").
- Breaking: Census and CompTox keys saved in the keychain are no longer used by the web
  program; the operator sets them in the environment.

## Context

See proposal.md and `openspec/ROADMAP.md` ("BYOK and credentials"). Code this changes:

- `app/key_vault.py`: `KeyVault` per key over `keyring`, `ServiceKeys` bundle with
  `vault(name)` and `statuses()`; the program falls back to each key's environment variable.
- `api/routers/v1_settings.py`: generated GET/POST/DELETE routes for `openai-key`,
  `census-key`, `comptox-key` and a combined `/keys` status.
- `tools/credentials.py`: `PROVIDER_KEY`, `CENSUS_KEY`, `COMPTOX_KEY` as
  `commons.scoped_secret.ScopedSecret` (ContextVar) holders; tools fall back to their
  configured environment variable when nothing is provided.
- `app/redaction.py` (moved from `api/core/logging_filter.py` by `extract-turn-runner`): `redact()` applies `commons.key_patterns` and the exact values
  registered with `protect_secrets(values)` (reference-counted, per turn).
- `app/telemetry.py` scrubs spans with the same patterns.
- After step 4 every request has an authenticated `user_id`; after step 2 there is a
  Postgres `storage/` layer.

## Goals / Non-Goals

**Goals:**
- A user's OpenAI key is usable only for that user's turns, unreadable from a database dump
  without the KEK, and never returned in any form.
- Operator keys never cross the HTTP boundary in either direction.
- One redaction routine covers logs, spans, error bodies and queued payloads, with a negative
  test per pattern.
- The KEK can be rotated without downtime or user action.

**Non-Goals:**
- A cloud KMS (AWS KMS envelope encryption) — the KEK comes from SSM Parameter Store into the
  environment in step 9; KMS is a possible follow-up behind the same interface.
- Per-user keys for other providers (Anthropic, Vertex); the storage has a `purpose` column so
  they can be added.
- Validating a key against OpenAI when it is saved (unchanged: never call the provider to
  validate).

## Decisions

1. **AES-256-GCM with associated data.** `seal(kek, plaintext, aad) -> (nonce, ciphertext)`
   and `open_(kek, nonce, ciphertext, aad)` in `commons/sealed_secret.py`, using
   `cryptography.hazmat.primitives.ciphers.aead.AESGCM`; nonce `os.urandom(12)` per seal;
   `aad = f"ecofate:{purpose}:{user_id}".encode()`. Binding the user id means a row swapped
   between users (SQL injection elsewhere, a bad migration) fails authentication instead of
   decrypting under the wrong account. *Alternatives*: Fernet (AES-CBC+HMAC, no AAD) —
   rejected for lacking AAD; pgcrypto in SQL — rejected because the KEK would travel in SQL
   statements and could land in Postgres logs.
2. **KEK format and loading.** 32 random bytes, base64url, in the variable named by
   `[byok].kek_env_var` (`ECOFATE_KEY_ENCRYPTION_KEY`). Loaded once at start-up by
   `app/user_key_vault.py`; a missing, non-base64 or wrong-length value stops the web program
   with a message naming the variable (never its value). `kek_id` = first 16 hex chars of
   SHA-256 of the KEK, stored on each row, so the vault knows which KEK opened it. The KEK
   value is registered as a protected literal for the life of the process.
3. **Rotation.** During a rotation the operator sets the new KEK as current and the old one
   in `[byok].previous_kek_env_var` (`ECOFATE_KEY_ENCRYPTION_KEY_PREVIOUS`). Reads use
   whichever KEK matches the row's `kek_id`; writes always use the current one; a read with
   the previous KEK re-seals the row lazily. `rotate-keys` re-seals every remaining row in
   batches and reports counts only; afterwards the previous variable is removed. A row whose
   `kek_id` matches neither is reported as unreadable (the user sees "No key configured" and
   must save it again), never guessed. This adds one variable beyond the ROADMAP list.
4. **Status, save, clear.** `GET/POST/DELETE /api/v1/settings/openai-key` act on the
   signed-in user's row only. Validation is unchanged (non-blank, no whitespace or control
   characters, max length). Status is `{"configured": bool}`. `/keys` returns
   `{"openai": {"configured"}, "services": {"census": {"available"}, "comptox":
   {"available"}}}` where `available` means the operator variable is set and non-empty.
5. **Per-turn use.** `UserKeyVault.read(user_id)` (async, like the rest of `storage/`) is
   the single per-turn entry point; the background worker of step 7 calls the same function
   from the turn id it receives. At turn start the runner calls it once,
   wraps the plaintext in `SecretStr`, gives it to `build_chat_model(..., api_key=...)` and to
   `PROVIDER_KEY.provide(...)`, and registers it with `protect_secrets` for the turn. Census
   and CompTox values come from the operator environment through `OperatorKeys` and are given
   to `CENSUS_KEY` / `COMPTOX_KEY` per turn as today, so tools are unchanged. No key is ever
   set into `os.environ`.
6. **Redaction additions** in `commons/key_patterns.py`, each with a positive and a negative
   test: `COOKIE_PATTERN` (`Cookie:` / `Set-Cookie:` header values, i.e. session tokens) and
   `FRAGMENT_TOKEN_PATTERN` (`#token=...`, i.e. reset and verification tokens). Database URL
   passwords and SQL parameters are already handled by `migrate-to-postgresql`
   (URL masking, SQLAlchemy `hide_parameters`); this change only checks them in its leak
   tests. Process-lifetime literals: KEK (current and previous), session secret,
   SMTP password, operator keys, Logfire tokens — registered once at start-up through a new
   `protect_for_process(values)` beside the per-turn `protect_secrets`.
7. **Queued payload guard.** `commons/payload_guard.py`: `assert_ids_only(payload)` walks a
   JSON-able payload and raises if any string matches a key pattern or a protected literal,
   or any key name is in a deny list (`api_key`, `password`, `token`, `secret`, `cookie`).
   Step 7 calls it before every Celery `apply_async`; this change adds it and its tests so the
   rule exists before the worker does.
8. **Keychain for the CLI only.** `app/key_vault.py` keeps working for `python -m app` and
   `evals`; `api` no longer imports `ServiceKeys`. `api/core/security_keyring.py` is deleted.

## Risks / Trade-offs

Threat model (assets: users' OpenAI keys, operator keys, the KEK):

- **Database dump or backup leak** (the nightly `pg_dump` to S3 in step 9) → ciphertext only;
  the KEK is not in the database or the dump. Residual: an attacker with both the dump and
  the server environment can decrypt; mitigated by SSM access control in step 9.
- **Cross-user key use** (IDOR, row swap) → repository requires `user_id`; AAD binds the
  ciphertext to the user; test swaps two rows and expects a decryption failure.
- **Key echoed by the provider** in an error (`sk-proj-****abcd`) → existing masked-key
  pattern; provider text is never shown (`provider_errors.py`).
- **Key in a traceback or span** → per-turn literal protection plus patterns; spans scrubbed.
- **Key in a queued task** (Redis persists messages) → payload guard; worker loads by id.
- **KEK loss** → every stored key becomes unreadable; users re-enter their key (a key is
  replaceable by its owner, so this is recoverable, unlike data). Documented in the README.
- **Memory disclosure** → Python cannot zero strings; the plaintext lives only for the turn
  inside `SecretStr` and a ContextVar; accepted.
- **Trade-off**: the KEK in an environment variable is visible to anyone with shell access on
  the VM; acceptable for a single-tenant VM, KMS is the follow-up.

## Migration Plan

1. Migration adds `user_credentials`. No automatic import from the keychain (the keychain
   belongs to the operator's laptop, not to an account).
2. Operator generates a KEK (`python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`),
   sets it and the service keys in `.env` / SSM.
3. Users save their OpenAI key once in Settings after signing in.
4. Rollback: the previous image ignores `user_credentials`; the down migration drops it.

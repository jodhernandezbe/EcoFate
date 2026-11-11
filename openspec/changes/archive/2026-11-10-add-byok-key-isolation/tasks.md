## 1. Settings and primitives

- [x] 1.1 Add `[byok]` to `config/settings.toml` (kek_env_var, previous_kek_env_var, rotation batch size, the operator key variable names for Census and CompTox if not already named elsewhere) with comments, and `config/byok.py`; negative tests (empty names, non-positive batch).
- [x] 1.2 `commons/sealed_secret.py`: `seal(kek, plaintext, aad)`, `open_(kek, nonce, ciphertext, aad)`, `kek_id(kek)`, `parse_kek(text)` (base64url, exactly 32 bytes). Tests: round trip; wrong AAD, wrong KEK, flipped ciphertext bit all fail; two seals differ; malformed KEK rejected with a message that does not contain the value.
- [x] 1.3 `commons/key_patterns.py`: `COOKIE_PATTERN` and `FRAGMENT_TOKEN_PATTERN` added to `KEY_PATTERNS` (database URL masking already exists from `migrate-to-postgresql`; do not duplicate it); positive and negative test for each (fragment without `token=` untouched, `cookie` in prose untouched).
- [x] 1.4 `app/redaction.py` (moved there by `extract-turn-runner`): apply the new patterns; `protect_for_process(values)` for process-lifetime literals; tests for each.
- [x] 1.5 `commons/payload_guard.py`: `assert_ids_only(payload, protected)`; tests: a key, a protected literal, a `password` field, nested values are refused; ids-only payload passes.

## 2. Storage and vault

- [x] 2.1 `storage/`: `user_credentials` model (user_id FK cascade, purpose, nonce, ciphertext, kek_id, updated_at; unique `(user_id, purpose)`), repository taking `user_id` on every method, Alembic migration up/down.
- [x] 2.2 `app/user_key_vault.py`: `UserKeyVault` (async, over the async `storage/` session; load current/previous KEK once, register them for process-lifetime redaction; `status`, `save`, `clear`, and `read(user_id)` returning `SecretStr | None` — the single per-turn decrypt function the API runner uses now and the worker of `add-background-agent-worker` calls at task start; lazy re-seal with the current KEK; unreadable rows treated as absent with a warning log that names only the user id).
- [x] 2.3 `OperatorKeys` reading the Census/CompTox variables once at start-up, registered for process-lifetime redaction; `available()` booleans.
- [x] 2.4 `api/__main__.py rotate-keys`: batches, prints counts (re-sealed, already current, unreadable) only.
- [x] 2.5 Start-up check: the web program exits with a message naming the KEK variable when it is missing or malformed.

## 3. API and runner

- [x] 3.1 `api/routers/v1_settings.py`: OpenAI GET/POST/DELETE on the signed-in user's row; remove the Census and CompTox routes; `/keys` returns the OpenAI status and service availability; update `api/schemas/settings.py`; regenerate the contract and frontend types.
- [x] 3.2 `api/services/agent_runner.py`: decrypt the user's key once per turn, provide it to the chat model and `PROVIDER_KEY`, provide the operator keys to `CENSUS_KEY`/`COMPTOX_KEY`, protect all of them for the turn; delete `api/core/security_keyring.py` and stop importing `ServiceKeys` in `api/`.
- [x] 3.3 Account deletion removes `user_credentials` rows in the same transaction (with step 4's delete-account service).
- [x] 3.4 `app/telemetry.py`: span scrubbing uses the extended patterns and protected values.
- [x] 3.5 Container mode (from the archived `add-docker-compose-stack`): `create_app(keys_from_environment=True)` keeps reading only the operator keys (Census, CompTox) from the environment through `EnvironmentVault`; the OpenAI key always comes from the user's encrypted row, never `OPENAI_API_KEY`. Update `tests/api/test_container_keys.py` accordingly (environment OpenAI key ignored, operator keys still read) and the README's Docker section (only the operator keys go in `.env`).

## 4. Frontend

- [x] 4.1 `features/settings/SettingsDrawer.tsx`: Assistant section only for the OpenAI key with the new status text; Data services section read-only availability; `hooks/useKeyStatus.ts` for the new `/keys` shape. Follow `frontend/DESIGN.md` with the `ui-craft` skill; `/ui-check` light and dark.
- [x] 4.2 Vitest: no Census/CompTox inputs rendered; availability texts; no key in storage after save.

## 5. Tests (one negative test per rule)

- [x] 5.1 Isolation: user B's status is false while only A has a key; A's ciphertext copied into B's row fails to decrypt and B's turn ends with the missing-key message; repository methods require `user_id`.
- [x] 5.2 Concurrent turns of two users with fake keys: each fake chat model and each tool holder sees only its user's key.
- [x] 5.3 No leak: every GET endpoint with keys set returns no key character; `POST /census-key` and `/comptox-key` → 404; error responses for a provider failure carry no key.
- [x] 5.4 Logs and spans: user key, operator keys, KEK, session secret, SMTP password and a `postgresql://user:pass@` URL absent from emitted log text and recorded spans (in-memory exporter). <!-- pragma: allowlist secret -->
- [x] 5.5 Rotation: rows under the previous KEK readable and re-sealed on read; command re-seals all; row under an unknown KEK counted unreadable and status false.
- [x] 5.6 Start-up: missing and malformed KEK each stop the program; the message names the variable and not the value.
- [x] 5.7 `os.environ` never contains the user's key after a turn.

## 6. Documentation

- [x] 6.1 README: BYOK (users give only their OpenAI key; it is encrypted per account; operator keys in the environment), generating the KEK, rotation procedure, what happens if the KEK is lost; `.env.example` gains `ECOFATE_KEY_ENCRYPTION_KEY` (placeholder) and `ECOFATE_KEY_ENCRYPTION_KEY_PREVIOUS` (commented).
- [x] 6.2 `api/CLAUDE.md` and `app/CLAUDE.md`: keychain for the CLI only, `UserKeyVault` the only module that decrypts user keys, payload guard rule; root `CLAUDE.md` dependency line `app -> storage`; `commons/CLAUDE.md` if new modules need mention; note the extra `_PREVIOUS` variable in `openspec/ROADMAP.md`.

## 7. Verification

- [x] 7.1 `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, `uv run bandit -c pyproject.toml -r agent app api commons config evals models prompts tools`, function-length check, `npm --prefix frontend run check`, `uv run pre-commit run --all-files` (twice); `uv run detect-secrets scan` shows no new findings.
- [x] 7.2 Run `/security-audit` on the change and resolve every confirmed finding.
- [x] 7.3 Live check with `docker compose up`: two accounts save different real or test OpenAI keys; `psql` shows only ciphertext; one turn each succeeds under its own key; `docker compose logs api db` and the Logfire trace contain neither key, the KEK nor the database password; rotate the KEK and confirm both users can still chat.

[← Documentation index](../../README.md#documentation) · [Security](README.md)

# Keys

## Bring your own key

The web program is bring-your-own-key: every user pays for their model calls with their own OpenAI
key, and the operator provides the data services.

- **The user's OpenAI key** (required, it runs the assistant) is saved in Settings. The container
  never reads `OPENAI_API_KEY`. Settings only says whether a key is stored; no endpoint returns any
  part of it. It is decrypted once per turn, in the process that runs the turn (the worker),
  handed to the model and tools for that turn only, and dropped when the turn ends. "Clear key"
  deletes it, and so does deleting the account.
- **Operator keys** (`CENSUS_API_KEY`, `COMPTOX_API_KEY`, `LOGFIRE_TOKEN`, `LOGFIRE_READ_TOKEN`)
  are set by whoever runs the installation, in `.env` or the server environment. Users never type,
  see or receive them; Settings lists each data service as provided or not available.
- **Command line** (`python -m app`, the evaluations): keys come from the OS keychain
  (`app/key_vault.py`), with environment variables as the fallback. The web program uses neither.

Details of the endpoints and settings screen: [api](../../api/docs/keys-and-byok.md).

## Key storage and rotation

- A user's key is stored in `user_credentials` sealed with **AES-256-GCM**: a fresh random nonce
  each time, and the account and the key's purpose as associated data, so a copy of one user's row
  in another account does not decrypt. Only the nonce, the ciphertext and the id of the
  key-encryption key (KEK) are stored. `app/user_key_vault.py` is the only module that decrypts it,
  through `commons/sealed_secret.py`.
- The KEK (`ECOFATE_KEY_ENCRYPTION_KEY`, 32 random bytes, base64url) is required: the web program
  refuses to start without it, naming the variable. It lives in the environment or a secret store,
  never in the database, an image or the repository.
- **Rotating** needs no downtime: set the new key as `ECOFATE_KEY_ENCRYPTION_KEY` and move the old
  one to `ECOFATE_KEY_ENCRYPTION_KEY_PREVIOUS`; a key sealed with the previous KEK is re-sealed
  when first read. Then run `uv run python -m api rotate-keys` (in Docker:
  `docker compose exec api python -m api rotate-keys`), which re-seals the rest and prints counts
  only, and finally remove the `_PREVIOUS` variable.
- **If the KEK is lost**, every stored key becomes unreadable: those users are treated as having
  no key and add it again; nothing is guessed or deleted. Back the KEK up like the database
  password.

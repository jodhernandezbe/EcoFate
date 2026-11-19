[← Documentation index](../../README.md#documentation) · [Security](README.md)

# Redaction and the threat model

## Redaction and logs

- Logs go through one filter (`app/redaction.py`) that hides key-shaped strings
  (`commons/key_patterns.py`: `sk-` keys, bearer tokens, key-like assignments, query keys,
  PostgreSQL URL passwords, cookie values, fragment tokens) and the exact secret values the
  process holds.
- Spans sent to Logfire are scrubbed with the same patterns ([monitoring](../monitoring.md#redaction)).
- Responses, events and logs never contain exception text, request headers or key material; errors
  are fixed messages and database errors are logged by class only. Emails are sent after the
  response and log only the exception class.

## Threat model summary

Assets: users' OpenAI keys, the operator's keys, the KEK, accounts. From the design of
`openspec/changes/archive/2026-11-10-add-byok-key-isolation/design.md`:

| Threat | Mitigation |
|---|---|
| Database dump or backup leak | only ciphertext is stored; the KEK is not in the database or the dump |
| One user using another's key (IDOR, row swap) | repositories require the user id; the user id is in the AES-GCM associated data |
| Provider echoes a key in an error | masked-key pattern in redaction; provider text is never shown (fixed messages) |
| Key in a traceback or span | per-turn literal protection plus patterns; spans scrubbed |
| Key in a queued task (Redis persists messages) | payload guard; the worker loads by id |
| KEK loss | users re-enter their key; nothing else is lost |

Accepted: Python cannot zero strings (the plaintext lives only for the turn); the KEK in an
environment variable is visible to anyone with shell access on the VM (a single-tenant VM; a key
management service is the follow-up named in that design).

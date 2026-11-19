# commons/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `commons/`.

- `commons/` must not import any other project package, read `config/`, do I/O, or call an
  LLM. Functions are pure; anything configurable (e.g. unit aliases) is a parameter.
- Add a module here only when it is generic and used (or clearly about to be used) by more
  than one layer; otherwise keep it with its caller.
- `stop.py` (`StopCheck`, `StoppedError`: a computation asks, at its boundaries, whether to stop) and
  `json_safe.py` (data as strict JSON, non-finite numbers absent) are pure.
- `sealed_secret.py` (AES-256-GCM seal and open, key id, key parsing), `payload_guard.py` (refuses a
  queued payload carrying a credential) and `key_patterns.py` (the shapes redaction hides) take every
  key, value and list as an argument; the key-encryption key never comes from here.

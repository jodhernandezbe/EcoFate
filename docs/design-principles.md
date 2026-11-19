[← Documentation index](../README.md#documentation) · [All docs](README.md)

# Design principles

Enforced by review (only function length has a hook); call out deliberate exceptions.

## SOLID
- **Single responsibility**: one reason to change per module and function (fetch, parse,
  convert and present are separate steps).
- **Open/closed**: extend via config or a new small function, not by editing working code
  (a new CompTox property is a `settings.toml` entry).
- **Liskov**: injected collaborators (HTTP client, `BaseChatModel`, `sleep`) and test fakes
  must honour the real contract.
- **Interface segregation**: pass and return the smallest type that works (focused
  TypedDicts/dataclasses, not one wide dict).
- **Dependency inversion**: inject collaborators; build defaults only at the outer edge.

## DRY
- One source of truth: URLs and units in `config/`, shared types in `tools/schemas.py`,
  generic helpers in `commons/`.
- Dedupe knowledge, not coincidence: extract on the third use or when copies must change
  together.

## Defensive programming
- Validate at the boundary once; treat external data as untrusted (check type and shape,
  finite numbers only, never `bool` as a number, verify it matches what you asked for).
- Fail closed: unverified or implausible data becomes absent with a reason, never guessed
  or coerced.
- Setup errors raise; data problems return `None` plus a warning.
- Catch only expected exceptions, never silently; time-bound every external call.
- Return copies of cached or config-backed data; prefer frozen dataclasses and tuples.
- Give each rule a negative test.

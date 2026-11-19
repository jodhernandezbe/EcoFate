[← Documentation index](../../README.md#documentation) · [Architecture](../architecture.md) · [Monitoring](../monitoring.md)

# Security

How EcoFate protects accounts, keys and data. The code rules are in `api/CLAUDE.md`,
`storage/CLAUDE.md`, `app/CLAUDE.md` and `worker/CLAUDE.md`; the sections below say what the
mechanisms are and where to check them.

## Contents

- [Keys](keys.md): bring your own key, key storage and rotation
- [Accounts and sessions](accounts-and-sessions.md): sign-up, passwords, sessions, throttling, administrators
- [Tenancy and the daily limit](tenancy-and-limits.md): per-user isolation, what crosses processes, the turn limit
- [Redaction and the threat model](redaction-and-threats.md): log redaction, assets, threats and mitigations
- [Secrets and automated checks](secrets-and-checks.md): CI and production secrets, pre-commit and audit checks, reporting a vulnerability

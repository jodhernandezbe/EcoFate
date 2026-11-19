[← Documentation index](../README.md#documentation) · [Architecture](architecture.md)

# Documentation

The cross-cutting documents. The folder READMEs are indexed in the
[root README](../README.md#documentation); developers start at [DEVELOPMENT.md](../DEVELOPMENT.md).

## Contents

- [Guides](#guides)
- [UI audits](#ui-audits)
- [Diagrams](#diagrams)
- [Folder READMEs](#folder-readmes)

## Guides

| File | What it covers |
|---|---|
| [demo.md](demo.md) | one real assessment in screenshots, from the question to monitoring and evaluation |
| [getting-started.md](getting-started.md) | Docker, the `make` targets, local development with uv, the command line |
| [reviewers.md](reviewers.md) | where each capstone criterion is and how to check it |
| [citation.md](citation.md) | licence, the Zenodo DOI, releasing a version |
| [architecture.md](architecture.md) | package layers, dependency rules, runtime containers, a turn's path, where state lives, configuration versus secrets |
| [security/](security/README.md) | bring your own key, key sealing and rotation, accounts and sessions, tenancy isolation, daily limit, redaction, threat model, secrets in CI and production |
| [load-test.md](load-test.md) | many users at once: scripted and real-model runs, queue waits, job throughput, what the evaluations changed |
| [monitoring.md](monitoring.md) | Logfire set-up (write and read tokens), what a session records, how the admin Monitoring view reads it, redaction |
| [deployment/](deployment/README.md) | provisioning the Oracle Cloud VM and Cloudflare tunnel, releasing, rolling back, logs, backups and restore, teardown |
| [design-principles.md](design-principles.md) | SOLID, DRY and defensive programming rules the code follows |

| Subfolder | Pages |
|---|---|
| [security/](security/README.md) | [keys](security/keys.md) · [accounts and sessions](security/accounts-and-sessions.md) · [tenancy and limits](security/tenancy-and-limits.md) · [redaction and threats](security/redaction-and-threats.md) · [secrets and checks](security/secrets-and-checks.md) |
| [deployment/](deployment/README.md) | [prerequisites and provision](deployment/prerequisites-and-provision.md) · [Cloudflare](deployment/cloudflare.md) · [first login and secrets](deployment/first-login-and-secrets.md) · [deploy key and GitHub](deployment/deploy-key-and-github.md) · [release and rollback](deployment/release-and-rollback.md) · [logs, backups, restore](deployment/logs-backups-restore.md) · [teardown and security](deployment/teardown-and-security.md) |
| [api/docs/](../api/README.md) | [running and testing](../api/docs/running-and-testing.md) · [endpoints and streaming](../api/docs/endpoints-and-streaming.md) · [accounts and email](../api/docs/accounts-and-email.md) · [keys and BYOK](../api/docs/keys-and-byok.md) |
| [evals/docs/](../evals/README.md) | [scenarios](../evals/docs/scenarios.md) · [catalogue and labels](../evals/docs/catalogue-and-labels.md) · [judge tuning](../evals/docs/judge-tuning.md) · [running and cost](../evals/docs/running-and-cost.md) |

## UI audits

Three runs of `/ui-audit` on the frontend against [`frontend/DESIGN.md`](../frontend/DESIGN.md),
each with a ranked improvement proposal:

| File | Run |
|---|---|
| [ui-audit-2026-10-30.md](ui-audit-2026-10-30.md) | first audit |
| [ui-audit-2026-11-01.md](ui-audit-2026-11-01.md) | second, after the first proposals were applied |
| [ui-audit-2026-11-09.md](ui-audit-2026-11-09.md) | third, after accounts were added |

## Diagrams

Editable draw.io files (`.drawio.svg`: open in draw.io, rendered as images on GitHub) in
`diagrams/`. Each is shown in the document it explains, with the source files it was drawn from.

| Diagram | Shown in |
|---|---|
| [system-context.drawio.svg](diagrams/system-context.drawio.svg) | [architecture.md](architecture.md#system-context) |
| [containers.drawio.svg](diagrams/containers.drawio.svg) | [architecture.md](architecture.md#runtime-containers) |
| [package-layers.drawio.svg](diagrams/package-layers.drawio.svg) | [architecture.md](architecture.md#package-layers) |
| [agent-graph.drawio.svg](diagrams/agent-graph.drawio.svg) | [agent/README.md](../agent/README.md#the-graph) |
| [turn-sequence.drawio.svg](diagrams/turn-sequence.drawio.svg) | [worker/README.md](../worker/README.md#a-turns-sequence) |
| [batch-assessment.drawio.svg](diagrams/batch-assessment.drawio.svg) | [tools/README.md](../tools/README.md#the-batch-assessment) |
| [evaluation-pipeline.drawio.svg](diagrams/evaluation-pipeline.drawio.svg) | [evals/README.md](../evals/README.md#pipeline) |
| [release-rollback.drawio.svg](diagrams/release-rollback.drawio.svg) | [deploy/README.md](../deploy/README.md#release-and-rollback) |

## Folder READMEs

[agent](../agent/README.md) · [tools](../tools/README.md) · [models](../models/README.md) ·
[prompts](../prompts/README.md) · [config](../config/README.md) · [storage](../storage/README.md) ·
[api](../api/README.md) · [worker](../worker/README.md) · [frontend](../frontend/README.md) ·
[evals](../evals/README.md) · [deploy](../deploy/README.md)

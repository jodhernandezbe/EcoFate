## Context

See proposal.md for motivation. What shapes the approach:

- ROADMAP fixes the topology: `api`, `worker`, `db` (postgres:16-alpine), `redis`
  (redis:7-alpine), `mailpit` (dev only) and, in production only, `caddy` via
  `compose.prod.yaml`. One `DATABASE_URL`; secrets only from the environment; non-secrets in
  `config/settings.toml`. Moving to RDS later is a connection-string change.
- `add-docker-compose-stack` gives the multi-stage `Dockerfile` (`api`, `worker` targets),
  `compose.yaml`, named volumes for `.cache/` and the Hugging Face model, and a `Makefile`.
  `migrate-to-postgresql` gives Alembic migrations in `storage/migrations/`.
  `add-ci-pipeline` gives CI on push/PR; this change adds the tag-driven deploy workflow.
- The API already exposes a health endpoint used by compose health checks (from step 1);
  this change requires it to check the database and Redis.
- The MolDeBERTa read-across model (~500 MB) plus torch need about 4 GB RAM at peak; a
  `t3.medium` (2 vCPU, 4 GB) or Lightsail 4 GB bundle is the smallest safe size. A 2 GB swap
  file is added as a buffer.
- The app serves SSE; a proxy must not buffer it.

## Goals / Non-Goals

**Goals:**
- One command to provision, one to tear down, with the cost stated.
- A release is a git tag; deploy is automatic, migrated, health-checked and rolled back on
  failure.
- No secret in git, in an image, in a GitHub log, or readable by another OS user on the VM.
- Data survives a VM loss (nightly off-host backup) and a restore has been tried once.

**Non-Goals:**
- High availability, autoscaling, multi-region, zero-downtime deploys (a few seconds of
  downtime on deploy is accepted for a capstone demo).
- Terraform/CDK; a shell script with the AWS CLI is enough for one VM and is easier for a
  reviewer to read. (Noted as the next step if the deployment grows.)
- Amazon RDS, ElastiCache, ECS (rejected by the user's choice; see ROADMAP).
- A CDN or WAF.

## Decisions

1. **EC2 `t3.medium` as the default, Lightsail 4 GB as a documented alternative.** EC2 gives
   instance roles (SSM Parameter Store and S3 access without keys) and SSM Run Command;
   Lightsail is a flat ~USD 24/month but has no instance roles, so it would need an access
   key on the box. Default EC2 with a 30 GB gp3 volume: about USD 30/month on demand
   (~USD 0.0416/h + storage + IP), less with a savings plan; stated in `docs/deployment.md`.
2. **Deploy over SSM Run Command, not SSH.** GitHub assumes an IAM role through OIDC limited
   to `ssm:SendCommand` on the one instance (by tag) and reading the command result; port 22
   can then stay closed, or open only to the operator's CIDR for emergencies. Alternative:
   SSH with a deploy key in GitHub secrets; rejected (long-lived key, inbound 22 from GitHub
   runner ranges).
3. **GHCR for images.** Free for the repository, same identity as the code; images are
   tagged `vX.Y.Z` and `sha-<short>`; the VM pulls with a read-only token stored in SSM.
   Alternative: ECR; adds cost and a registry login helper for no gain here.
4. **Secrets in SSM Parameter Store `SecureString`** under `/ecofate/prod/` (`DATABASE_URL`,
   `POSTGRES_PASSWORD`, `REDIS_URL`, `ECOFATE_KEY_ENCRYPTION_KEY`, `ECOFATE_SESSION_SECRET`,
   `SMTP_PASSWORD`, `COMPTOX_API_KEY`, `CENSUS_API_KEY`, `LOGFIRE_TOKEN`,
   `LOGFIRE_READ_TOKEN`, `GHCR_READ_TOKEN`). `fetch-secrets.sh` writes `.env.prod` with
   `umask 077` at each deploy; values never pass through the GitHub runner. Alternative:
   Secrets Manager; ~USD 0.40 per secret per month for rotation we do not need.
5. **Migrations as a one-off `migrate` service** using the `api` image and
   `alembic upgrade head`; `api` and `worker` `depends_on: migrate: condition:
   service_completed_successfully`. A failed migration stops the deploy before any new code
   serves traffic. Expand/contract rule (documented in `storage/CLAUDE.md`): a release may
   add columns/tables but drops or renames only in a later release, so rollback to the
   previous image is safe without a down-migration.
6. **Caddy for TLS.** Automatic Let's Encrypt issuance and renewal with a five-line
   `Caddyfile`; `flush_interval -1` for SSE; HSTS, `X-Content-Type-Options`,
   `Referrer-Policy`, `frame-ancestors 'none'`. Certificates persist in a named volume to
   avoid rate limits. Alternative: nginx + certbot; more moving parts.
7. **Rollback by recorded tag.** `deploy.sh` writes the running tag to
   `/opt/ecofate/RELEASE` before switching and keeps the previous one in `RELEASE.prev`;
   on a failed health check (10 tries, 6 s apart) it redeploys `RELEASE.prev`. The workflow
   has a `rollback` dispatch input taking any tag.
8. **Backups**: systemd timer at 03:15 UTC runs `docker compose exec -T db pg_dump -Fc` to
   a temp file, uploads to `s3://<bucket>/pg/<date>.dump` with the instance role, deletes
   the local copy. S3 versioning + lifecycle keeps 30 days. `restore.sh <date>` restores into
   a new database and swaps `DATABASE_URL` only after a row-count sanity check.
9. **Logs**: Docker `json-file` driver with `max-size: 10m`, `max-file: 5`; agent traces in
   Logfire; no CloudWatch agent (cost/complexity). Documented commands for reading logs.

## Risks / Trade-offs

- [Single VM is a single point of failure] → accepted for a demo; backups bound data loss to
  one day; re-provision + restore is documented and drilled.
- [4 GB RAM is tight with torch] → swap file, `mem_limit` per service, the read-across model
  loaded lazily; if OOM is observed, move to `t3.large` (one config value).
- [Let's Encrypt needs DNS before first start] → provisioning prints the IP; the guide says to
  create the A record first; without a domain, the VM's public DNS name works.
- [SSM agent not ready on first boot] → deploy workflow retries the command for a few
  minutes.
- [Cost overrun after grading] → teardown script and a cost note; optional AWS Budget alarm
  created by `provision.sh`.
- [A migration that is not backward compatible breaks rollback] → expand/contract rule plus
  a CI check that the previous tag's tests pass against the new schema is out of scope;
  reviewers enforce the rule.

## Migration Plan

1. Owner creates the SSM parameters (guide lists each one and how to generate the
   encryption key and session secret), runs `make deploy-provision`, points DNS at the IP.
2. Owner adds the GitHub variables `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `ECOFATE_DOMAIN`.
3. Push tag `v1.0.0`; the workflow publishes images and deploys; owner creates the first
   admin with the CLI command from `add-user-accounts` through SSM Session Manager.
4. Run the restore drill once and record the result in `docs/deployment.md`.

Rollback of this change: `make deploy-teardown` removes every AWS resource; the repository
files can stay (they do nothing without the AWS resources).

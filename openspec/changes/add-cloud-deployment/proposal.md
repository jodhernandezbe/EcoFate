## Why

After ROADMAP steps 1-8, EcoFate is a containerised, multi-user BYOK service. It still runs
only on a developer machine, so reviewers must install it to see it, and the capstone awards
2 points for a cloud deployment. The user chose one AWS virtual machine running the same
docker compose stack as local development, with PostgreSQL as a container (see ROADMAP,
"PostgreSQL: a compose service everywhere"): the cheapest option (about USD 20-35 a month),
identical to what reviewers run locally, and easy to tear down after grading.

## What Changes

- **Provisioning**: `deploy/aws/provision.sh` (AWS CLI) creates, in one region from
  `deploy/aws/config.env`: an Ubuntu 24.04 VM (EC2 `t3.medium` or Lightsail 4 GB; the
  read-across model needs about 4 GB RAM), an Elastic/static IP, a security group allowing
  80 and 443 from anywhere and 22 only from the operator's CIDR (or no 22 at all when SSM
  Session Manager is used), an instance role allowed to read `/ecofate/prod/*` from SSM
  Parameter Store and write to one S3 backup bucket, the bucket itself (private, versioned,
  encrypted, 30-day lifecycle), and a `cloud-init.yaml` that installs Docker Engine and the
  compose plugin, creates a non-root `ecofate` user and enables unattended security updates.
  `deploy/aws/teardown.sh` deletes all of it (asking for the bucket name to confirm).
  `docs/deployment.md` states the monthly cost and the teardown steps.
- **Production compose**: `compose.prod.yaml` overrides `compose.yaml`: images pulled from
  GHCR by tag instead of built, `restart: unless-stopped`, no published ports except Caddy's
  80/443, the `mailpit` dev profile replaced by real SMTP settings, resource limits, json-file
  log rotation, and a `caddy` service with a `Caddyfile` that obtains and renews a Let's
  Encrypt certificate for the configured domain, redirects HTTP to HTTPS, sets HSTS and
  security headers, and proxies to `api` (SSE without buffering).
- **Secrets**: `deploy/fetch-secrets.sh` writes `/opt/ecofate/.env.prod` (mode 0600, owner
  `ecofate`) from SSM Parameter Store `SecureString` parameters under `/ecofate/prod/`,
  using the instance role; no secret is in git, in a GitHub log, or in an image.
- **Images and CD**: on a version tag `v*.*.*`, a workflow `.github/workflows/deploy.yml`
  builds the `api` and `worker` images, pushes them to `ghcr.io/<owner>/ecofate-{api,worker}`
  tagged with the version and the commit SHA, then deploys through AWS SSM Run Command (no
  inbound SSH from GitHub), authenticated to AWS with GitHub OIDC (no long-lived AWS keys).
  The deploy script on the VM records the running tag, fetches secrets, pulls the new
  images, runs `alembic upgrade head` in a one-off `migrate` container, and starts the
  stack; `api` and `worker` start only after `migrate` completed successfully.
- **Health and rollback**: the deploy waits for the `api` health check (database and Redis
  reachable) through Caddy over HTTPS; if it fails, it redeploys the previously recorded tag
  and the workflow fails. A manual `rollback` workflow input redeploys any earlier tag.
  Migrations are written to be backward compatible for one release (expand, then contract),
  so the previous image works against the upgraded schema.
- **Backups**: a systemd timer on the VM runs `pg_dump --format=custom` nightly inside the
  `db` container and uploads it to the S3 bucket; `deploy/restore.sh` restores a named dump
  into a fresh database. A documented restore drill is part of this change's verification.
- **Logs**: containers log JSON to stdout with rotation; `docs/deployment.md` explains
  `docker compose logs` on the VM and that agent traces go to Logfire (admin Monitoring
  view). Log redaction from `add-byok-key-isolation` applies unchanged.
- **Makefile targets** `deploy-provision`, `deploy-teardown`, `deploy-backup`,
  `deploy-restore` wrapping the scripts.

## Capabilities

### New Capabilities

- `cloud-deployment`: how the system is provisioned on AWS, configured with secrets, released
  from a tag, migrated, health-checked, rolled back, backed up, restored and torn down.

### Modified Capabilities

(none; the `ci-pipeline` capability from `add-ci-pipeline` is unchanged, publishing lives in
the separate deploy workflow)

## Impact

- New: `deploy/aws/{config.env.example,provision.sh,teardown.sh,cloud-init.yaml,iam-policy.json}`,
  `deploy/{deploy.sh,fetch-secrets.sh,backup.sh,restore.sh,ecofate-backup.service,ecofate-backup.timer}`,
  `compose.prod.yaml`, `deploy/Caddyfile`, `.github/workflows/deploy.yml`, `docs/deployment.md`.
- `Makefile` (targets), `compose.yaml` (a `migrate` one-off service and `depends_on:
  condition: service_completed_successfully` for `api` and `worker`, if not already added by
  `migrate-to-postgresql`), `.gitignore` (`deploy/aws/config.env`, `.env.prod`).
- `config/settings.toml`: production values that are not secrets (e.g. `[telemetry]
  environment`) are overridden through an environment-selected settings layer only if the
  loader from `add-docker-compose-stack` supports it; otherwise through documented environment
  variables named in settings.
- README: the public URL (or a note that the demo was torn down, with screenshots) and a link
  to `docs/deployment.md`.
- Costs money while running; the owner needs an AWS account, a domain (or the VM's public
  DNS name with a Caddy certificate for it), and GitHub repository secrets/variables for the
  OIDC role ARN and region.

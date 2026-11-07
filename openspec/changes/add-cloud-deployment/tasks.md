## 1. Production compose and proxy

- [ ] 1.1 Write `compose.prod.yaml`: `api`/`worker`/`migrate` use `image: ghcr.io/<owner>/ecofate-{api,worker}:${ECOFATE_TAG}`, `env_file: /opt/ecofate/.env.prod`, `restart: unless-stopped`, `mem_limit`s, json-file log rotation; no ports published except `caddy` 80/443; `mailpit` excluded.
- [ ] 1.2 Add the one-off `migrate` service (`alembic upgrade head`) to `compose.yaml` if `migrate-to-postgresql` has not, and make `api` and `worker` depend on it with `service_completed_successfully`.
- [ ] 1.3 Write `deploy/Caddyfile`: site `{$ECOFATE_DOMAIN}`, `reverse_proxy api:8000 { flush_interval -1 }`, HSTS and security headers; `caddy_data` volume for certificates.
- [ ] 1.4 Make the API health endpoint report unhealthy when Postgres or Redis is unreachable (fixed body, no error text); add a test with fakes.

## 2. Provisioning and teardown

- [ ] 2.1 Write `deploy/aws/config.env.example` (region, instance type, key-less defaults, operator CIDR, bucket name, domain) and git-ignore `deploy/aws/config.env`.
- [ ] 2.2 Write `deploy/aws/cloud-init.yaml` (Docker Engine + compose plugin from Docker's apt repo, `ecofate` user, `/opt/ecofate`, 2 GB swap, unattended-upgrades, SSM agent check) and `deploy/aws/iam-policy.json` (read `/ecofate/prod/*`, decrypt with the SSM KMS key, put/get on the backup bucket only).
- [ ] 2.3 Write `deploy/aws/provision.sh` (idempotent, `set -euo pipefail`): security group (80/443 open, 22 only from the operator CIDR or none), instance role + profile, S3 bucket (block public access, versioning, SSE, 30-day lifecycle), EC2 instance with cloud-init and tags, Elastic IP, optional AWS Budget alarm; prints the IP and next steps.
- [ ] 2.4 Write `deploy/aws/teardown.sh` that deletes everything `provision.sh` created, after typing the bucket name to confirm.

## 3. Secrets and deploy script

- [ ] 3.1 Write `deploy/fetch-secrets.sh`: reads every parameter under `/ecofate/prod/` with decryption via the instance role and writes `/opt/ecofate/.env.prod` with `umask 077`, owner `ecofate`; never prints a value.
- [ ] 3.2 Write `deploy/deploy.sh <tag>`: log in to GHCR with the stored read token, record `RELEASE` → `RELEASE.prev`, fetch secrets, `docker compose -f compose.yaml -f compose.prod.yaml pull`, `up -d` (migrate runs first), poll `https://$ECOFATE_DOMAIN/<health>`; on failure redeploy `RELEASE.prev` and exit non-zero. <!-- pragma: allowlist secret -->

## 4. Release workflow

- [ ] 4.1 Write `.github/workflows/deploy.yml`: on tags `v*.*.*` and `workflow_dispatch` (input `rollback_tag`, validated against the tag pattern); `permissions: contents: read, packages: write, id-token: write`; build and push both images to GHCR tagged version + `sha-<short>`; `aws-actions/configure-aws-credentials` with OIDC role; `aws ssm send-command` running `deploy.sh <tag>` on the instance by tag, wait for the result with retries, fail the job on failure; all actions SHA-pinned; `environment: production`.
- [ ] 4.2 Document the OIDC trust policy (repository + tag ref condition) and the minimal role policy in `deploy/aws/` and `docs/deployment.md`.

## 5. Backups and restore

- [ ] 5.1 Write `deploy/backup.sh` and the systemd `ecofate-backup.service`/`.timer` (03:15 UTC): `pg_dump -Fc` in the `db` container to a temp file, upload to `s3://<bucket>/pg/<UTC date>.dump`, remove the local file, exit non-zero on any failure.
- [ ] 5.2 Write `deploy/restore.sh <date>`: download, restore into a new database, check row counts of the core tables, then switch and restart `api`/`worker`.

## 6. Makefile and documentation

- [ ] 6.1 Add `deploy-provision`, `deploy-teardown`, `deploy-backup`, `deploy-restore` targets to the `Makefile`.
- [ ] 6.2 Write `docs/deployment.md`: architecture diagram (internet → Caddy → api/worker → db/redis, S3, SSM, GHCR, Logfire), costs per month, prerequisites, SSM parameters to create (and how to generate the encryption key and session secret), first deploy, creating the first admin, releasing, rollback, reading logs, backups and the restore drill result, teardown.
- [ ] 6.3 README: public URL (or "demo torn down" with screenshots) and a link to `docs/deployment.md`.

## 7. Verification

- [ ] 7.1 `shellcheck` on every script, `actionlint` on the workflow, `docker compose -f compose.yaml -f compose.prod.yaml config` validates, `uv run pre-commit run --all-files` passes (detect-secrets clean).
- [ ] 7.2 Provision, deploy `v1.0.0`, sign up, run one assessment over HTTPS, confirm the certificate and HSTS header.
- [ ] 7.3 Deploy a tag whose health check fails on purpose and confirm the automatic rollback to the previous tag.
- [ ] 7.4 Run one backup, restore it into a fresh database, record the drill (date, dump size, time taken) in `docs/deployment.md`.
- [ ] 7.5 Confirm with `nmap`/the console that only 80/443 (and 22 from the operator CIDR, if enabled) are reachable, and that `.env.prod` is mode 0600.

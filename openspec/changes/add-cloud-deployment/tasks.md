## 1. arm64 images first (de-risk)

- [x] 1.1 Build the `api` and `worker` targets for `linux/arm64` (locally with buildx, or a throwaway workflow run on `ubuntu-24.04-arm`); confirm every native wheel installs and `python -c "import torch, rdkit, chromadb"` runs in the image. If it fails, stop and revisit the platform choice.

## 2. App changes for production behind Cloudflare

- [x] 2.1 Production settings override in `config/` (typed loader, environment-selected): public origin, `cookie_secure`, `trusted_proxy_hops`, `[telemetry].environment`; local defaults unchanged; tests including refusals of malformed values.
- [x] 2.2 Origin guard checks `Host` and `Origin` against the public origin when set (it stays strict for every path, `/api/health` included); the container health check becomes `python -m api.container_health`, which calls `/api/health` on loopback with the origin's own `Host`; tests: public host served, other hosts and origins rejected, the health command sends the right `Host` locally and in production, local runs unchanged.
- [x] 2.3 SSE comment heartbeat in the chat event relay at a `[ui]`-configured interval (about 15 s, below Cloudflare's 100 s); tests with a quiet fake turn.
- [x] 2.4 Health endpoint also checks Redis (fixed body, no error text); tests with fakes for each dependency down.

## 3. Production compose and secrets

- [x] 3.1 `compose.prod.yaml`: `api`/`worker`/`migrate` from `ghcr.io/jodhernandezbe/ecofate-{api,worker}:${ECOFATE_TAG}`, `env_file: /opt/ecofate/.env.prod`, no published ports, `mem_limit`s, json-file log rotation, `restart: unless-stopped`; a `cloudflared` service (`tunnel run`, pinned image, token from its own `/opt/ecofate/tunnel.env` so the API and worker never hold it); `ECOFATE_SETTINGS_PROFILE=production` on `api`, `worker` and `migrate`; dev-only services excluded. `docker compose -f compose.yaml -f compose.prod.yaml config` validates.
- [x] 3.2 `deploy/env.prod.example` and `deploy/tunnel.env.example`: every required variable name with a comment on how to generate or obtain it, no values (uncommented names are the list `deploy.sh` requires); git-ignore `.env.prod`, `tunnel.env` and `deploy/oci/config.env`.

## 4. Provisioning and teardown on Oracle Cloud

- [x] 4.1 `deploy/oci/config.env.example` (compartment, tenancy, OCPUs, memory, boot size, operator SSH key, Bastion client /32, bucket name, capacity retries) and git-ignore `deploy/oci/config.env`.
- [x] 4.2 `deploy/oci/cloud-init.yaml`: Docker Engine + compose plugin from Docker's apt repo (arm64), OCI CLI, `ecofate` user, `/opt/ecofate`, unattended-upgrades.
- [x] 4.3 `deploy/oci/provision.sh` (idempotent, `set -euo pipefail`): refuses shapes beyond Always Free and a Bastion range wider than /32; VCN, internet gateway, subnet and a security list whose only inbound rule is SSH from the subnet (re-applied each run); an OCI Bastion accepting only the operator's /32, with `deploy/oci/bastion-ssh.sh` opening a one-hour port-forwarding session for the first login; A1 Flex instance with cloud-init (retry with backoff across availability domains on capacity errors); dynamic group + policy for objects in the one bucket; private bucket with a 30-day retention rule; prints next steps.
- [x] 4.4 `deploy/oci/teardown.sh`: deletes everything `provision.sh` created after typing the bucket name.

## 5. Deploy path

- [x] 5.1 `deploy/deploy.sh <tag>`: runs from a private copy (it moves its own checkout), accepts only `deploy|rollback vX.Y.Z`, validates the tag pattern, takes a lock, checks `.env.prod` mode/owner and required variables (names only), records `RELEASE` → `RELEASE.prev`, `pull`, `up -d` (migrate first), polls `https://ecofate.org/api/health`; on failure redeploys `RELEASE.prev` and exits non-zero. Installed as the deploy key's forced command (`authorized_keys` options documented).
- [x] 5.2 `.github/workflows/deploy.yml`: on tags `v*.*.*` and `workflow_dispatch` (`rollback_tag`, validated against the pattern, passed via `env:`); `permissions: contents: read, packages: write`; build and push both images on `ubuntu-24.04-arm` tagged version + `sha-<short>`; deploy job uses the pinned `cloudflared` image as SSH `ProxyCommand` (`access ssh`, Access service token via environment), the deploy key and a pinned `known_hosts` from secrets, and the `DEPLOY_SSH_HOST` variable; all actions SHA-pinned; `environment: production`.

## 6. Backups and restore

- [x] 6.1 `deploy/backup.sh` + systemd `ecofate-backup.service`/`.timer` (03:15 UTC): `pg_dump -Fc` in `db`, upload with `oci os object put --auth instance_principal --no-overwrite` as `pg/<UTC date>T<UTC time>.dump` (the VM may create and read dumps but not overwrite or delete them), remove the local file, exit non-zero on any failure.
- [x] 6.2 `deploy/restore.sh <timestamp>`: download, restore into a new database, show row counts of the core tables, switch only after typing `switch`, in one transaction (a failed switch leaves the live database live and restarts the app); the previous database is kept, renamed. Shared paths and the compose call live in `deploy/lib.sh`.

## 7. Makefile and documentation

- [x] 7.1 `Makefile`: `deploy-provision`, `deploy-teardown`, `deploy-backup`, `deploy-restore`.
- [x] 7.2 `docs/deployment.md`: architecture (Cloudflare → tunnel → api/worker → db/redis; GHCR; Object Storage; Logfire), USD 0 cost and how to keep it (Always Free shapes only, Pay As You Go upgrade against idle reclamation, USD 1 budget alert), Oracle sign-up and console walkthrough, capacity tips and the Hetzner fallback, Cloudflare Tunnel + Access setup, `www` redirect, Always Use HTTPS + HSTS, SMTP via Cloudflare Email Service (Resend fallback) and the SPF/DKIM records, creating `.env.prod`, first deploy, first admin, releasing, rollback, logs, backups and the restore drill, teardown.
- [x] 7.3 README: `https://ecofate.org` and a link to `docs/deployment.md`.

## 8. Verification

- [x] 8.1 `shellcheck` on every script, `actionlint` on the workflow, compose config validates, `uv run pre-commit run --all-files` passes (detect-secrets clean).
- [ ] 8.2 Provision, deploy `v0.2.0`, sign up with a real mailbox (email arrives, SPF/DKIM pass), run one assessment at `https://ecofate.org`, confirm the HSTS header, the `Secure` cookie, and a long turn's stream staying open; confirm `trusted_proxy_hops = 1` by checking that two visitors' sign-in throttles are counted separately (cloudflared does not append its own address to `X-Forwarded-For`).
- [ ] 8.3 Deploy a tag whose health check fails on purpose and confirm the automatic rollback.
- [ ] 8.4 Run one backup, restore it into a fresh database, record the drill (date, dump size, time) in `docs/deployment.md`.
- [ ] 8.5 Confirm in the OCI console and with a port scan from the internet that no port answers, that the Bastion accepts only the operator's /32, that the deploy key cannot open a shell, and that `.env.prod` is mode 0600.

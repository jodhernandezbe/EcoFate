## Why

EcoFate is a containerised, multi-user BYOK service with CI, but it runs only on a developer
machine, so reviewers must install it to see it, and the capstone awards 2 points for a cloud
deployment. The owner bought `ecofate.org` (DNS on Cloudflare) and wants no monthly cost. Oracle
Cloud's Always Free tier offers an Arm VM with up to 4 OCPUs and 24 GB of memory, enough for the
read-across model (about 4 GB at peak), so the same docker compose stack that runs locally can run
there for USD 0 a month, always on, reachable at `https://ecofate.org` through a Cloudflare Tunnel.

## What Changes

- **Provisioning on Oracle Cloud**: `deploy/oci/provision.sh` (OCI CLI) creates, from
  `deploy/oci/config.env`, one Always Free Ampere A1 Flex VM (Ubuntu 24.04 aarch64; 4 OCPU /
  24 GB by default, never above the Always Free limits), its VCN and subnet with a security list
  that allows **no inbound traffic**, a dynamic group and policy letting that VM write to one
  Object Storage backup bucket (instance principal, no keys), the private bucket itself with a
  30-day retention rule, and a `cloud-init.yaml` that installs Docker Engine and the compose
  plugin, creates a non-root `ecofate` user and enables unattended security updates. Capacity
  errors ("out of host capacity") are retried and documented; `docs/deployment.md` also walks
  through the same steps in the OCI console. `deploy/oci/teardown.sh` deletes all of it after
  typing the bucket name. The guide tells the owner to upgrade the tenancy to Pay As You Go (still
  free within Always Free limits, and then idle Always Free VMs are not reclaimed) and to set a
  budget alert.
- **Cloudflare in front, nothing open on the VM**: a `cloudflared` service in `compose.prod.yaml`
  (tunnel token in the VM's environment file) connects out to Cloudflare, which serves
  `https://ecofate.org` with its certificate, redirects `www.ecofate.org` and HTTP to HTTPS, sets
  HSTS, and forwards to `api`. No Caddy, no Let's Encrypt, no published host ports.
- **Production compose**: `compose.prod.yaml` overrides `compose.yaml`: `api`, `worker` and
  `migrate` pulled from GHCR by tag instead of built, `restart: unless-stopped`, no published
  ports, memory limits, json-file log rotation, real SMTP settings instead of the `mailpit` dev
  profile.
- **Production settings the app needs** (found in the code): the origin guard accepts only
  `[ui].host:[ui].port` and would reject `ecofate.org`; the session cookie is not `Secure`; client
  addresses for sign-in throttling would all be the tunnel's. A production settings override sets
  the public origin `https://ecofate.org`, `cookie_secure = true`, the trusted proxy hops for
  Cloudflare and `cloudflared`, and `[telemetry].environment = "production"`.
- **Streams survive Cloudflare**: the chat event stream sends an SSE comment heartbeat about every
  15 s while a turn is quiet, so Cloudflare's 100 s idle timeout never cuts it.
- **Secrets stay on the VM**: `/opt/ecofate/.env.prod` (mode 0600, owner `ecofate`) is created
  once by the owner on the VM and never passes through git, GitHub or an image; the deploy only
  checks that every required variable is present, without printing values.
- **Images and CD**: on a version tag `v*.*.*` (first deploy `v0.2.0`; `v0.1.0` is already
  released and archived on Zenodo), `.github/workflows/deploy.yml` builds the `api` and `worker`
  images for `linux/arm64` on GitHub's Arm runners, pushes them to
  `ghcr.io/jodhernandezbe/ecofate-{api,worker}` tagged with the version and the commit, then
  connects to the VM over SSH **through the tunnel** (Cloudflare Access service token) with a
  deploy key whose `authorized_keys` entry can only run `deploy.sh`. The deploy pulls the images,
  runs the migrations in the one-off `migrate` service, starts the stack and checks
  `https://ecofate.org/api/health`.
- **Health and rollback**: the health endpoint also checks Redis; a failed check redeploys the
  previously recorded tag and fails the workflow; a manual `rollback_tag` input redeploys any
  earlier tag. Migrations stay backward compatible for one release (expand, then contract).
- **Backups**: a systemd timer runs `pg_dump --format=custom` nightly in the `db` container and
  uploads it to the Object Storage bucket with the instance principal; `deploy/restore.sh`
  restores a named dump into a fresh database. A restore drill is part of verification.
- **Email**: sign-up and password-reset mail is sent through Cloudflare Email Service over SMTP
  (fallback: Resend's free tier) from `no-reply@ecofate.org`, with SPF and DKIM records in
  Cloudflare DNS.
- **Makefile targets** `deploy-provision`, `deploy-teardown`, `deploy-backup`, `deploy-restore`.

## Capabilities

### New Capabilities

- `cloud-deployment`: how the system is provisioned on Oracle Cloud, exposed through Cloudflare,
  configured for production, released from a tag, migrated, health-checked, rolled back, backed
  up, restored and torn down. Its production-behind-Cloudflare requirement also covers the
  public origin, secure cookie, trusted proxy hops and SSE heartbeat the web program needs there.

### Modified Capabilities

(none; `ci-pipeline` is unchanged, publishing and deploying live in the separate deploy workflow)

## Impact

- New: `deploy/oci/{config.env.example,provision.sh,teardown.sh,cloud-init.yaml}`,
  `deploy/{deploy.sh,backup.sh,restore.sh,ecofate-backup.service,ecofate-backup.timer,env.prod.example}`,
  `compose.prod.yaml`, `.github/workflows/deploy.yml`, `docs/deployment.md`.
- App code: a production settings override (origin, cookie, proxy hops, telemetry environment),
  the origin guard reading the public origin, an SSE heartbeat in the chat event relay, Redis in
  the health check; with tests.
- `Makefile` (targets), `.gitignore` (`deploy/oci/config.env`, `.env.prod`).
- README: the public URL and a link to `docs/deployment.md`.
- Cost: USD 0 a month within Oracle Always Free and Cloudflare's free plan. The owner needs an
  Oracle Cloud account (card for verification), the Cloudflare zone for `ecofate.org`, a
  Cloudflare Tunnel and Access service token, and GitHub repository secrets for the deploy key and
  the Access token.

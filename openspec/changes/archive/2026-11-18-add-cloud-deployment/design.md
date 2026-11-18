## Context

See proposal.md for motivation. What shapes the approach:

- The stack is fixed by `compose.yaml`: `api`, `worker`, `migrate` (one-off `python -m storage
  upgrade`, already a dependency of `api` and `worker`), `db` (postgres:16-alpine), `redis`, and
  dev-only `mailpit`, `db-port`, `redis-port`. Secrets come only from the environment;
  non-secrets from `config/settings.toml`.
- The `Dockerfile` builds `api` and `worker` targets on Python 3.13 slim; on Linux, PyTorch comes
  from the CPU wheel index, which publishes `manylinux_2_28_aarch64` wheels (present in
  `uv.lock`), so an arm64 image is possible; the other native wheels (RDKit, chromadb's
  dependencies) must be confirmed by the first arm64 build.
- The app assumes it is reached at `[ui].host:[ui].port`: `api/core/origin_guard.py` rejects
  any other `Host` (403), `[auth].cookie_secure` is false, `[auth].trusted_proxy_hops` is 0, and
  the loader refuses `cookie_secure = false` when `[telemetry].environment` is "production".
- The chat event relay sends nothing while a tool runs; Cloudflare closes a proxied HTTP
  connection after 100 s without data on the free plan. The browser reattaches with
  `Last-Event-ID`, but a heartbeat avoids the break.
- `GET /api/health` checks only the database today.
- Oracle Always Free: Ampere A1 Flex up to 4 OCPU / 24 GB total, 200 GB block storage, 20 GB
  Object Storage, 10 TB egress a month. Always Free VMs idle for 7 days (low CPU, network and
  memory) may be reclaimed unless the tenancy is Pay As You Go. Popular regions often report "out
  of host capacity" for A1.
- DNS for `ecofate.org` is on Cloudflare; the owner has Email Routing / Email Workers active
  (receiving), which is separate from sending.

## Goals / Non-Goals

**Goals:**
- USD 0 a month, always on, at `https://ecofate.org`.
- No inbound port open on the VM; no secret in git, an image, or a GitHub log.
- A release is a git tag; deploy is automatic, migrated, health-checked and rolled back.
- Data survives a VM loss (nightly off-host backup) and a restore has been tried once.

**Non-Goals:**
- High availability, autoscaling, zero-downtime deploys (seconds of downtime per deploy are fine).
- Terraform; one VM is clearer as a commented OCI CLI script plus a console walkthrough.
- Managed database or Redis; a CDN or WAF beyond what Cloudflare's free plan gives by default.

## Decisions

1. **Oracle Cloud Always Free, Ampere A1 Flex, Ubuntu 24.04 aarch64.** 4 OCPU / 24 GB by default
   (configurable down, never above the free limits), 100 GB boot volume. Alternatives: AWS EC2
   `t3.medium` (about USD 30 a month, rejected on cost), Hetzner CAX21 (about EUR 7, kept as the
   documented fallback if A1 capacity never frees up: the same compose files work unchanged),
   scale-to-zero platforms (rejected: managed Postgres and Redis, worker rework, 30-60 s cold
   starts to load the model).
2. **Cloudflare Tunnel instead of a reverse proxy with open ports.** `cloudflared` runs as a
   compose service with the tunnel token from its own `/opt/ecofate/tunnel.env` (so the API and
   worker processes never hold it); the tunnel's public hostname
   `ecofate.org` points at `http://api:8000`; `www.ecofate.org` redirects with a Cloudflare rule;
   "Always Use HTTPS" and HSTS are turned on in the zone. The VM's security list admits nothing
   from the internet; its one inbound rule is SSH from its own subnet, for the OCI Bastion (Always
   Free) that accepts only the operator's /32. A Bastion port-forwarding session is the first
   login, before the tunnel exists, and the emergency path; it needs no agent plugin on the VM.
   Alternatives for the first login: the tunnel token in cloud-init (left readable in instance
   metadata) or temporary SSH from the operator's IP (briefly internet-facing); rejected. Alternative: Caddy with Let's Encrypt and ports 80/443 open; rejected
   (open ports, certificate management, no benefit once DNS is on Cloudflare).
3. **arm64 images built natively on GitHub's Arm runners** (`ubuntu-24.04-arm`, free for public
   repositories), pushed to GHCR (free, public packages need no pull token). Alternative: QEMU
   emulation on x86 runners; rejected (PyTorch-sized builds become very slow).
4. **Deploy over SSH through the tunnel.** The tunnel also exposes `ssh.ecofate.org` behind a
   Cloudflare Access application that accepts only a service token. The workflow runs
   `cloudflared access ssh` with that token (GitHub secrets) and a dedicated deploy key; the key's
   `authorized_keys` line is `command="/opt/ecofate/deploy/deploy.sh",no-pty,no-port-forwarding,...`,
   so it can only deploy a validated tag. Alternatives: OCI Bastion (session TTL limits, more
   setup), a self-hosted runner on the VM (runs untrusted workflow code on the server); rejected.
5. **Secrets only in `/opt/ecofate/.env.prod` on the VM**, created once by the owner from
   `deploy/env.prod.example` (variable names only), mode 0600, owner `ecofate`. `deploy.sh`
   checks every required variable is non-empty and names a missing one without printing values.
   The owner keeps a copy in a password manager (the VM is not the only copy). Alternative: OCI
   Vault with instance principal; rejected as more moving parts for no gain at this size.
6. **Production settings override.** A `[deployment]`-style environment-selected override (chosen
   in implementation, following the existing typed loaders) sets: the public origin
   `https://ecofate.org` (the origin guard checks `Host` and `Origin` against it instead of
   `[ui].host:port`), `cookie_secure = true`, `trusted_proxy_hops` matching
   Cloudflare + `cloudflared` (client address from the right `X-Forwarded-For` entry), and
   `[telemetry].environment = "production"`. Local runs are unchanged. The container health
   checks run inside the container, where a plain loopback request carries `Host: 127.0.0.1:8000`;
   rather than exempting a path from the guard (existing tests require it to refuse foreign hosts
   on `/api/health` too), they run `python -m api.container_health`, which sends the origin's own
   `Host`, so no domain is written into the Dockerfile or compose files.
7. **SSE heartbeat.** The chat event relay emits an SSE comment line (`: keepalive`) when no event
   has been sent for `[ui]`-configured seconds (about 15). Comments are ignored by `EventSource`
   and carry no data.
8. **Migrations as the existing one-off `migrate` service** before `api` and `worker` start;
   expand/contract rule so the previous image works against the migrated schema.
9. **Rollback by recorded tag.** `deploy.sh` writes the running tag to `/opt/ecofate/RELEASE`,
   keeps the previous in `RELEASE.prev`; after `up -d` it polls `https://ecofate.org/api/health`
   (10 tries, 6 s apart); on failure it redeploys `RELEASE.prev` and exits non-zero.
10. **Backups to OCI Object Storage via instance principal.** A dynamic group matching the VM and
    a policy allowing `manage objects` in the one bucket; the OCI CLI on the VM uses
    `--auth instance_principal`. systemd timer 03:15 UTC; 30-day retention rule; a dump is a few
    MB, far under the 20 GB free.
11. **Email via Cloudflare Email Service SMTP** (`smtp.mx.cloudflare.net`, port 465, `tls`, as
    `.env.example` documents) from `no-reply@ecofate.org`, with the SPF/DKIM records Cloudflare
    provides. Fallback: Resend's free tier on port 587. Only `SMTP_*` values change.

## Risks / Trade-offs

- [A1 capacity unavailable in the home region] → `provision.sh` retries with backoff and can try
  each availability domain; the guide explains choosing a less busy home region at sign-up and the
  Hetzner fallback.
- [Idle reclamation of Always Free VMs] → upgrade to Pay As You Go (no charge within free limits)
  plus a budget alert at USD 1.
- [arm64 build fails on a native dependency] → the first task builds the image for arm64 before
  any infrastructure work; the fallback is an x86 Hetzner VM with the existing amd64 images.
- [Cloudflare outage or account problem] → the site is down; accepted for a demo.
- [Single VM] → nightly backups bound data loss to one day; re-provision and restore are drilled.
- [Pay As You Go mistakes cost money] → stay on Always Free shapes only; the budget alert.

## Migration Plan

1. Owner creates the Oracle account (Pay As You Go upgrade, budget alert), runs
   `make deploy-provision` (or the console walkthrough), creates the Cloudflare Tunnel and the
   Access application, writes `/opt/ecofate/.env.prod` on the VM.
2. Owner adds the GitHub secrets (deploy key, Access client id and secret) and the SMTP records.
3. Push tag `v0.2.0`: images are published and deployed; owner creates the first admin with
   `python -m api create-admin` on the VM.
4. Run the restore drill once and record it in `docs/deployment.md`.

Rollback of this change: `make deploy-teardown` removes the Oracle resources; delete the tunnel
and DNS records in Cloudflare; the repository files do nothing without them.

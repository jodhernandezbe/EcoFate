# Deploying EcoFate (Oracle Cloud Always Free + Cloudflare)

EcoFate runs in production at **https://ecofate.org** on one Oracle Cloud Always Free virtual
machine, with the same docker compose stack as local development. Cloudflare serves the site
through a tunnel, so the VM accepts no connection from the internet. Cost: **USD 0 a month**.

```
browser ──HTTPS──> Cloudflare (ecofate.org: certificate, HSTS, www redirect)
                       │  outbound tunnel opened by the VM
                       ▼
              Oracle Cloud VM (Ampere A1, 4 OCPU / 24 GB, Ubuntu 24.04 arm64)
              ┌──────────────────────────────────────────────────────────┐
              │ cloudflared ─> api ──> db (PostgreSQL)    worker ──> redis│
              └──────────────────────────────────────────────────────────┘
   GitHub Actions (tag vX.Y.Z) ─builds arm64 images─> GHCR ─pulled by─> VM
   GitHub Actions ─SSH over the tunnel (Access service token)─> deploy.sh on the VM
   VM ─nightly pg_dump─> Oracle Object Storage (30 days)      traces ─> Logfire
```

| Piece | Where it lives |
|---|---|
| Provision / teardown / first login | `deploy/oci/provision.sh`, `teardown.sh`, `bastion-ssh.sh` (`make deploy-provision`, `deploy-teardown`, `deploy-ssh`) |
| Production compose overrides | `compose.prod.yaml` |
| Production settings (no secrets) | `config/settings.production.toml`, switched on by `ECOFATE_SETTINGS_PROFILE=production` |
| Secrets (only on the VM) | `/opt/ecofate/.env.prod`, `/opt/ecofate/tunnel.env` (templates: `deploy/*.example`) |
| Deploy | `.github/workflows/deploy.yml` → `deploy/deploy.sh` |
| Backups / restore | `deploy/backup.sh` + `ecofate-backup.timer`, `deploy/restore.sh` |

## Keeping it free

- Use only Always Free shapes: `provision.sh` refuses more than 4 OCPUs, 24 GB of memory or a
  200 GB disk before creating anything.
- Upgrade the tenancy to **Pay As You Go** (Billing & Cost Management → Upgrade and Manage
  Payment; add a payment method first). Within Always Free limits the bill stays at zero, and
  Oracle no longer reclaims Always Free VMs that sit idle for a week.
- Create a **budget alert at USD 1** (Billing & Cost Management → Cost Management → Budgets).
- Cloudflare's free plan covers the tunnel, Access (up to 50 users), DNS and the certificate.

## 1. Prerequisites (once)

1. **Oracle Cloud account** with your home region chosen carefully (it cannot change; Always
   Free resources exist only there). This deployment uses `us-chicago-1`.
2. **OCI CLI** on your machine: `brew install oci-cli`, then `oci setup config` (user OCID,
   tenancy OCID, home region; paste the printed public key under My profile → API keys). Check
   with `oci iam region list`.
3. **Cloudflare** zone for `ecofate.org` and Email Service sending enabled for it.
4. An SSH key for yourself (`~/.ssh/id_ed25519.pub`).

## 2. Provision the VM

```bash
cp deploy/oci/config.env.example deploy/oci/config.env
# fill in: OCI_TENANCY_OCID and OCI_COMPARTMENT_OCID (both the tenancy OCID),
# OCI_BASTION_CLIENT_CIDR = your public IP + /32  (curl -s https://checkip.amazonaws.com)
make deploy-provision
```

It creates the network (its only inbound rule is SSH from its own subnet, for the Bastion), the
VM, the Bastion (your /32 only), the private backup bucket and the permission that lets only the
VM create and read dumps. Running it again reuses what exists.

**"Out of host capacity"**: Ampere A1 capacity is often short. The script retries across the
three availability domains for about an hour (`OCI_CAPACITY_ATTEMPTS`); run it again later if
it gives up. If capacity never frees up, the same compose files run unchanged on a Hetzner
CAX21 (about EUR 7 a month).

## 3. Cloudflare Tunnel and Access

Cloudflare moves these menus often; the dashboard search (**Cmd/Ctrl + K**) finds each page by
the name in bold.

1. **Tunnels** (main dashboard: Networking → Tunnels; or Zero Trust → Networks → Connectors) →
   **Create a tunnel**, type *Cloudflared*, name `ecofate`. Pick any OS (Debian, arm64): only the
   token matters. Copy the value starting with `eyJ` from the "install as a service" command
   into your password manager (it goes into `tunnel.env` in step 4); run nothing. The page can
   be opened again later to show it.
2. The wizard cannot continue while no connector runs: leave it, open the tunnel, **Routes →
   Add route → Published application**, and add two (the URL includes the protocol):
   - subdomain empty, domain `ecofate.org`, URL `http://api:8000` (**http**, not https: the
     tunnel encrypts, the API speaks plain HTTP inside the VM; https gives a 502)
   - subdomain `ssh`, domain `ecofate.org`, URL `ssh://host.docker.internal:22`

   Each route needs its own hostname: a route saved with an empty subdomain takes over
   `ecofate.org`. Editing a route can also move its DNS record, so afterwards check **DNS →
   Records** shows both `ecofate.org` and `ssh` as proxied CNAMEs to `<tunnel-id>.cfargotunnel.com`
   (add a missing one by hand).
3. **Service Tokens** (Zero Trust → Access → Service credentials) → **Create Service Token**
   named `github-deploy`, non-expiring (or a year). Copy the Client ID and Client Secret (the
   secret is shown once) for the GitHub secrets in step 6.
4. **Applications** (Zero Trust → Access) → **Add an application → Self-hosted** (not
   *Infrastructure*, which needs the WARP client), name `ecofate-ssh`, hostname `ssh.ecofate.org`,
   with a policy whose action is **Service Auth** and whose rule is that service token. Optionally
   add a second policy (action *Allow*) for your own email, to SSH in through the browser login.
   The default session duration is fine (service-token requests re-authenticate every time).
   Never put an Access application on `ecofate.org` itself: the site is public.
5. **Check Access before going further**: from your machine, `ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ecofate@ssh.ecofate.org`
   must stop at a Cloudflare login (or be refused) unless you pass the service token or your
   email policy lets you in. sshd is reachable through the tunnel, so Access is what guards it.
6. Zone settings for `ecofate.org`: **SSL/TLS → Edge Certificates → Always Use HTTPS** on, **HSTS**
   on (max-age 6 months, include subdomains); **Rules → Redirect Rules**: `www.ecofate.org/*` →
   `https://ecofate.org/${1}` (301), with a proxied DNS record for `www`.

## 4. First login and the secret files

```bash
make deploy-ssh            # opens a one-hour Bastion session and logs you in as ecofate
```

A new Bastion session refuses its key for a few seconds; the script retries ("not ready yet;
retrying") and uses the next free local port if 2222 is taken. It fails only when your public
IP no longer matches `OCI_BASTION_CLIENT_CIDR`: update `config.env` and run
`make deploy-provision` (it updates the Bastion). Ignore Ubuntu's offer to upgrade to a newer
release; reboot when it says "System restart required" (`oci compute instance action --action
SOFTRESET`, or the console).

On the VM (`ecofate` user):

```bash
cd /opt/ecofate
cp app/deploy/env.prod.example .env.prod && chmod 600 .env.prod && nano .env.prod
cp app/deploy/tunnel.env.example tunnel.env && chmod 600 tunnel.env && nano tunnel.env
```

Fill every uncommented variable (the template says how to generate each); keep a copy in your
password manager. `deploy.sh` refuses to deploy while one is missing and names it without showing
values. Email: `SMTP_HOST=smtp.mx.cloudflare.net`, `SMTP_PORT=465`, `SMTP_SECURITY=tls`,
`SMTP_USERNAME=api_token`, `SMTP_PASSWORD=` a **new** Cloudflare API token (not the one you use
locally): permission *Account → Email Sending → Edit*, **Account Resources** the account that owns
`ecofate.org` (or all accounts), and **no client IP filter** (the VM's outbound address is
Oracle's and can change). A token scoped otherwise still logs in but every send fails with
`550 5.7.1 Not authorized to send from domain`. `SMTP_FROM=noreply@ecofate.org`, exactly the
sender verified in Cloudflare Email Service (a different address is refused the same way).
`ECOFATE_BACKUP_BUCKET` is the bucket name from `config.env`.

The nightly backup timer was installed at first boot (`systemctl list-timers ecofate-backup.timer`);
until `.env.prod` exists its runs fail visibly in `journalctl -u ecofate-backup.service`.

## 5. The deploy key

The deploy key lets GitHub run exactly one thing on the VM: `deploy.sh`.

```bash
ssh-keygen -t ed25519 -N '' -C github-deploy -f ./ecofate_deploy_key     # on your machine
```

On the VM, append one line to `~ecofate/.ssh/authorized_keys` (the public key after the options):

```
restrict,command="/opt/ecofate/app/deploy/deploy.sh" ssh-ed25519 AAAA... github-deploy
```

`restrict` turns off port, agent and X11 forwarding and the terminal; `command=` makes every
connection run `deploy.sh`, which accepts only `deploy vX.Y.Z` or `rollback vX.Y.Z`. Check that
`/etc/ssh/sshd_config` has no `PermitUserEnvironment yes` and no `AcceptEnv` for `ECOFATE_*`
(Ubuntu's default accepts only `LANG LC_*`).

For the pinned host key, print the VM's key: `cat /etc/ssh/ssh_host_ed25519_key.pub` and build
the line `ssh.ecofate.org ssh-ed25519 AAAA...` (host name, then the key type and key).

## 6. GitHub settings

- **Secrets** (Settings → Secrets and variables → Actions): `DEPLOY_SSH_KEY` (the private
  `ecofate_deploy_key`, then delete the local file), `DEPLOY_KNOWN_HOSTS` (the line above),
  `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`.
- **Variable**: `DEPLOY_SSH_HOST` = `ssh.ecofate.org`.
- **Environment** `production` (Settings → Environments): you as **required reviewer**, and
  deployment tags limited to `v*.*.*`. Every deploy then waits for your approval.
- After the first release, make the packages `ecofate-api` and `ecofate-worker` **public**
  (your profile → Packages → package settings), so the VM pulls them without a token.

## 7. First release

The tunnel starts with the stack, so the very first deploy runs by hand through the Bastion:

1. Bump the version (`pyproject.toml` and `CITATION.cff` together, `date-released`), merge, then
   `git tag v0.2.0 && git push origin v0.2.0`. The **images** jobs build and push to GHCR; the
   **deploy** job waits for your approval.
2. Make the two packages public (step 6), then on the VM: `/opt/ecofate/app/deploy/deploy.sh deploy v0.2.0`
   (first time only; it pulls the images, migrates, starts the stack and the tunnel, and checks
   `https://ecofate.org/api/health`).
3. Approve the waiting deploy job: it redeploys the same tag over the tunnel, which proves the
   automatic path works.
4. Create the first administrator on the VM (it asks for the password, hidden; an existing
   account with that email is promoted instead):
   `docker exec -it ecofate-api-1 python -m api create-admin --email you@example.com`

Every later release is only: bump the version, tag, push, approve.

## Rollback

A deploy whose health check fails redeploys the previous release by itself. To go back to any
earlier release on purpose: **Actions → Deploy → Run workflow**, `rollback_tag` = `vX.Y.Z`
(its images must still be in GHCR). Database migrations only add to the schema within a release
(expand, then contract in a later release), so an older release runs on the migrated schema.

**Rollback drill**: 2026-11-18, tag `v0.2.1` (a deliberately wrong `public_origin`, never merged)
failed its health check; the job redeployed v0.2.0 by itself and the site answered 200 again.
The red deploy job is the expected result. `v0.2.1` stays as the record; never deploy it.

## Logs

On the VM (compose needs the running release's tag, which `deploy.sh` records in
`/opt/ecofate/RELEASE`):

```bash
alias dc='ECOFATE_TAG=$(cat /opt/ecofate/RELEASE) docker compose --env-file /opt/ecofate/.env.prod -f /opt/ecofate/app/compose.yaml -f /opt/ecofate/app/compose.prod.yaml --project-directory /opt/ecofate/app'
dc ps                      # state and health of every service
dc logs --tail 200 api     # or worker, cloudflared, db
journalctl -u ecofate-backup.service --since today
```

Container logs rotate (10 MB × 5 per service). Agent traces go to Logfire when `LOGFIRE_TOKEN`
is set (administrators see them in the Monitoring view).

## Backups and restore

- Every night at about 03:15 UTC the timer dumps the database to `pg/<UTC timestamp>.dump` in
  the bucket; dumps are deleted after 30 days. The VM can create and read dumps but not delete
  or overwrite them. Run one now with `make deploy-backup` (on the VM, in `/opt/ecofate/app`).
- Restore: `make deploy-restore DUMP=20261118T031500Z`. It restores into a new database, shows the
  row counts, and switches only after you type `switch`, in one transaction; the previous
  database is kept as `<name>_before_<timestamp>` until you drop it.

**Restore drill**: 2026-11-18, v0.2.0, dump `pg/20261118T185624Z.dump`, 40,113 bytes (1 user,
1 thread, 1 turn); backup 3 s, restore into `ecofate_restore_20261118t185624z` 4 s, row counts
matched, live database untouched, drill database dropped afterwards. Repeat after big data
changes; the times grow with the dump.

## Teardown

```bash
make deploy-teardown       # type the bucket name to confirm; deletes the VM, data and backups
```

Then delete the tunnel, the Access application and service token, and the `ecofate.org` /
`ssh.ecofate.org` / `www` records in Cloudflare.

## Security notes

- Nothing on the VM is reachable from the internet; the Bastion admits only your /32 and the
  tunnel only Cloudflare. Legacy instance metadata (IMDSv1) is disabled.
- The `ecofate` user is in the `docker` group, which is root-equivalent on the VM: protect your
  SSH key and the deploy key accordingly.
- Secrets exist only in the two files on the VM (mode 600) and your password manager; the
  tunnel token is read by `cloudflared` alone.
- `trusted_proxy_hops = 1` (production settings) is confirmed at the first deploy by checking
  that two visitors' sign-in throttles are counted separately.

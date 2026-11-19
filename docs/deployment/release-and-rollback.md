[← Documentation index](../../README.md#documentation) · [Deployment](README.md)

# First release and rollback

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

Next: [Logs, backups and restore](logs-backups-restore.md)

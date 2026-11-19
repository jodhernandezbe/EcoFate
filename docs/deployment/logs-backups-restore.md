[← Documentation index](../../README.md#documentation) · [Deployment](README.md)

# Logs, backups and restore

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

Next: [Teardown and security notes](teardown-and-security.md)

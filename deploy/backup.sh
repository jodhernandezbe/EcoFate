#!/usr/bin/env bash
# Nightly database backup on the VM (docs/deployment.md, "Backups"), run by ecofate-backup.timer.
# Dumps the whole database (pg_dump custom format) inside the `db` container, checks the dump is
# readable, uploads it to Object Storage as pg/<UTC timestamp>.dump with the VM's own identity
# (instance principal; it may create and read dumps, never overwrite or delete them), and removes
# the local copy. Any failure exits non-zero, so systemd records the run as failed.
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
source "${HERE}/lib.sh"

main() {
  local bucket name dump
  bucket="$(ecofate_env_value ECOFATE_BACKUP_BUCKET)"
  [[ "${bucket}" =~ ^[a-z0-9][a-z0-9-]{1,62}$ ]] || { echo "backup: set ECOFATE_BACKUP_BUCKET in ${ECOFATE_ENV_FILE}" >&2; exit 1; }
  name="pg/$(date -u +%Y%m%dT%H%M%SZ).dump"
  dump="$(mktemp)"
  trap 'rm -f "${dump}"' EXIT
  # The credentials stay inside the container: pg_dump reads them from its own environment.
  # shellcheck disable=SC2016  # expanded by the container's shell, on purpose
  ecofate_compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "${dump}"
  [[ -s "${dump}" ]] || { echo "backup: the dump is empty" >&2; exit 1; }
  ecofate_compose exec -T db pg_restore --list < "${dump}" > /dev/null || { echo "backup: the dump is not readable" >&2; exit 1; }
  ecofate_oci os object put --bucket-name "${bucket}" --name "${name}" --file "${dump}" --no-overwrite > /dev/null
  echo "backup: uploaded ${name} ($(stat -c %s "${dump}") bytes)"
}

main "$@"

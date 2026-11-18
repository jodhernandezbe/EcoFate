#!/usr/bin/env bash
# Restore a nightly dump on the VM (docs/deployment.md, "Restore").
#
# Usage: deploy/restore.sh <UTC timestamp, e.g. 20261118T031500Z>
#
# Downloads pg/<timestamp>.dump, restores it into a NEW database (the live one is untouched),
# prints the row counts of the core tables and asks you to type "switch". Only then it stops the
# API and worker, renames the live database to <name>_before_<timestamp> (kept, never dropped
# here), gives the restored one the live name, and starts the API and worker again.
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
source "${HERE}/lib.sh"

die() { echo "restore: $*" >&2; exit 1; }

# psql inside the db container as the database owner; extra arguments are passed through.
db_psql() {
  # shellcheck disable=SC2016  # expanded by the container's shell, on purpose
  ecofate_compose exec -T db sh -c 'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$@"' psql "$@"
}

restore_into() {
  local database="$1" dump="$2"
  # psql expands :"name" only in input it reads, not in -c commands.
  echo 'CREATE DATABASE :"name";' | db_psql -d postgres -v name="${database}"
  # shellcheck disable=SC2016  # expanded by the container's shell, on purpose
  ecofate_compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --exit-on-error' \
    pg_restore "${database}" < "${dump}"
}

show_counts() {
  echo "Row counts in the restored database ${1}:"
  db_psql -d "${1}" -A -F ' ' -c \
    "SELECT 'users', count(*) FROM users UNION ALL SELECT 'threads', count(*) FROM threads UNION ALL SELECT 'turns', count(*) FROM turns"  < /dev/null
}

switch_to() {
  local restored="$1" stamp="$2" live kept
  live="$(ecofate_env_value POSTGRES_DB)"
  # PostgreSQL names are at most 63 characters: keep room for the suffix (24).
  kept="${live:0:39}_before_${stamp,,}"
  echo "==> stopping api and worker"
  ecofate_compose stop api worker
  # One transaction: if either rename fails, neither happens and the live database stays live.
  if ! db_psql -d postgres --single-transaction -v live="${live}" -v kept="${kept}" -v restored="${restored}" <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'live' AND pid <> pg_backend_pid();
ALTER DATABASE :"live" RENAME TO :"kept";
ALTER DATABASE :"restored" RENAME TO :"live";
SQL
  then
    ecofate_compose up -d api worker
    die "the switch failed; the live database is unchanged and the app is running again"
  fi
  echo "==> starting api and worker on the restored data"
  ecofate_compose up -d --wait api worker
  echo "Restored. The previous database is kept as ${kept}; drop it once you are satisfied:"
  echo "  docker compose ... exec db dropdb -U <user> ${kept}"
}

main() {
  local stamp="${1:-}" bucket dump restored answer
  stamp="${stamp#pg/}"
  stamp="${stamp%.dump}"
  [[ "${stamp}" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "usage: restore.sh <UTC timestamp like 20261118T031500Z>"
  bucket="$(ecofate_env_value ECOFATE_BACKUP_BUCKET)"
  [[ "${bucket}" =~ ^[a-z0-9][a-z0-9-]{1,62}$ ]] || die "set ECOFATE_BACKUP_BUCKET in ${ECOFATE_ENV_FILE}"
  dump="$(mktemp)"
  # The path is expanded now: $dump is local to main and gone when the EXIT trap runs.
  # shellcheck disable=SC2064
  trap "rm -f $(printf '%q' "${dump}")" EXIT
  ecofate_oci os object get --bucket-name "${bucket}" --name "pg/${stamp}.dump" --file "${dump}" > /dev/null
  restored="ecofate_restore_${stamp,,}"
  echo "==> restoring pg/${stamp}.dump into ${restored}"
  restore_into "${restored}" "${dump}"
  show_counts "${restored}"
  read -r -p "Type 'switch' to make it the live database (anything else keeps the live one): " answer || answer=""
  [[ "${answer}" == "switch" ]] || { echo "Not switched. ${restored} is left in place for inspection."; exit 0; }
  switch_to "${restored}" "${stamp}"
}

main "$@"

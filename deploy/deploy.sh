#!/usr/bin/env bash
# Deploy one EcoFate release on the VM (docs/deployment/release-and-rollback.md, "Releasing").
#
# Installed as the forced command of the deploy key in ~ecofate/.ssh/authorized_keys, so that key
# can run nothing else. The requested action arrives in SSH_ORIGINAL_COMMAND (or as arguments
# when the operator runs it by hand) and must be exactly `deploy vX.Y.Z` or `rollback vX.Y.Z`.
#
# Steps: check the secret files and every required variable (names only, never values), move the
# checkout to the tag, pull the tagged images, start the stack (migrations run first; api and
# worker start only if they succeed), then check https://<public origin>/api/health. If the new
# release never reports healthy, the previous release is deployed again and this exits non-zero.
set -euo pipefail
umask 077

# Run from a private copy: the checkout this file lives in is moved to the new tag below, and bash
# reads a script as it runs, so editing it underneath would execute whatever the new version holds.
# The copy learns where it came from through its arguments, never the environment (a forced-command
# SSH key cannot add arguments).
if [[ "${1:-}" != "--from-copy" ]]; then
  copy="$(mktemp)"
  cp "${BASH_SOURCE[0]}" "${copy}"
  exec bash "${copy}" --from-copy "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" "$@"
fi
DEPLOY_DIR="$2"
shift 2
# Remove the private copy on exit, and only a temporary file (never the checkout's own script).
SELF="${BASH_SOURCE[0]}"
[[ "${SELF}" == "${TMPDIR:-/tmp}"/tmp.* ]] && trap 'rm -f "${SELF}"' EXIT

# Paths and the compose invocation, read now: the checkout moves to another tag further down.
# shellcheck source=deploy/lib.sh
source "${DEPLOY_DIR}/lib.sh"
ROOT="${ECOFATE_ROOT}"
APP="${ECOFATE_APP}"
ENV_FILE="${ECOFATE_ENV_FILE}"
TUNNEL_FILE="${ECOFATE_TUNNEL_FILE}"
RELEASE="${ECOFATE_RELEASE_FILE}"
TAG_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'
HEALTH_TRIES=10
HEALTH_PAUSE_SECONDS=6
UP_WAIT_SECONDS=300

die() { echo "deploy: $*" >&2; exit 1; }
say() { echo "==> $*"; }

parse_request() {
  local request="${SSH_ORIGINAL_COMMAND:-$*}" action tag extra
  read -r action tag extra <<< "${request}"
  [[ -z "${extra:-}" ]] || die "expected 'deploy vX.Y.Z' or 'rollback vX.Y.Z'"
  [[ "${action:-}" == "deploy" || "${action:-}" == "rollback" ]] || die "expected 'deploy vX.Y.Z' or 'rollback vX.Y.Z'"
  [[ "${tag:-}" =~ ${TAG_PATTERN} ]] || die "not a release tag: ${tag:-<none>}"
  TAG="${tag}"
}

# A secret file must exist, belong to the service user and be readable by it alone.
check_private_file() {
  local file="$1"
  [[ -f "${file}" ]] || die "missing ${file} (template in deploy/)"
  [[ "$(stat -c '%a %U' "${file}")" == "600 $(id -un)" ]] || die "${file} must be mode 600 and owned by $(id -un)"
}

# Every uncommented NAME= line of the template must be set to a non-empty value in the file.
check_required() {
  local template="$1" file="$2" name missing=()
  while IFS= read -r name; do
    grep -Eq "^${name}=.+" "${file}" || missing+=("${name}")
  done < <(sed -nE 's/^([A-Z][A-Z0-9_]*)=.*/\1/p' "${template}")
  (( ${#missing[@]} == 0 )) || die "missing or empty in ${file}: ${missing[*]}"
}

checkout() {
  git -C "${APP}" fetch --quiet --tags --force origin
  git -C "${APP}" rev-parse --verify --quiet "refs/tags/${1}" >/dev/null || die "no tag ${1} in the repository"
  git -C "${APP}" checkout --quiet --detach "refs/tags/${1}"
}

compose() {
  ECOFATE_TAG="${CURRENT}" ecofate_compose "$@"
}

public_health_ok() {
  local origin try
  origin="$(compose exec -T api python -c 'from config.ui import get_ui_settings; print(get_ui_settings().origin)')"
  [[ "${origin}" =~ ^https://[a-z0-9.-]+$ ]] || { echo "deploy: unexpected public origin" >&2; return 1; }
  for (( try = 1; try <= HEALTH_TRIES; try++ )); do
    curl --fail --silent --show-error --max-time 10 "${origin}/api/health" >/dev/null && return 0
    sleep "${HEALTH_PAUSE_SECONDS}"
  done
  return 1
}

# Start release $1; succeeds only when the stack is up and the public health check passes.
start_release() {
  CURRENT="$1"
  checkout "${CURRENT}"
  check_required "${APP}/deploy/env.prod.example" "${ENV_FILE}"
  check_required "${APP}/deploy/tunnel.env.example" "${TUNNEL_FILE}"
  say "pulling ${CURRENT}"
  compose pull --quiet
  say "starting ${CURRENT} (migrations first)"
  compose up -d --remove-orphans --wait --wait-timeout "${UP_WAIT_SECONDS}" && public_health_ok
}

main() {
  parse_request "$@"
  check_private_file "${ENV_FILE}"
  check_private_file "${TUNNEL_FILE}"
  exec 9>"${ROOT}/.deploy.lock"
  flock -n 9 || die "another deploy is running"
  local previous=""
  [[ -f "${RELEASE}" ]] && previous="$(cat "${RELEASE}")"
  if start_release "${TAG}"; then
    [[ "${previous}" == "${TAG}" ]] || echo "${previous}" > "${RELEASE}.prev"
    echo "${TAG}" > "${RELEASE}"
    say "${TAG} is live"
    return 0
  fi
  echo "deploy: ${TAG} did not become healthy" >&2
  if [[ "${previous}" =~ ${TAG_PATTERN} && "${previous}" != "${TAG}" ]]; then
    say "rolling back to ${previous}"
    start_release "${previous}" || die "rollback to ${previous} also failed; see docker compose logs"
    say "${previous} is live again"
  fi
  exit 1
}

main "$@"

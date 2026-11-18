#!/usr/bin/env bash
# Shared by deploy.sh, backup.sh and restore.sh on the VM: paths and the one way to run compose.
# Sourced, never run. Callers set ECOFATE_TAG (deploy.sh) or use the running release (RELEASE).
# shellcheck disable=SC2034  # the paths are used by the scripts that source this file

ECOFATE_ROOT="/opt/ecofate"
ECOFATE_APP="${ECOFATE_ROOT}/app"
ECOFATE_ENV_FILE="${ECOFATE_ROOT}/.env.prod"
ECOFATE_TUNNEL_FILE="${ECOFATE_ROOT}/tunnel.env"
ECOFATE_RELEASE_FILE="${ECOFATE_ROOT}/RELEASE"

# docker compose for the production stack at release ECOFATE_TAG (default: the running release).
ecofate_compose() {
  local tag="${ECOFATE_TAG:-}"
  [[ -n "${tag}" ]] || tag="$(cat "${ECOFATE_RELEASE_FILE}" 2>/dev/null || true)"
  [[ -n "${tag}" ]] || { echo "no release recorded in ${ECOFATE_RELEASE_FILE}" >&2; return 1; }
  ECOFATE_TAG="${tag}" docker compose --env-file "${ECOFATE_ENV_FILE}" \
    -f "${ECOFATE_APP}/compose.yaml" -f "${ECOFATE_APP}/compose.prod.yaml" \
    --project-directory "${ECOFATE_APP}" "$@"
}

# The value of NAME in the environment file, without printing it anywhere else.
ecofate_env_value() {
  sed -nE "s/^${1}=(.*)$/\\1/p" "${ECOFATE_ENV_FILE}" | tail -n 1
}

# The OCI CLI as the VM itself (instance principal: no keys on disk).
ecofate_oci() {
  "${HOME}/.local/bin/oci" --auth instance_principal "$@"
}

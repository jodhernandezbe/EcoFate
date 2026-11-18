#!/usr/bin/env bash
# SSH into the EcoFate VM as `ecofate` through the OCI Bastion (docs/deployment.md, "First login"):
# opens a one-hour port-forwarding session to the VM's private address, forwards a local port
# through it, and logs in with the operator key from config.env. Needed before the Cloudflare
# tunnel exists (to write /opt/ecofate/.env.prod and tunnel.env) and in an emergency.
#
# Usage: deploy/oci/bastion-ssh.sh            (reads deploy/oci/config.env)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="ecofate"
LOCAL_PORT="${LOCAL_PORT:-2222}"
SESSION_SECONDS=3600

die() { echo "bastion-ssh: $*" >&2; exit 1; }

[[ -f "${HERE}/config.env" ]] || die "missing ${HERE}/config.env (see config.env.example)"
# shellcheck source=/dev/null
source "${HERE}/config.env"
PUBLIC_KEY="${OCI_SSH_PUBLIC_KEY_FILE/#\~/${HOME}}"
PRIVATE_KEY="${PUBLIC_KEY%.pub}"
[[ -f "${PUBLIC_KEY}" && -f "${PRIVATE_KEY}" ]] || die "need both ${PRIVATE_KEY} and ${PUBLIC_KEY}"
[[ "${LOCAL_PORT}" =~ ^[0-9]{4,5}$ ]] || die "LOCAL_PORT must be a port number"
# Another session (or anything else) may already listen there: never reuse a busy port, or the
# login below would go to whatever answers on it.
for _ in $(seq 1 50); do
  nc -z 127.0.0.1 "${LOCAL_PORT}" 2>/dev/null || break
  LOCAL_PORT=$(( LOCAL_PORT + 1 ))
done
nc -z 127.0.0.1 "${LOCAL_PORT}" 2>/dev/null && die "no free local port found near ${LOCAL_PORT}"

instance="$(oci compute instance list --compartment-id "${OCI_COMPARTMENT_OCID}" --all \
  --query "data[?\"display-name\"=='${NAME}-vm' && \"lifecycle-state\"=='RUNNING'].id | [0]" --raw-output)"
[[ -n "${instance}" && "${instance}" != "null" ]] || die "no running ${NAME}-vm (run provision.sh)"
private_ip="$(oci compute instance list-vnics --instance-id "${instance}" --query 'data[0]."private-ip"' --raw-output)"
bastion="$(oci bastion bastion list --compartment-id "${OCI_COMPARTMENT_OCID}" --all \
  --query "data[?name=='${NAME}bastion' && \"lifecycle-state\"=='ACTIVE'].id | [0]" --raw-output)"
[[ -n "${bastion}" && "${bastion}" != "null" ]] || die "no active ${NAME}bastion (run provision.sh)"
region="$(oci iam region-subscription list --tenancy-id "${OCI_TENANCY_OCID}" \
  --query 'data[?"is-home-region"].["region-name"] | [0][0]' --raw-output)"

echo "==> opening a ${SESSION_SECONDS}s bastion session to ${private_ip}"
session="$(oci bastion session create-port-forwarding --bastion-id "${bastion}" \
  --target-resource-id "${instance}" --target-private-ip "${private_ip}" --target-port 22 \
  --ssh-public-key-file "${PUBLIC_KEY}" --session-ttl "${SESSION_SECONDS}" \
  --display-name "${NAME}-$(date -u +%Y%m%dT%H%M%SZ)" \
  --wait-for-state SUCCEEDED --query 'data.resources[0].identifier' --raw-output)"

# Runs in the background, so it must never stop at a host-key question: Oracle's bastion host
# key is recorded on first use (the VM's own key is still checked on the login below).
start_forward() {
  ssh -i "${PRIVATE_KEY}" -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
    -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=15 \
    -L "${LOCAL_PORT}:${private_ip}:22" -p 22 "${session}@host.bastion.${region}.oci.oraclecloud.com" &
  forward=$!
}
forward=""
trap '[[ -n "${forward}" ]] && kill "${forward}" 2>/dev/null || true' EXIT

# A new session refuses its key ("Permission denied (publickey)") for a few seconds after it is
# created: retry the forward for up to about two minutes until the local port answers. The port
# counts only while our own forward is alive (another local process could be listening on it).
for _ in $(seq 1 12); do
  start_forward
  for _ in $(seq 1 10); do
    kill -0 "${forward}" 2>/dev/null && nc -z 127.0.0.1 "${LOCAL_PORT}" 2>/dev/null && break 2
    kill -0 "${forward}" 2>/dev/null || break
    sleep 1
  done
  kill "${forward}" 2>/dev/null || true
  echo "==> the bastion session is not ready yet; retrying"
  sleep 5
done
kill -0 "${forward}" 2>/dev/null && nc -z 127.0.0.1 "${LOCAL_PORT}" 2>/dev/null \
  || die "the bastion forward did not open (is ${OCI_BASTION_CLIENT_CIDR} still your IP?)"

# Extra arguments run as a command on the VM instead of an interactive shell.
ssh -i "${PRIVATE_KEY}" -p "${LOCAL_PORT}" -o HostKeyAlias="${NAME}-vm" -o StrictHostKeyChecking=accept-new \
  ecofate@127.0.0.1 "$@"

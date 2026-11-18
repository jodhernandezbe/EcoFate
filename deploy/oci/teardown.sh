#!/usr/bin/env bash
# Delete everything deploy/oci/provision.sh created (docs/deployment.md, "Teardown"): the VM and
# its boot volume, the Bastion, the backup policy and dynamic group, the backup bucket with every
# dump in it, and the network. Irreversible: the database on the VM and all its backups are gone.
# Asks you to type the bucket name first; nothing is deleted if it does not match.
#
# Usage: deploy/oci/teardown.sh            (reads deploy/oci/config.env)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="ecofate"

die() { echo "teardown: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[[ -f "${HERE}/config.env" ]] || die "missing ${HERE}/config.env (see config.env.example)"
# shellcheck source=/dev/null
source "${HERE}/config.env"
command -v oci >/dev/null || die "install the OCI CLI first"

confirm() {
  echo "This deletes the EcoFate VM, its database, every backup in '${OCI_BACKUP_BUCKET}', the Bastion"
  echo "and the network. It cannot be undone."
  read -r -p "Type the bucket name to confirm: " typed
  [[ "${typed}" == "${OCI_BACKUP_BUCKET}" ]] || die "name did not match; nothing was deleted"
}

# The OCID of the live resource called "$2" listed by `oci $1 list ...`, or nothing.
find_id() {
  local listing="$1" name="$2"
  shift 2
  # shellcheck disable=SC2086  # $listing is a fixed "group command" pair, split on purpose
  oci ${listing} list --compartment-id "${OCI_COMPARTMENT_OCID}" --all "$@" \
    --query "data[?\"display-name\"=='${name}' && \"lifecycle-state\"!='TERMINATED' && \"lifecycle-state\"!='TERMINATING'].id | [0]" \
    --raw-output 2>/dev/null | grep -v '^null$' || true
}

by_name() {  # OCID of the IAM resource ($1: dynamic-group | policy) called $2, or nothing
  oci iam "$1" list --compartment-id "${OCI_TENANCY_OCID}" --all \
    --query "data[?name=='$2'].id | [0]" --raw-output 2>/dev/null | grep -v '^null$' || true
}

delete_compute_and_access() {
  local id
  id="$(find_id "compute instance" "${NAME}-vm")"
  [[ -z "${id}" ]] || { say "terminating VM ${id}"; oci compute instance terminate --instance-id "${id}" \
    --preserve-boot-volume false --force --wait-for-state TERMINATED >/dev/null; }
  id="$(oci bastion bastion list --compartment-id "${OCI_COMPARTMENT_OCID}" --all \
    --query "data[?name=='${NAME}bastion' && \"lifecycle-state\"!='DELETED'].id | [0]" --raw-output 2>/dev/null | grep -v '^null$' || true)"
  [[ -z "${id}" ]] || { say "deleting bastion ${id}"; oci bastion bastion delete --bastion-id "${id}" --force \
    --wait-for-state SUCCEEDED >/dev/null; }
  id="$(by_name policy "${NAME}-backups")"
  [[ -z "${id}" ]] || { say "deleting policy"; oci iam policy delete --policy-id "${id}" --force >/dev/null; }
  id="$(by_name dynamic-group "${NAME}-vm")"
  [[ -z "${id}" ]] || { say "deleting dynamic group"; oci iam dynamic-group delete --dynamic-group-id "${id}" --force >/dev/null; }
}

delete_bucket() {
  local namespace
  namespace="$(oci os ns get --query data --raw-output)"
  if oci os bucket get --bucket-name "${OCI_BACKUP_BUCKET}" --namespace-name "${namespace}" >/dev/null 2>&1; then
    say "deleting bucket ${OCI_BACKUP_BUCKET} and its dumps"
    oci os bucket delete --bucket-name "${OCI_BACKUP_BUCKET}" --namespace-name "${namespace}" --empty --force >/dev/null
  fi
}

delete_network() {
  local vcn id
  vcn="$(find_id "network vcn" "${NAME}-vcn")"
  [[ -n "${vcn}" ]] || return 0
  id="$(find_id "network subnet" "${NAME}-subnet" --vcn-id "${vcn}")"
  [[ -z "${id}" ]] || oci network subnet delete --subnet-id "${id}" --force --wait-for-state TERMINATED >/dev/null
  id="$(find_id "network security-list" "${NAME}-no-public-inbound" --vcn-id "${vcn}")"
  [[ -z "${id}" ]] || oci network security-list delete --security-list-id "${id}" --force --wait-for-state TERMINATED >/dev/null
  id="$(find_id "network route-table" "${NAME}-rt" --vcn-id "${vcn}")"
  [[ -z "${id}" ]] || oci network route-table delete --rt-id "${id}" --force --wait-for-state TERMINATED >/dev/null
  id="$(find_id "network internet-gateway" "${NAME}-igw" --vcn-id "${vcn}")"
  [[ -z "${id}" ]] || oci network internet-gateway delete --ig-id "${id}" --force --wait-for-state TERMINATED >/dev/null
  say "deleting VCN ${vcn}"
  oci network vcn delete --vcn-id "${vcn}" --force --wait-for-state TERMINATED >/dev/null
}

confirm
delete_compute_and_access
delete_bucket
delete_network
say "done. Also delete the tunnel and the DNS records in Cloudflare (docs/deployment.md)."

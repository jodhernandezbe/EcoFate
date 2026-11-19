#!/usr/bin/env bash
# Create EcoFate's Oracle Cloud Always Free resources (docs/deployment/prerequisites-and-provision.md, "Provision"):
# a VCN whose security list allows no inbound traffic from the internet (only SSH from inside its
# own subnet, where the OCI Bastion's endpoint sits), one Ampere A1 Flex VM (Ubuntu 24.04 aarch64)
# started with cloud-init.yaml, an OCI Bastion that accepts only the operator's IP, a private
# Object Storage bucket for the nightly dumps (deleted after 30 days), and a dynamic group +
# policy that let only that VM write to it.
#
# Idempotent: each resource is looked up by its display name first and reused when it exists.
# Refuses any shape larger than the Always Free limits before creating anything.
#
# Usage: deploy/oci/provision.sh            (reads deploy/oci/config.env)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${HERE}/config.env"
NAME="ecofate"
SHAPE="VM.Standard.A1.Flex"
SUBNET_CIDR="10.0.0.0/24"
FREE_OCPUS=4
FREE_MEMORY_GB=24
FREE_BLOCK_GB=200

die() { echo "provision: $*" >&2; exit 1; }
say() { echo "==> $*"; }

load_config() {
  [[ -f "${CONFIG}" ]] || die "copy ${HERE}/config.env.example to ${CONFIG} and fill it in"
  # shellcheck source=/dev/null
  source "${CONFIG}"
  local var
  for var in OCI_COMPARTMENT_OCID OCI_TENANCY_OCID OCI_OCPUS OCI_MEMORY_GB OCI_BOOT_VOLUME_GB \
    OCI_SSH_PUBLIC_KEY_FILE OCI_BASTION_CLIENT_CIDR OCI_BACKUP_BUCKET OCI_CAPACITY_RETRY_SECONDS OCI_CAPACITY_ATTEMPTS; do
    [[ -n "${!var:-}" ]] || die "${var} is empty in ${CONFIG}"
  done
  OCI_SSH_PUBLIC_KEY_FILE="${OCI_SSH_PUBLIC_KEY_FILE/#\~/${HOME}}"
  [[ -f "${OCI_SSH_PUBLIC_KEY_FILE}" ]] || die "no public key at ${OCI_SSH_PUBLIC_KEY_FILE}"
  [[ "${OCI_BASTION_CLIENT_CIDR}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ ]] || die "OCI_BASTION_CLIENT_CIDR must be one IPv4 address as /32"
  [[ "${OCI_BACKUP_BUCKET}" =~ ^[a-z0-9][a-z0-9-]{1,62}$ ]] || die "OCI_BACKUP_BUCKET: lowercase letters, digits and dashes"
}

check_free_limits() {
  local n
  for n in OCI_OCPUS OCI_MEMORY_GB OCI_BOOT_VOLUME_GB; do
    [[ "${!n}" =~ ^[0-9]+$ ]] || die "${n} must be a whole number"
  done
  (( OCI_OCPUS >= 1 && OCI_OCPUS <= FREE_OCPUS )) || die "OCI_OCPUS must be 1-${FREE_OCPUS} (Always Free limit)"
  (( OCI_MEMORY_GB >= 6 && OCI_MEMORY_GB <= FREE_MEMORY_GB )) || die "OCI_MEMORY_GB must be 6-${FREE_MEMORY_GB} (Always Free limit; each worker slot needs about 2 GB, plus the database and services)"
  (( OCI_BOOT_VOLUME_GB >= 50 && OCI_BOOT_VOLUME_GB <= FREE_BLOCK_GB )) || die "OCI_BOOT_VOLUME_GB must be 50-${FREE_BLOCK_GB} (Always Free block storage)"
}

# The OCID of the first resource called "$2" listed by `oci $1 list ...`, or nothing.
find_id() {
  local listing="$1" name="$2"
  shift 2
  # shellcheck disable=SC2086  # $listing is a fixed "group command" pair, split on purpose
  oci ${listing} list --compartment-id "${OCI_COMPARTMENT_OCID}" --all "$@" \
    --query "data[?\"display-name\"=='${name}' && \"lifecycle-state\"!='TERMINATED' && \"lifecycle-state\"!='TERMINATING'].id | [0]" \
    --raw-output 2>/dev/null | grep -v '^null$' || true
}

ensure_vcn() {
  VCN_ID="$(find_id "network vcn" "${NAME}-vcn")"
  if [[ -z "${VCN_ID}" ]]; then
    VCN_ID="$(oci network vcn create --compartment-id "${OCI_COMPARTMENT_OCID}" --display-name "${NAME}-vcn" \
      --cidr-blocks '["10.0.0.0/16"]' --dns-label "${NAME}" --wait-for-state AVAILABLE --query data.id --raw-output)"
  fi
  say "VCN ${VCN_ID}"
}

ensure_gateway_and_routes() {
  IGW_ID="$(find_id "network internet-gateway" "${NAME}-igw" --vcn-id "${VCN_ID}")"
  if [[ -z "${IGW_ID}" ]]; then
    IGW_ID="$(oci network internet-gateway create --compartment-id "${OCI_COMPARTMENT_OCID}" --vcn-id "${VCN_ID}" \
      --display-name "${NAME}-igw" --is-enabled true --wait-for-state AVAILABLE --query data.id --raw-output)"
  fi
  RT_ID="$(find_id "network route-table" "${NAME}-rt" --vcn-id "${VCN_ID}")"
  if [[ -z "${RT_ID}" ]]; then
    RT_ID="$(oci network route-table create --compartment-id "${OCI_COMPARTMENT_OCID}" --vcn-id "${VCN_ID}" \
      --display-name "${NAME}-rt" --wait-for-state AVAILABLE --query data.id --raw-output \
      --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"${IGW_ID}\"}]")"
  fi
  say "outbound route through ${IGW_ID}"
}

# Egress anywhere (images, EPA and OpenAI APIs, the Cloudflare tunnel). Ingress: only SSH from
# inside the subnet (the Bastion's private endpoint), never from the internet. Re-applied on every
# run, so a rule added by hand in the console is removed again.
ensure_security_list() {
  local egress ingress
  egress='[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]'
  ingress="[{\"source\":\"${SUBNET_CIDR}\",\"protocol\":\"6\",\"isStateless\":false,\"tcpOptions\":{\"destinationPortRange\":{\"min\":22,\"max\":22}}}]"
  SL_ID="$(find_id "network security-list" "${NAME}-no-public-inbound" --vcn-id "${VCN_ID}")"
  if [[ -z "${SL_ID}" ]]; then
    SL_ID="$(oci network security-list create --compartment-id "${OCI_COMPARTMENT_OCID}" --vcn-id "${VCN_ID}" \
      --display-name "${NAME}-no-public-inbound" --ingress-security-rules "${ingress}" \
      --egress-security-rules "${egress}" --wait-for-state AVAILABLE --query data.id --raw-output)"
  else
    oci network security-list update --security-list-id "${SL_ID}" --ingress-security-rules "${ingress}" \
      --egress-security-rules "${egress}" --force --wait-for-state AVAILABLE >/dev/null
  fi
  say "security list ${SL_ID} (inbound: SSH from ${SUBNET_CIDR} only)"
}

# Oracle gives every VCN a default security list that admits SSH from anywhere. No subnet here
# uses it, but a subnet created later in the console would: keep it empty (no inbound, no outbound).
close_default_security_list() {
  local default_id
  default_id="$(oci network vcn get --vcn-id "${VCN_ID}" --query 'data."default-security-list-id"' --raw-output)"
  oci network security-list update --security-list-id "${default_id}" --ingress-security-rules '[]' \
    --egress-security-rules '[]' --force --wait-for-state AVAILABLE >/dev/null
  say "default security list ${default_id} emptied (unused)"
}

ensure_subnet() {
  SUBNET_ID="$(find_id "network subnet" "${NAME}-subnet" --vcn-id "${VCN_ID}")"
  if [[ -z "${SUBNET_ID}" ]]; then
    SUBNET_ID="$(oci network subnet create --compartment-id "${OCI_COMPARTMENT_OCID}" --vcn-id "${VCN_ID}" \
      --display-name "${NAME}-subnet" --cidr-block "${SUBNET_CIDR}" --dns-label app \
      --route-table-id "${RT_ID}" --security-list-ids "[\"${SL_ID}\"]" \
      --wait-for-state AVAILABLE --query data.id --raw-output)"
  fi
  say "subnet ${SUBNET_ID}"
}

latest_ubuntu_image() {
  oci compute image list --compartment-id "${OCI_COMPARTMENT_OCID}" --all \
    --operating-system "Canonical Ubuntu" --operating-system-version "24.04" --shape "${SHAPE}" \
    --sort-by TIMECREATED --sort-order DESC --query "data[0].id" --raw-output
}

user_data_file() {
  local key out
  # Only the key type and data: the comment never reaches the YAML.
  key="$(head -n 1 "${OCI_SSH_PUBLIC_KEY_FILE}" | awk '{ print $1 " " $2 }')"
  [[ "${key}" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9-]+)\ [A-Za-z0-9+/=]+$ ]] || die "not an SSH public key: ${OCI_SSH_PUBLIC_KEY_FILE}"
  out="$(mktemp)"
  KEY="${key}" awk '{ gsub("__OPERATOR_SSH_PUBLIC_KEY__", ENVIRON["KEY"]); print }' "${HERE}/cloud-init.yaml" > "${out}"
  echo "${out}"
}

# One launch attempt in one availability domain; prints the instance OCID or fails.
launch_in() {
  local ad="$1" image="$2" user_data="$3"
  oci compute instance launch --compartment-id "${OCI_COMPARTMENT_OCID}" --availability-domain "${ad}" \
    --display-name "${NAME}-vm" --shape "${SHAPE}" \
    --shape-config "{\"ocpus\":${OCI_OCPUS},\"memoryInGBs\":${OCI_MEMORY_GB}}" \
    --image-id "${image}" --boot-volume-size-in-gbs "${OCI_BOOT_VOLUME_GB}" \
    --subnet-id "${SUBNET_ID}" --assign-public-ip true --user-data-file "${user_data}" \
    --instance-options '{"areLegacyImdsEndpointsDisabled":true}' \
    --wait-for-state RUNNING --query data.id --raw-output
}

ensure_instance() {
  INSTANCE_ID="$(find_id "compute instance" "${NAME}-vm")"
  if [[ -n "${INSTANCE_ID}" ]]; then say "VM exists: ${INSTANCE_ID}"; return; fi
  local image user_data attempt ad err
  image="$(latest_ubuntu_image)"
  [[ -n "${image}" && "${image}" != "null" ]] || die "no Ubuntu 24.04 image for ${SHAPE} in this region"
  user_data="$(user_data_file)"
  err="$(mktemp)"
  for (( attempt = 1; attempt <= OCI_CAPACITY_ATTEMPTS; attempt++ )); do
    while read -r ad; do
      say "launching ${SHAPE} (${OCI_OCPUS} OCPU, ${OCI_MEMORY_GB} GB) in ${ad}, attempt ${attempt}"
      if INSTANCE_ID="$(launch_in "${ad}" "${image}" "${user_data}" 2>"${err}")"; then
        rm -f "${user_data}" "${err}"; say "VM running: ${INSTANCE_ID}"; return
      fi
      grep -qi "out of host capacity" "${err}" || { cat "${err}" >&2; rm -f "${user_data}" "${err}"; die "launch failed"; }
      echo "    out of host capacity in ${ad}"
    done < <(oci iam availability-domain list --compartment-id "${OCI_TENANCY_OCID}" --query 'data[].name' --raw-output | tr -d '[]", ' | grep -v '^$')
    (( attempt < OCI_CAPACITY_ATTEMPTS )) && sleep "${OCI_CAPACITY_RETRY_SECONDS}"
  done
  rm -f "${user_data}" "${err}"
  die "no A1 capacity after ${OCI_CAPACITY_ATTEMPTS} attempts; try again later or see docs/deployment/prerequisites-and-provision.md (capacity)"
}

# The way in before the tunnel exists: sessions are opened with deploy/oci/bastion-ssh.sh.
ensure_bastion() {
  BASTION_ID="$(oci bastion bastion list --compartment-id "${OCI_COMPARTMENT_OCID}" --all \
    --query "data[?name=='${NAME}bastion' && \"lifecycle-state\"!='DELETED'].id | [0]" --raw-output 2>/dev/null | grep -v '^null$' || true)"
  if [[ -z "${BASTION_ID}" ]]; then
    BASTION_ID="$(oci bastion bastion create --compartment-id "${OCI_COMPARTMENT_OCID}" --bastion-type standard \
      --name "${NAME}bastion" --target-subnet-id "${SUBNET_ID}" --client-cidr-list "[\"${OCI_BASTION_CLIENT_CIDR}\"]" \
      --max-session-ttl 10800 --wait-for-state SUCCEEDED --query 'data.resources[0].identifier' --raw-output)"
  else
    # Re-applied on every run: a new home IP in config.env replaces the old one (only one /32).
    oci bastion bastion update --bastion-id "${BASTION_ID}" --client-cidr-list "[\"${OCI_BASTION_CLIENT_CIDR}\"]" \
      --force --wait-for-state SUCCEEDED >/dev/null
  fi
  say "bastion ${BASTION_ID} (accepts ${OCI_BASTION_CLIENT_CIDR} only)"
}

ensure_bucket() {
  local namespace items
  namespace="$(oci os ns get --query data --raw-output)"
  if ! oci os bucket get --bucket-name "${OCI_BACKUP_BUCKET}" --namespace-name "${namespace}" >/dev/null 2>&1; then
    oci os bucket create --compartment-id "${OCI_COMPARTMENT_OCID}" --namespace-name "${namespace}" \
      --name "${OCI_BACKUP_BUCKET}" --public-access-type NoPublicAccess --storage-tier Standard >/dev/null
  fi
  items='[{"name":"expire-dumps","action":"DELETE","timeAmount":30,"timeUnit":"DAYS","isEnabled":true,"objectNameFilter":{"inclusionPrefixes":["pg/"]}}]'
  # The lifecycle rule needs the policy ensure_backup_permission just created, and a new IAM
  # policy takes a little while to apply: retry for about two minutes before giving up.
  local attempt
  for attempt in $(seq 1 12); do
    oci os object-lifecycle-policy put --bucket-name "${OCI_BACKUP_BUCKET}" --namespace-name "${namespace}" \
      --items "${items}" --force >/dev/null 2>&1 && break
    (( attempt < 12 )) || die "could not set the 30-day lifecycle rule on ${OCI_BACKUP_BUCKET}; run provision.sh again"
    say "waiting for the new policy to apply (attempt ${attempt})"
    sleep 10
  done
  say "bucket ${OCI_BACKUP_BUCKET} (private, dumps deleted after 30 days)"
}

# Only this VM may add and read dumps, only in the backup bucket, never delete or overwrite them
# (a compromised VM cannot destroy its backups). Object Storage itself may delete objects, which
# the 30-day lifecycle rule needs.
ensure_backup_permission() {
  local group="${NAME}-vm" policy="${NAME}-backups" id region where
  region="$(oci iam region-subscription list --tenancy-id "${OCI_TENANCY_OCID}" \
    --query 'data[?"is-home-region"].["region-name"] | [0][0]' --raw-output)"
  where="in compartment id ${OCI_COMPARTMENT_OCID} where target.bucket.name='${OCI_BACKUP_BUCKET}'"
  id="$(oci iam dynamic-group list --compartment-id "${OCI_TENANCY_OCID}" --all \
    --query "data[?name=='${group}'].id | [0]" --raw-output 2>/dev/null | grep -v '^null$' || true)"
  if [[ -z "${id}" ]]; then
    oci iam dynamic-group create --compartment-id "${OCI_TENANCY_OCID}" --name "${group}" \
      --description "The EcoFate VM (backups)" --matching-rule "instance.id = '${INSTANCE_ID}'" \
      --wait-for-state ACTIVE >/dev/null \
      || die "could not create dynamic group ${group}; on an Identity Domains tenancy create it in the console (docs/deployment/README.md)"
  fi
  id="$(oci iam policy list --compartment-id "${OCI_TENANCY_OCID}" --all \
    --query "data[?name=='${policy}'].id | [0]" --raw-output 2>/dev/null | grep -v '^null$' || true)"
  if [[ -z "${id}" ]]; then
    oci iam policy create --compartment-id "${OCI_TENANCY_OCID}" --name "${policy}" \
      --description "EcoFate VM writes its database dumps to one bucket" \
      --statements "[\"Allow dynamic-group ${group} to {OBJECT_INSPECT, OBJECT_CREATE, OBJECT_READ} ${where}\",\"Allow dynamic-group ${group} to read buckets ${where}\",\"Allow service objectstorage-${region} to manage object-family ${where}\"]" \
      --wait-for-state ACTIVE >/dev/null
  fi
  say "backup permission: dynamic group ${group}, policy ${policy}"
}

main() {
  command -v oci >/dev/null || die "install the OCI CLI first (brew install oci-cli) and run oci setup config"
  load_config
  check_free_limits
  ensure_vcn
  ensure_gateway_and_routes
  ensure_security_list
  close_default_security_list
  ensure_subnet
  ensure_instance
  ensure_bastion
  ensure_backup_permission
  ensure_bucket
  cat <<EOF

Done. The VM accepts no connection from the internet; it reaches out to Cloudflare once the
stack starts. Next steps (docs/deployment/README.md):
  1. Create the Cloudflare Tunnel and copy its token.
  2. Open a session with deploy/oci/bastion-ssh.sh and write /opt/ecofate/.env.prod and
     /opt/ecofate/tunnel.env (templates in deploy/).
  3. Add the deploy key and the GitHub secrets, then push a version tag.
VM: ${INSTANCE_ID}
EOF
}

main "$@"

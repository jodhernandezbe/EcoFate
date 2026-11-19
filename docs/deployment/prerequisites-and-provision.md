[← Documentation index](../../README.md#documentation) · [Deployment](README.md)

# Prerequisites and provisioning the VM

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

Next: [Cloudflare Tunnel and Access](cloudflare.md)

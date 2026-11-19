[← Documentation index](../../README.md#documentation) · [Deployment](README.md)

# Teardown and security notes

## Teardown

```bash
make deploy-teardown       # type the bucket name to confirm; deletes the VM, data and backups
```

Then delete the tunnel, the Access application and service token, and the `ecofate.org` /
`ssh.ecofate.org` / `www` records in Cloudflare.

## Security notes

- Nothing on the VM is reachable from the internet; the Bastion admits only your /32 and the
  tunnel only Cloudflare. Legacy instance metadata (IMDSv1) is disabled.
- The `ecofate` user is in the `docker` group, which is root-equivalent on the VM: protect your
  SSH key and the deploy key accordingly.
- Secrets exist only in the two files on the VM (mode 600) and your password manager; the
  tunnel token is read by `cloudflared` alone.
- `trusted_proxy_hops = 1` (production settings) is confirmed at the first deploy by checking
  that two visitors' sign-in throttles are counted separately.

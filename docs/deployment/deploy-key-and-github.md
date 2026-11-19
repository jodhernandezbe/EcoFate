[← Documentation index](../../README.md#documentation) · [Deployment](README.md)

# The deploy key and GitHub settings

## 5. The deploy key

The deploy key lets GitHub run exactly one thing on the VM: `deploy.sh`.

```bash
ssh-keygen -t ed25519 -N '' -C github-deploy -f ./ecofate_deploy_key     # on your machine
```

On the VM, append one line to `~ecofate/.ssh/authorized_keys` (the public key after the options):

```
restrict,command="/opt/ecofate/app/deploy/deploy.sh" ssh-ed25519 AAAA... github-deploy
```

`restrict` turns off port, agent and X11 forwarding and the terminal; `command=` makes every
connection run `deploy.sh`, which accepts only `deploy vX.Y.Z` or `rollback vX.Y.Z`. Check that
`/etc/ssh/sshd_config` has no `PermitUserEnvironment yes` and no `AcceptEnv` for `ECOFATE_*`
(Ubuntu's default accepts only `LANG LC_*`).

For the pinned host key, print the VM's key: `cat /etc/ssh/ssh_host_ed25519_key.pub` and build
the line `ssh.ecofate.org ssh-ed25519 AAAA...` (host name, then the key type and key).

## 6. GitHub settings

- **Secrets** (Settings → Secrets and variables → Actions): `DEPLOY_SSH_KEY` (the private
  `ecofate_deploy_key`, then delete the local file), `DEPLOY_KNOWN_HOSTS` (the line above),
  `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`.
- **Variable**: `DEPLOY_SSH_HOST` = `ssh.ecofate.org`.
- **Environment** `production` (Settings → Environments): you as **required reviewer**, and
  deployment tags limited to `v*.*.*`. Every deploy then waits for your approval.
- After the first release, make the packages `ecofate-api` and `ecofate-worker` **public**
  (your profile → Packages → package settings), so the VM pulls them without a token.

Next: [First release and rollback](release-and-rollback.md)

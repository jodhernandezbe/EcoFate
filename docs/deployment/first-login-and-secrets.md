[← Documentation index](../../README.md#documentation) · [Deployment](README.md)

# 4. First login and the secret files

```bash
make deploy-ssh            # opens a one-hour Bastion session and logs you in as ecofate
```

A new Bastion session refuses its key for a few seconds; the script retries ("not ready yet;
retrying") and uses the next free local port if 2222 is taken. It fails only when your public
IP no longer matches `OCI_BASTION_CLIENT_CIDR`: update `config.env` and run
`make deploy-provision` (it updates the Bastion). Ignore Ubuntu's offer to upgrade to a newer
release; reboot when it says "System restart required" (`oci compute instance action --action
SOFTRESET`, or the console).

On the VM (`ecofate` user):

```bash
cd /opt/ecofate
cp app/deploy/env.prod.example .env.prod && chmod 600 .env.prod && nano .env.prod
cp app/deploy/tunnel.env.example tunnel.env && chmod 600 tunnel.env && nano tunnel.env
```

Fill every uncommented variable (the template says how to generate each); keep a copy in your
password manager. `deploy.sh` refuses to deploy while one is missing and names it without showing
values. Email: `SMTP_HOST=smtp.mx.cloudflare.net`, `SMTP_PORT=465`, `SMTP_SECURITY=tls`,
`SMTP_USERNAME=api_token`, `SMTP_PASSWORD=` a **new** Cloudflare API token (not the one you use
locally): permission *Account → Email Sending → Edit*, **Account Resources** the account that owns
`ecofate.org` (or all accounts), and **no client IP filter** (the VM's outbound address is
Oracle's and can change). A token scoped otherwise still logs in but every send fails with
`550 5.7.1 Not authorized to send from domain`. `SMTP_FROM=noreply@ecofate.org`, exactly the
sender verified in Cloudflare Email Service (a different address is refused the same way).
`ECOFATE_BACKUP_BUCKET` is the bucket name from `config.env`.

The nightly backup timer was installed at first boot (`systemctl list-timers ecofate-backup.timer`);
until `.env.prod` exists its runs fail visibly in `journalctl -u ecofate-backup.service`.

Next: [The deploy key and GitHub settings](deploy-key-and-github.md)

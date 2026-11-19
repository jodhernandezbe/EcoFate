[← Documentation index](../../README.md#documentation) · [Deployment](README.md)

# 3. Cloudflare Tunnel and Access

Cloudflare moves these menus often; the dashboard search (**Cmd/Ctrl + K**) finds each page by
the name in bold.

1. **Tunnels** (main dashboard: Networking → Tunnels; or Zero Trust → Networks → Connectors) →
   **Create a tunnel**, type *Cloudflared*, name `ecofate`. Pick any OS (Debian, arm64): only the
   token matters. Copy the value starting with `eyJ` from the "install as a service" command
   into your password manager (it goes into `tunnel.env` in step 4); run nothing. The page can
   be opened again later to show it.
2. The wizard cannot continue while no connector runs: leave it, open the tunnel, **Routes →
   Add route → Published application**, and add two (the URL includes the protocol):
   - subdomain empty, domain `ecofate.org`, URL `http://api:8000` (**http**, not https: the
     tunnel encrypts, the API speaks plain HTTP inside the VM; https gives a 502)
   - subdomain `ssh`, domain `ecofate.org`, URL `ssh://host.docker.internal:22`

   Each route needs its own hostname: a route saved with an empty subdomain takes over
   `ecofate.org`. Editing a route can also move its DNS record, so afterwards check **DNS →
   Records** shows both `ecofate.org` and `ssh` as proxied CNAMEs to `<tunnel-id>.cfargotunnel.com`
   (add a missing one by hand).
3. **Service Tokens** (Zero Trust → Access → Service credentials) → **Create Service Token**
   named `github-deploy`, non-expiring (or a year). Copy the Client ID and Client Secret (the
   secret is shown once) for the GitHub secrets in step 6.
4. **Applications** (Zero Trust → Access) → **Add an application → Self-hosted** (not
   *Infrastructure*, which needs the WARP client), name `ecofate-ssh`, hostname `ssh.ecofate.org`,
   with a policy whose action is **Service Auth** and whose rule is that service token. Optionally
   add a second policy (action *Allow*) for your own email, to SSH in through the browser login.
   The default session duration is fine (service-token requests re-authenticate every time).
   Never put an Access application on `ecofate.org` itself: the site is public.
5. **Check Access before going further**: from your machine, `ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ecofate@ssh.ecofate.org`
   must stop at a Cloudflare login (or be refused) unless you pass the service token or your
   email policy lets you in. sshd is reachable through the tunnel, so Access is what guards it.
6. Zone settings for `ecofate.org`: **SSL/TLS → Edge Certificates → Always Use HTTPS** on, **HSTS**
   on (max-age 6 months, include subdomains); **Rules → Redirect Rules**: `www.ecofate.org/*` →
   `https://ecofate.org/${1}` (301), with a proxied DNS record for `www`.

Next: [First login and the secret files](first-login-and-secrets.md)

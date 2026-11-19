[← Documentation index](../../README.md#documentation) · [Security](README.md)

# Secrets and automated checks

## Secrets in CI and production

- **CI** (`.github/workflows/ci.yml`) needs no repository secret and never runs the `eval`
  marker: the `docker` job uses the placeholder `.github/ci.env` plus a throwaway database
  password, key-encryption key and session secret generated in the job. Actions are pinned to
  commit SHAs and Dependabot proposes updates weekly.
- **Evaluations** (`.github/workflows/evals.yml`) are started by hand in the `evals` environment
  (which can require approval) and use the secrets `OPENAI_API_KEY`, `COMPTOX_API_KEY` and
  `CENSUS_API_KEY`.
- **Deploy** (`.github/workflows/deploy.yml`) uses `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`,
  `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` and the variable `DEPLOY_SSH_HOST`, in the
  `production` environment with a required reviewer. The deploy key can run only
  `deploy/deploy.sh`, which accepts only `deploy vX.Y.Z` or `rollback vX.Y.Z`.
- **Production secrets** exist only in `/opt/ecofate/.env.prod` and `/opt/ecofate/tunnel.env` on the
  VM (mode 600, owner `ecofate`; templates in `deploy/`) and in the owner's password manager.
  `deploy.sh` checks both files and names a missing variable without printing values. Nothing on
  the VM is reachable from the internet. See [deployment](../deployment/teardown-and-security.md#security-notes).
- **Never in the repository or an image:** keys, tokens, passwords, the database URL. The `.env`
  file is git-ignored and the Dockerfile copies no secret.

## Automated checks

`pre-commit` runs `detect-secrets` (baseline `.secrets.baseline`), `detect-private-key`, strict
pyright and `bandit`; CI also runs `make audit` (`pip-audit`, with the few reviewed exceptions
listed in the `Makefile`). Run them all with `make check`.

## Reporting a vulnerability

The repository has no `SECURITY.md` and no recorded disclosure channel. Until one is added, do not
open a public issue with exploit details: contact the author named in `CITATION.cff` directly.

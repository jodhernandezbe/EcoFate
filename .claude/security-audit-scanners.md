# Deterministic security scanners

Read by `/security-audit` before the independent auditor runs. Every command runs from the
repository root. Each was verified on 2026-10-30.

| Layer | Command | Notes |
| --- | --- | --- |
| Secrets | `git diff --name-only <range> \| xargs uv run pre-commit run detect-secrets --files` | Yelp detect-secrets against `.secrets.baseline`. Pass only the changed files; `--all-files` re-scans the whole tree and is slow. Use the `xargs` form: this session's shell is zsh, which does not word-split an unquoted variable, so `--files $FILES` arrives as one argument and pre-commit reports "no files to check" while appearing to pass. Never add a real secret to the baseline to silence it. |
| Security lint (Python) | `uv run bandit -c pyproject.toml -q -r agent app api commons config evals models prompts tools` | Configuration in `pyproject.toml`; `tests` and `.venv` are excluded there. Quiet mode prints nothing when clean. Warnings about comment-style test names are noise from the config, not findings. |
| Dependency advisories (Python) | `make audit` | pip-audit with the reviewed exceptions (`AUDIT_ACCEPTED` in the `Makefile`, each with its reason); CI runs the same target. Audits the resolved environment, so it covers transitive dependencies. Takes a few minutes. Run only when `pyproject.toml` or `uv.lock` changed. |
| Dependency advisories (frontend) | `npm --prefix frontend audit --audit-level=high` | Run only when `frontend/package.json` or `frontend/package-lock.json` changed. |
| Types | `uv run pyright` | Not a security tool, but a type error at a trust boundary often is one. Already enforced by pre-commit; report it only if it fails on the changed files. |

## Reading the output honestly

A scanner that prints "Skipped" or "no files to check" has **not** passed. Say so and find out
why before moving on. The most common cause here is a file list that reached the tool as a
single argument; see the secrets row.

## Exit codes

- `detect-secrets`: non-zero means a potential secret outside the baseline. Treat as a finding
  until shown otherwise; never resolve it by regenerating the baseline.
- `bandit`: non-zero means at least one issue at or above the configured severity. Read the
  issue; bandit reports patterns, so confirm the path before calling it a defect.
- `pip-audit`: non-zero means at least one advisory in the resolved environment.
- `npm audit`: non-zero means an advisory at or above `high`.

## Known state (2026-11-17)

`make audit` is clean. `jupyter` (a runtime dependency nothing imported) was removed, which took
JupyterLab, Notebook, nbconvert, mistune and bleach with it, and every other advisory with a fix
was upgraded away. The only accepted advisories are four in `chromadb` (no fixed version), all
about the Chroma server, which EcoFate does not run (it uses the embedded client); their IDs and
reasons are in the `Makefile`. A new advisory, or a chromadb release that fixes them, makes the
target fail or the ignore list stale: revisit the list then. `torch` is skipped with a warning
on Linux (CPU wheel from PyTorch's own index, not on PyPI); that is not a pass for torch.

## Not configured

- No semantic static analysis (Semgrep or CodeQL) and no container or infrastructure scanning.
  The project ships no containers or infrastructure code, so the gap is the semantic pass.
- CI (`.github/workflows/ci.yml`) runs the pre-commit hooks (detect-secrets, bandit, pyright) and `make audit`; `npm audit` runs only by hand.

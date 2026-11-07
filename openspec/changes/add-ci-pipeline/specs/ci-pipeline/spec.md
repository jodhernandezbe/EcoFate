## ADDED Requirements

### Requirement: Checks on every push and pull request
The repository SHALL have a continuous-integration workflow that runs on every pull request
and every push to `main` and fails when any of these fails: the hooks listed in
`.pre-commit-config.yaml` (run from that file, not re-listed), the default pytest run, the
dependency vulnerability audit, the frontend check and the frontend build. The default run
SHALL NOT require any secret and SHALL NOT run the `eval` marker.

#### Scenario: Lint failure
- **WHEN** a pull request introduces a ruff error
- **THEN** the CI run fails in the Python job and the commit shows a failed check

#### Scenario: Frontend failure
- **WHEN** a push breaks the frontend type check
- **THEN** the frontend job fails

#### Scenario: No secrets needed
- **WHEN** the workflow runs on a pull request from a fork with no repository secrets available
- **THEN** every job runs to a pass or fail on the code's merits, and no step asks for a key

### Requirement: Container build and start in CI
The CI workflow SHALL build every target of the project's `Dockerfile` and SHALL start the
compose stack with placeholder configuration, wait until its services report healthy, call
the API health endpoint, and stop the stack and remove its volumes whatever the outcome.

#### Scenario: Stack starts
- **WHEN** the images build and the compose stack starts
- **THEN** the health endpoint answers with success and the job passes

#### Scenario: Stack fails to start
- **WHEN** a service exits or never becomes healthy
- **THEN** the job fails and the stack is still torn down

### Requirement: Evaluations run only on demand
The repository SHALL have a separate evaluation workflow that runs only when started by hand,
offers the scripted scenarios, the catalogue run and the judge of a named run, uses the
OpenAI key (and, for the catalogue, the CompTox and Census keys) from repository secrets, and
uploads the evaluation reports as a downloadable artifact even when the evaluation fails.
User-supplied inputs SHALL reach commands only through environment variables and SHALL be
validated before use.

#### Scenario: Never on push
- **WHEN** commits are pushed or a pull request is opened
- **THEN** the evaluation workflow does not run

#### Scenario: Report artifact
- **WHEN** the owner starts the workflow with the scenarios choice
- **THEN** the run's `evals/reports/<timestamp>/` folder is attached to the run as an artifact

#### Scenario: Malicious run directory
- **WHEN** the judge choice is started with a run directory that does not match the timestamp pattern
- **THEN** the workflow fails before running any command with that value

### Requirement: Secret hygiene and least privilege in workflows
Workflows SHALL default to read-only repository permissions, SHALL pin every third-party
action to a full commit SHA, SHALL expose a secret only as an environment variable of the
step that needs it, and SHALL NOT print a secret. Superseded runs of the same branch SHALL
be cancelled. Dependency and action updates SHALL be proposed automatically.

#### Scenario: Pinned actions
- **WHEN** a workflow file is reviewed
- **THEN** every `uses:` of a third-party action names a 40-character commit SHA

#### Scenario: Secret masked
- **WHEN** an evaluation step fails with an error mentioning its environment
- **THEN** the log shows no secret value

### Requirement: Cached dependencies
CI SHALL cache the uv package cache keyed on `uv.lock`, the npm cache keyed on
`frontend/package-lock.json`, the pre-commit environments keyed on
`.pre-commit-config.yaml`, and Docker build layers, so an unchanged lockfile does not
re-download dependencies.

#### Scenario: Warm cache
- **WHEN** CI runs twice on commits with the same lockfiles
- **THEN** the second run restores the uv, npm and pre-commit caches instead of downloading them

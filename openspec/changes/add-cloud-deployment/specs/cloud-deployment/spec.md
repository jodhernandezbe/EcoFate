## ADDED Requirements

### Requirement: Scripted provisioning and teardown on AWS
The repository SHALL provide a provisioning script that creates, from one configuration
file, a single Ubuntu virtual machine on AWS with at least 4 GB of memory, a static public
IP, a security group that allows ports 80 and 443 from anywhere and port 22 only from a
configured operator address range (or not at all), an instance role limited to reading the
deployment's parameters and writing to one backup bucket, and a private, versioned,
encrypted backup bucket with a retention lifecycle. Running it twice SHALL NOT create
duplicates. A teardown script SHALL delete every resource the provisioning script created
after an explicit confirmation. The deployment guide SHALL state the expected monthly cost.

#### Scenario: Provision
- **WHEN** the operator runs the provisioning script with a filled configuration file
- **THEN** the VM, IP, security group, role and bucket exist and the script prints the public IP and the next steps

#### Scenario: SSH closed to the world
- **WHEN** the security group is inspected
- **THEN** port 22 is not open to `0.0.0.0/0`

#### Scenario: Teardown requires confirmation
- **WHEN** the teardown script runs and the typed bucket name does not match
- **THEN** nothing is deleted

### Requirement: Production stack behind TLS
The production configuration SHALL run the same services as local development from
published images, with a reverse proxy that obtains and renews a TLS certificate for the
configured domain, redirects HTTP to HTTPS, sets HSTS and security headers, and proxies the
API without buffering server-sent events. Only the proxy SHALL publish ports on the host.
Containers SHALL restart unless stopped and SHALL rotate their logs.

#### Scenario: HTTPS only
- **WHEN** a client requests the site over HTTP
- **THEN** it is redirected to HTTPS and the HTTPS response carries a `Strict-Transport-Security` header

#### Scenario: Database not exposed
- **WHEN** the host's listening ports are inspected
- **THEN** PostgreSQL and Redis are not reachable from outside the compose network

#### Scenario: Streaming not buffered
- **WHEN** a chat turn streams progress events through the proxy
- **THEN** the browser receives each event as it is sent, not at the end of the turn

### Requirement: Secrets only from the parameter store
Production secrets SHALL be stored as encrypted parameters in AWS SSM Parameter Store and
written on the VM, at each deploy, to an environment file readable only by the service user.
No secret SHALL be committed to git, baked into an image, passed through the CI runner, or
printed by any deployment script.

#### Scenario: Environment file permissions
- **WHEN** secrets are fetched on the VM
- **THEN** the environment file has mode 0600 and is owned by the service user

#### Scenario: Missing parameter
- **WHEN** a required parameter is absent from the parameter store
- **THEN** the deploy stops with a message naming the parameter and not showing any value, and the running release keeps serving

### Requirement: Release from a version tag
Pushing a version tag SHALL build the application images, publish them to the GitHub
container registry tagged with the version and the commit, and deploy that version to the VM
through AWS Systems Manager using short-lived credentials obtained through OpenID Connect,
without long-lived AWS keys and without inbound SSH from the CI runner.

#### Scenario: Tag deploys
- **WHEN** tag `v1.2.0` is pushed
- **THEN** images tagged `v1.2.0` are published and the VM runs them after the workflow succeeds

#### Scenario: No static cloud credentials
- **WHEN** the repository secrets are listed
- **THEN** none of them is an AWS access key

### Requirement: Migrations before the new release serves
Each deploy SHALL apply the database migrations in a one-off step before the API and the
worker of the new release start, and SHALL NOT start them if the migration fails. A release
SHALL only add to the schema; removals and renames SHALL come in a later release, so the
previous release keeps working against the migrated schema.

#### Scenario: Migration fails
- **WHEN** the migration step exits with an error
- **THEN** the API and worker of the new release are not started and the deploy fails

### Requirement: Health-checked deploy with automatic rollback
A deploy SHALL wait for the API health endpoint, which reports healthy only when the database
and Redis are reachable, to succeed over HTTPS through the proxy. If it does not succeed
within the configured number of attempts, the deploy SHALL redeploy the previously running
release and fail. The operator SHALL be able to redeploy any earlier version tag on demand.

#### Scenario: Failed health check rolls back
- **WHEN** the new release never reports healthy
- **THEN** the previous release is running again and the workflow is marked failed

#### Scenario: Manual rollback
- **WHEN** the operator starts the deploy workflow with an earlier tag
- **THEN** the VM runs that tag after the health check passes

#### Scenario: Health body reveals nothing
- **WHEN** the database is unreachable and the health endpoint is called
- **THEN** it answers unhealthy with a fixed body that contains no host name, error text or credential

### Requirement: Nightly off-host backups with a tested restore
The VM SHALL dump the PostgreSQL database every night and upload the dump to the backup
bucket, failing visibly when any step fails. A restore script SHALL restore a named dump
into a fresh database and switch to it only after a sanity check. The deployment guide SHALL
record one completed restore drill.

#### Scenario: Nightly dump
- **WHEN** the backup timer fires
- **THEN** a dump named with the UTC date exists in the bucket and no local copy is left behind

#### Scenario: Restore
- **WHEN** the operator restores a dump
- **THEN** the application serves the restored users and threads after the switch

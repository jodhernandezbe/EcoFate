# cloud-deployment Specification

## Purpose

The production deployment at https://ecofate.org: an Oracle Cloud Always Free VM running the
docker compose stack behind a Cloudflare Tunnel, released from version tags with a health-checked
deploy and automatic rollback, secrets kept only on the VM, nightly off-host backups with a tested
restore, and outgoing email from the domain.

## Requirements

### Requirement: Scripted provisioning and teardown on Oracle Cloud Always Free
The repository SHALL provide a provisioning script that creates, from one configuration file, a
single Ubuntu virtual machine on Oracle Cloud using only Always Free shapes and limits, with at
least 4 GB of memory, a network whose security list allows no inbound traffic from the internet (only SSH
from inside the VM's own subnet, for a managed bastion that accepts only the operator's address), a
permission that
lets only that VM write to one backup bucket without stored keys, and a private backup bucket with
a retention rule. Running it twice SHALL NOT create duplicates, and a capacity error SHALL be
retried and then reported with what to try next. A teardown script SHALL delete every resource the
provisioning script created after an explicit confirmation. The deployment guide SHALL state that
the expected monthly cost is zero and how to keep it so.

#### Scenario: Provision
- **WHEN** the operator runs the provisioning script with a filled configuration file
- **THEN** the VM, network, permission and bucket exist and the script prints the next steps

#### Scenario: Nothing open to the internet
- **WHEN** the VM's security rules are inspected
- **THEN** no inbound rule admits traffic from outside the VM's subnet, and the only rule admits SSH from inside it

#### Scenario: Bastion limited to the operator
- **WHEN** the bastion's allowed client addresses are inspected
- **THEN** they are exactly the operator's single address, never an open range

#### Scenario: Never beyond Always Free
- **WHEN** the configuration asks for more OCPUs or memory than the Always Free limits
- **THEN** the script refuses before creating anything and names the limit

#### Scenario: Teardown requires confirmation
- **WHEN** the teardown script runs and the typed bucket name does not match
- **THEN** nothing is deleted

### Requirement: Production stack behind Cloudflare
The production configuration SHALL run the same services as local development from published
images and SHALL reach the internet only through an outbound Cloudflare Tunnel that serves the
configured domain over HTTPS with HTTP and the `www` name redirected to it and HSTS set. No service
SHALL publish a port on the host. Containers SHALL restart unless stopped and SHALL rotate their
logs. In production the web program SHALL accept requests whose host and origin are the public
domain (and still reject any other), SHALL send the session cookie only over HTTPS, SHALL take the
client address for throttling from the forwarding header entry the configured proxies vouch for,
and SHALL keep a quiet event stream open by sending an event-stream comment at a configured
interval shorter than the proxy's idle timeout.

#### Scenario: HTTPS only
- **WHEN** a client requests `http://ecofate.org` or `https://www.ecofate.org`
- **THEN** it is redirected to `https://ecofate.org` and the response carries a `Strict-Transport-Security` header

#### Scenario: Public origin accepted, others rejected
- **WHEN** a request with `Host: ecofate.org` arrives through the tunnel, and another with `Host: evil.example`
- **THEN** the first is served and the second is rejected with the fixed refusal

#### Scenario: Secure session cookie
- **WHEN** a user signs in on the production site
- **THEN** the session cookie is marked `Secure` and `HttpOnly`

#### Scenario: Real client address
- **WHEN** two users sign in from different addresses through Cloudflare
- **THEN** sign-in throttling counts them separately, not as the tunnel's single address

#### Scenario: Long quiet turn
- **WHEN** a tool runs for longer than the proxy's idle timeout without producing an event
- **THEN** the stream stays open, carrying comment lines only, and the turn's later events arrive

#### Scenario: Nothing exposed on the host
- **WHEN** the host's listening ports are inspected
- **THEN** no application, database or Redis port is reachable from outside the compose network

### Requirement: Secrets only on the VM
Production secrets SHALL exist only in one environment file on the VM, readable only by the
service user, and in the owner's own safekeeping. No secret SHALL be committed to git, baked into
an image, passed through or stored in the CI system except the deploy key and the tunnel access
token, or printed by any deployment script. The repository SHALL list the required variable names
without values.

#### Scenario: Environment file permissions
- **WHEN** the deploy runs
- **THEN** it refuses to continue unless the environment file has mode 0600 and is owned by the service user

#### Scenario: Missing variable
- **WHEN** a required variable is absent or empty in the environment file
- **THEN** the deploy stops with a message naming the variable and not showing any value, and the running release keeps serving

### Requirement: Release from a version tag
Pushing a version tag SHALL build the application images for the VM's architecture, publish them
to the GitHub container registry tagged with the version and the commit, and deploy that version
to the VM over the tunnel with a key that can only run the deploy script, without any inbound port
open on the VM. The deploy SHALL accept only a version tag that matches the release pattern.

#### Scenario: Tag deploys
- **WHEN** tag `v0.2.0` is pushed
- **THEN** arm64 images tagged `v0.2.0` are published and the VM runs them after the workflow succeeds

#### Scenario: Deploy key cannot open a shell
- **WHEN** the deploy key is used to request an interactive shell or another command
- **THEN** only the deploy script runs, and it rejects anything that is not a valid version tag

### Requirement: Migrations before the new release serves
Each deploy SHALL apply the database migrations in a one-off step before the API and the worker of
the new release start, and SHALL NOT start them if the migration fails. A release SHALL only add to
the schema; removals and renames SHALL come in a later release, so the previous release keeps
working against the migrated schema.

#### Scenario: Migration fails
- **WHEN** the migration step exits with an error
- **THEN** the API and worker of the new release are not started and the deploy fails

### Requirement: Health-checked deploy with automatic rollback
A deploy SHALL wait for the API health endpoint, which reports healthy only when the database and
Redis are reachable, to succeed over HTTPS at the public domain. If it does not succeed within the
configured number of attempts, the deploy SHALL redeploy the previously running release and fail.
The operator SHALL be able to redeploy any earlier version tag on demand.

#### Scenario: Failed health check rolls back
- **WHEN** the new release never reports healthy
- **THEN** the previous release is running again and the workflow is marked failed

#### Scenario: Manual rollback
- **WHEN** the operator starts the deploy workflow with an earlier tag
- **THEN** the VM runs that tag after the health check passes

#### Scenario: Health body reveals nothing
- **WHEN** the database or Redis is unreachable and the health endpoint is called
- **THEN** it answers unhealthy with a fixed body that contains no host name, error text or credential

### Requirement: Nightly off-host backups with a tested restore
The VM SHALL dump the PostgreSQL database every night and upload the dump to the backup bucket
using its own identity, failing visibly when any step fails. A restore script SHALL restore a named
dump into a fresh database and switch to it only after a sanity check. The deployment guide SHALL
record one completed restore drill.

#### Scenario: Nightly dump
- **WHEN** the backup timer fires
- **THEN** a dump named with the UTC date exists in the bucket and no local copy is left behind

#### Scenario: Restore
- **WHEN** the operator restores a dump
- **THEN** the application serves the restored users and threads after the switch

### Requirement: Outgoing email from the domain
In production, verification and password-reset emails SHALL be sent from an address on the public
domain through an SMTP provider over an encrypted connection, with the domain's SPF and DKIM
records published, so that they are accepted by common mail providers.

#### Scenario: Sign-up email delivered
- **WHEN** a new user signs up on the production site with a real mailbox
- **THEN** the verification email arrives from the domain's address and passes SPF and DKIM

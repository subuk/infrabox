# InfraBox MVP — Codex Implementation Plan

> Original MVP implementation contract and historical scope. Current user
> instructions are in [installation](docs/installation.md) and
> [architecture](docs/architecture.md). Later accepted work adds central
> [identity](docs/identity.md), [monitoring dashboards](docs/monitoring.md),
> [OpenClaw](docs/openclaw.md) and [Platform](docs/platform.md), superseding the
> local-admin-only, no-dashboard and no-AI exclusions below. Preserve the remaining
> bootstrap, TPM, PKI and isolation invariants. Historical target addresses are
> not defaults for a new deployment. See the [documentation map](docs/README.md).

## 1. Objective

Implement an Ansible repository that turns a clean AlmaLinux 10 host into a single-node InfraBox appliance.

The MVP must be:

- deterministic;
- idempotent;
- secure by default;
- explicit about bootstrap transitions;
- based on Podman + Quadlet rather than Kubernetes;
- compatible with SELinux enforcing mode;
- built around short-lived automatically rotated certificates;
- automatically unsealed after reboot using the host TPM 2.0;
- simple enough to recover operationally without hidden Ansible state machines.

Do not silently redesign the architecture while implementing it.

---

# 2. Final MVP architecture

```text
AlmaLinux 10
│
├── systemd
├── SELinux
├── firewalld
├── chrony
├── Podman
├── nginx                       native
├── OpenBao Agent               native
│
├── TPM 2.0
│     └── tpm2-pkcs11
│            └── OpenBao auto-unseal
│
└── Podman + Quadlet
      ├── OpenBao
      ├── PostgreSQL
      ├── Redis
      ├── Gitea
      ├── Gitea Runner
      ├── NetBox
      ├── NetBox Worker
      ├── Prometheus
      └── Grafana
```

Not part of the MVP:

```text
OpenTelemetry Collector
Loki
Alertmanager
backup/restore
HA
Kubernetes
Argo CD
AI agent
```

---

# 3. High-level component responsibilities

```text
Gitea
    Git repositories
    Pull Requests
    Gitea Actions
    package registry
    OCI registry

Gitea Runner
    user-facing CI execution

NetBox
    infrastructure Source of Truth
    IPAM/DCIM

OpenBao
    secrets
    PKI
    authentication
    certificate authority

OpenBao Agent
    leaf certificate acquisition
    leaf certificate rendering
    automatic certificate rotation

TPM2 + tpm2-pkcs11
    unattended OpenBao auto-unseal

PostgreSQL
    Gitea database
    NetBox database
    Grafana database

Redis
    NetBox tasks/cache

Prometheus
    InfraBox monitoring

Grafana
    visualization; dashboard provisioning is outside the MVP

nginx
    public HTTPS entry point

Ansible
    installation and desired-state management
    of the InfraBox appliance itself
```

NetBox must NOT be used as bootstrap inventory for InfraBox.

Static Ansible inventory remains authoritative for deployment of the appliance.

---

# 4. Native versus containerized components

Native host services/components:

```text
chrony
SELinux tooling
firewalld
Podman
nginx
OpenBao Agent
tpm2-pkcs11 tooling
```

Containerized through Podman + Quadlet:

```text
OpenBao
PostgreSQL
Redis
Gitea
Gitea Runner
NetBox
NetBox Worker
Prometheus
Grafana
```

Application services should normally be containerized.

Native deployment is reserved for components that intentionally integrate with the host.

---

# 5. Ansible architecture rules

Every role represents one concrete component or OS facility.

Allowed examples:

```text
chrony
selinux
firewalld
cacerts
podman
tpm2_pkcs11
postgresql
redis
gitea
netbox
openbao
openbao_bootstrap
openbao_agent
nginx
```

Do NOT introduce generic roles such as:

```text
base
common
network
storage
platform
services_common
security_common
```

Playbooks provide orchestration.

Roles provide component implementation.

Ansible must describe an explicitly selected desired state.

Ansible must NOT infer bootstrap security transitions.

In particular:

```text
OpenBao HTTP -> OpenBao TLS
```

is an explicit operator configuration change.

---

# 6. Mandatory lifecycle tags

Every role must use the common lifecycle tags where applicable:

```text
install
configure
service
verify
```

Definitions:

```text
install
    packages
    binaries
    system users/groups
    prerequisites

configure
    directories
    configuration files
    policies
    PKI definitions
    Quadlet definitions

service
    enable
    start
    restart
    reload

verify
    health
    readiness
    acceptance checks
```

Each role also receives its role-specific tag.

Example:

```yaml
- role: redis
  tags:
    - redis
```

Recommended structure:

```text
roles/<role>/tasks/
├── main.yml
├── install.yml
├── configure.yml
├── service.yml
└── verify.yml
```

Small roles may omit genuinely empty lifecycle files.

---

# 7. Variable naming

All role-owned variables must use the role name as prefix.

Correct:

```yaml
tpm2_pkcs11_device:
tpm2_pkcs11_store_dir:

openbao_version:
openbao_tls_enabled:

openbao_agent_version:
openbao_agent_certificates:

postgresql_image:
postgresql_version:

netbox_image:
netbox_version:

grafana_database_name:
```

Incorrect:

```yaml
version:
image:
enabled:
port:
data_dir:
```

Shared appliance variables use:

```text
infrabox_
```

At minimum:

```yaml
infrabox_domain: infrabox1.krglv.com
infrabox_internal_domain: infrabox.internal
infrabox_timezone: Europe/Berlin

infrabox_storage_root: /srv/infrabox
infrabox_config_root: /etc/infrabox
infrabox_pki_root: /etc/infrabox/pki

infrabox_root_ca_path: /etc/infrabox/pki/root-ca.crt
```

---

# 8. Repository structure

```text
infrabox-ansible/
├── ansible.cfg
├── requirements.yml
├── README.md
├── IMPLEMENTATION_PLAN.md
│
├── site.yml
├── system.yml
├── platform.yml
├── pki.yml
├── services.yml
├── edge.yml
├── ci.yml
├── observability.yml
├── verify.yml
│
├── images/
│   └── openbao/
│       └── Containerfile
│
├── inventories/
│   ├── development/
│   │   ├── hosts.yml
│   │   ├── group_vars/
│   │   │   ├── all.yml
│   │   │   └── infrabox.yml
│   │   └── host_vars/
│   │
│   └── production/
│       ├── hosts.yml
│       ├── group_vars/
│       │   ├── all.yml
│       │   └── infrabox.yml
│       └── host_vars/
│
└── roles/
    ├── packages/
    ├── chrony/
    ├── selinux/
    ├── firewalld/
    ├── cacerts/
    ├── podman/
    ├── quadlet/
    ├── tpm2_pkcs11/
    │
    ├── openbao/
    ├── openbao_bootstrap/
    ├── openbao_agent/
    │
    ├── postgresql/
    ├── redis/
    ├── gitea/
    ├── netbox/
    ├── nginx/
    ├── gitea_runner/
    ├── prometheus/
    └── grafana/
```

There is intentionally no `backup.yml` or `restore.yml` in the MVP.

---

# 9. Filesystem layout

Configuration:

```text
/etc/infrabox/
├── openbao/
├── openbao-agent/
├── postgresql/
├── redis/
├── gitea/
├── netbox/
├── nginx/
├── prometheus/
├── grafana/
└── pki/
```

Persistent application data:

```text
/srv/infrabox/
├── openbao/
├── postgresql/
├── redis/
├── gitea/
├── netbox/
├── prometheus/
└── grafana/
```

TPM2 PKCS#11 state:

```text
/var/lib/infrabox/tpm2-pkcs11/
```

Container writable layers must never contain authoritative persistent data.

---

# 10. SELinux

SELinux must remain:

```text
enabled
enforcing
```

Never solve a deployment issue using:

```text
setenforce 0
SELINUX=disabled
```

Service-specific SELinux requirements belong to the corresponding role.

For bind mounts:

```text
:z
```

should be used where the same host content is shared across multiple containers.

```text
:Z
```

may be used for content private to one container.

In particular the shared RootCA must not repeatedly receive mutually exclusive private labels.

---

# 11. firewalld

Public host exposure:

```text
22/tcp      host administration
80/tcp
443/tcp
2222/tcp    Gitea SSH
```

Do NOT expose publicly:

```text
5432 PostgreSQL
6379 Redis
8200 OpenBao
Gitea internal HTTP
NetBox internal HTTP
Grafana internal HTTP
Prometheus HTTP
```

OpenBao bootstrap HTTP must only be reachable through host localhost.

---

# 12. Podman

Role:

```text
podman
```

Prefix:

```text
podman_
```

Responsibilities:

```text
install Podman/container tooling
configure registries
configure storage if required
configure InfraBox network
verify Quadlet support
verify runtime operation
```

Default:

```yaml
podman_api_enabled: false
```

InfraBox does not depend on the Podman REST socket.

Never expose the rootful Podman socket over the network.

Never mount it into Gitea Runner.

---

# 13. Quadlet helper

Role:

```text
quadlet
```

Prefix:

```text
quadlet_
```

This is an implementation helper rather than an application role.

Suggested interface:

```yaml
quadlet_name:
quadlet_type:
quadlet_definition:
quadlet_enabled:
quadlet_state:
```

It may:

```text
render /etc/containers/systemd/*
daemon-reload
enable/start generated unit
verify unit
```

It must contain no Gitea/PostgreSQL/OpenBao/etc. logic.

---

# 14. InfraBox Podman network

Create the internal application network (the runner requires separate network isolation; see section 89):

```text
infrabox.network
```

Containerized services receive stable aliases.

Required logical names:

```text
openbao.infrabox.internal
postgresql.infrabox.internal
redis.infrabox.internal
gitea.infrabox.internal
netbox.infrabox.internal
prometheus.infrabox.internal
grafana.infrabox.internal
```

Actual values derive from:

```yaml
infrabox_internal_domain:
```

TLS certificate SANs must correspond exactly to names clients use.

Do not issue a certificate for one hostname and connect using another.

---

# 15. TPM2 auto-unseal architecture

TPM auto-unseal is mandatory. The initial target is an AlmaLinux 10 VM with a virtual TPM; physical TPM hosts remain supported.

Architecture:

```text
TPM 2.0
   │
   ▼
tpm2-pkcs11
   │
   │ PKCS#11
   ▼
OpenBao PKCS#11 seal
   │
   ▼
automatic unseal
```

Do NOT initialize OpenBao first with Shamir and later migrate it.

PKCS#11 seal must be configured before the initial:

```text
bao operator init
```

OpenBao must therefore be initialized directly using the TPM-backed auto-unseal mechanism.

---

# 16. tpm2_pkcs11 role

Role:

```text
tpm2_pkcs11
```

Prefix:

```text
tpm2_pkcs11_
```

Responsibilities:

## install

Install:

```text
tpm2-tools
tpm2-pkcs11
tpm2-pkcs11-tools
```

AlmaLinux 10 packages must be used where available.

## configure

Create a dedicated PKCS#11 store.

Initialize an InfraBox token.

Create the TPM-backed key used by OpenBao.

## service

No persistent service is expected unless required by the selected TPM stack.

## verify

Verify:

```text
TPM resource manager exists
PKCS#11 module loads
InfraBox token exists
OpenBao seal key exists
PKCS#11 crypto operation succeeds
```

Required TPM device:

```yaml
tpm2_pkcs11_device: /dev/tpmrm0
```

Both physical and virtual appliance deployments must fail clearly if TPM2 is unavailable.

Do not silently downgrade to software-based unseal.

---

# 17. TPM2 PKCS#11 variables

Suggested variables:

```yaml
tpm2_pkcs11_device: /dev/tpmrm0

tpm2_pkcs11_store_dir: /var/lib/infrabox/tpm2-pkcs11

tpm2_pkcs11_token_label: InfraBox
tpm2_pkcs11_key_label: openbao-unseal

tpm2_pkcs11_key_type: rsa
tpm2_pkcs11_key_bits: 4096

tpm2_pkcs11_mechanism: RSA_PKCS_OAEP
tpm2_pkcs11_rsa_oaep_hash: sha256
```

PIN values are secrets:

```yaml
tpm2_pkcs11_so_pin:
tpm2_pkcs11_user_pin:
```

They must not appear in Git.

Tasks handling PINs must use:

```yaml
no_log: true
```

where appropriate.

---

# 18. TPM provisioning idempotency

The role must NOT recreate TPM objects on every Ansible run.

Required behavior:

```text
store missing
    -> initialize store

token missing
    -> create token

key missing
    -> create key

objects already exist
    -> verify them
    -> leave them unchanged
```

Normal Ansible execution must never replace the OpenBao seal key.

Changing the seal key is not ordinary configuration management.

---

# 19. OpenBao PKCS#11 runtime requirements

OpenBao runs inside a container but must access:

```text
/dev/tpmrm0
tpm2-pkcs11 store
tpm2-pkcs11 PKCS#11 provider
```

Do NOT run the OpenBao container with:

```text
--privileged
```

Only the TPM resource-manager device should be exposed.

The OpenBao process must receive the minimum permissions required to access the device.

---

# 20. OpenBao container image for TPM

For the MVP pin:

```yaml
openbao_version: "2.6.2"
```

Use an OpenBao 2.6.x HSM-capable build because PKCS#11 auto-unseal is available directly in that release line.

The repository may contain a small InfraBox OpenBao image definition:

```text
images/openbao/Containerfile
```

Its purpose is only to combine:

```text
HSM-capable OpenBao
+
tpm2-pkcs11 runtime/provider
```

Do NOT mount arbitrary host `/usr/lib64` trees into the container.

The resulting image must contain the PKCS#11 provider and all required runtime libraries.

Verify inside the resulting image that the configured PKCS#11 module can actually be loaded.

Pin the base image by version and preferably digest.

Do not use `latest`.

The custom image is an implementation requirement, not a general third-party software build pipeline.

---

# 21. TPM store access from OpenBao

Mount the host PKCS#11 store into OpenBao.

Conceptually:

```text
/var/lib/infrabox/tpm2-pkcs11
       ↓
/var/lib/infrabox/tpm2-pkcs11
```

The OpenBao container must receive:

```text
TPM2_PKCS11_STORE
```

pointing to the mounted store where required by the provider.

The store and TPM object are provisioned by:

```text
tpm2_pkcs11
```

not by the OpenBao role.

---

# 22. OpenBao PKCS#11 PIN handling

OpenBao requires the PKCS#11 user PIN for auto-unseal.

Do not render this PIN into a Git-tracked configuration file.

Prefer a root-protected runtime environment/credential file supplied to the Quadlet service.

For example:

```text
/etc/infrabox/openbao/hsm.env
```

with restrictive permissions and containing the required environment value.

Use the OpenBao environment mechanism:

```text
BAO_HSM_PIN
```

rather than placing the PIN in `config.hcl`.

The PIN must remain available after reboot because unattended auto-unseal is a core MVP requirement.

It must not be logged by Ansible.

---

# 23. OpenBao seal configuration

OpenBao must use a PKCS#11 seal backed by the TPM-created key.

Conceptually:

```hcl
seal "pkcs11" {
  lib           = "/usr/lib64/pkcs11/libtpm2_pkcs11.so"
  token_label   = "InfraBox"
  key_label     = "openbao-unseal"
  mechanism     = "RSA_PKCS_OAEP"
  rsa_oaep_hash = "sha256"
}
```

The exact library location is determined by the final OpenBao image and must be explicit in variables.

Suggested variables:

```yaml
openbao_pkcs11_library:
openbao_pkcs11_token_label:
openbao_pkcs11_key_label:
openbao_pkcs11_mechanism:
openbao_pkcs11_rsa_oaep_hash:
```

The seal key must exist before OpenBao initialization.

OpenBao must not be expected to create the PKCS#11 key itself.

---

# 24. OpenBao storage

Use OpenBao integrated Raft storage even on the single-node MVP.

Do not use the deprecated file storage backend.

Persistent location:

```text
/srv/infrabox/openbao/
```

The single-node implementation does not require HA.

The choice of Raft makes the storage model compatible with future expansion without redesigning the initial storage backend.

---

# 25. OpenBao role

Role:

```text
openbao
```

Prefix:

```text
openbao_
```

OpenBao runs through Podman + Quadlet.

The role owns runtime configuration only.

It does NOT own:

```text
TPM provisioning
PKCS#11 key creation
RootCA creation
intermediate CA creation
leaf certificate issuance
leaf certificate rotation
OpenBao Agent
```

The role supports two explicit listener modes.

Bootstrap:

```yaml
openbao_tls_enabled: false
```

Production:

```yaml
openbao_tls_enabled: true
```

No automatic transition is permitted.

---

# 26. OpenBao bootstrap listener

When:

```yaml
openbao_tls_enabled: false
```

OpenBao exposes HTTP only to the InfraBox host.

Conceptually:

```text
127.0.0.1:8200
       ↓
OpenBao container
```

It must NOT be reachable from:

```text
external networks
managed infrastructure
nginx
ordinary application containers
```

PKCS#11 auto-unseal remains enabled even while the listener is temporarily HTTP.

HTTP bootstrap mode concerns transport only.

It does not mean using a different seal mechanism.

---

# 27. Initial OpenBao initialization

`openbao_bootstrap` initializes OpenBao only after:

```text
TPM exists
PKCS#11 store exists
PKCS#11 token exists
OpenBao seal key exists
OpenBao has started with seal "pkcs11"
```

Initialization is therefore:

```text
TPM-backed PKCS#11
       ↓
OpenBao start
       ↓
bao operator init
```

Do not create normal Shamir unseal keys as the operational unseal mechanism.

With auto-unseal configured, initialization/recovery material must be handled according to OpenBao auto-unseal semantics.

Initialization output is sensitive.

Never print it into normal Ansible logs.

Never commit it to Git.

Automated initialization must save recovery material and the initial administrative token to an explicitly configured protected location on the Ansible controller. Tasks must use `no_log`. Retain the initial root token in that protected controller location for subsequent Ansible administration and recovery; do not automatically revoke it. The OpenBao Agent continues to use its dedicated AppRole.

Do not invent backup/DR functionality around this in the MVP.

---

# 28. OpenBao production TLS listener

When:

```yaml
openbao_tls_enabled: true
```

OpenBao consumes:

```text
/etc/infrabox/pki/openbao/server-chain.crt
/etc/infrabox/pki/openbao/server.key
```

These files are maintained by OpenBao Agent.

If:

```yaml
openbao_tls_enabled: true
```

and required files are absent or invalid:

```text
FAIL
```

Never automatically fall back to plaintext.

After TLS activation, the HTTP bootstrap endpoint disappears.

---

# 29. InfraBox PKI hierarchy

Required hierarchy:

```text
RootCA
├── ServerCA
│   ├── OpenBao ServerCert
│   ├── PostgreSQL ServerCert
│   ├── Redis ServerCert
│   └── nginx ServerCert
│
└── UserCA
    └── UserCert
```

Forbidden:

```text
RootCA -> ordinary ServerCert

RootCA -> ordinary UserCert

ServerCA -> UserCert

UserCA -> ServerCert
```

Use separate PKI mounts:

```text
pki-root/
pki-server/
pki-user/
```

CA private keys remain inside OpenBao.

---

# 30. Certificate lifetimes

Default server leaf TTL:

```yaml
openbao_bootstrap_server_certificate_ttl: 336h
```

That is 14 days.

Exact TTL remains configurable.

Lifetime hierarchy:

```text
RootCA       longest
ServerCA     shorter
UserCA       shorter
ServerCert   14 days by default
UserCert     short-lived
```

RootCA must only sign intermediate CAs.

---

# 31. openbao_bootstrap role

Role:

```text
openbao_bootstrap
```

Prefix:

```text
openbao_bootstrap_
```

Responsibilities:

```text
initialize OpenBao if explicitly requested and uninitialized

enable required auth methods

enable KV where required

create RootCA

create ServerCA

create UserCA

create ServerCA issuance role

create UserCA issuance role

create OpenBao Agent AppRole

create OpenBao Agent policy

export public RootCA certificate
```

It does NOT own the leaf-certificate lifecycle.

It does NOT periodically issue:

```text
OpenBao certificate
PostgreSQL certificate
Redis certificate
nginx certificate
```

That belongs to OpenBao Agent. An explicit exception permits Ansible-assisted recovery of expired certificates, as specified in section 89.

---

# 32. PKI bootstrap idempotency

Repeated execution must never recreate:

```text
RootCA
ServerCA
UserCA
```

Required pattern:

```text
resource exists?
    yes -> verify/configure
    no  -> create
```

CA private keys must never leave OpenBao storage.

Export only the public RootCA certificate:

```text
/etc/infrabox/pki/root-ca.crt
```

---

# 33. OpenBao Agent authentication

Use a dedicated AppRole:

```text
infrabox-openbao-agent
```

Its policy permits only what the certificate agent needs.

Allowed:

```text
issue certificates through ServerCA role
read required public CA information
```

Forbidden:

```text
RootCA signing
ServerCA signing
UserCA issuance
OpenBao administration
token administration
arbitrary KV access
```

The Agent must not use the initial root/admin token during normal operation.

AppRole credentials must not exist in Git.

---

# 34. openbao_agent role

Role:

```text
openbao_agent
```

Prefix:

```text
openbao_agent_
```

OpenBao Agent runs natively through systemd.

Responsibilities:

```text
install pinned OpenBao Agent binary

configure Auto-Auth

configure certificate templates

request initial server certificates

render certificate/key/chain files

automatically rotate certificates

trigger narrowly scoped service reloads
```

Ansible configures certificate lifecycle machinery.

OpenBao Agent performs routine certificate renewal. An Ansible re-run must also repair expired certificates after downtime, as specified in section 89.

---

# 35. OpenBao Agent addresses

Initial bootstrap configuration:

```yaml
openbao_agent_openbao_address: http://127.0.0.1:8200
```

Final production configuration:

```yaml
openbao_agent_openbao_address: >-
  https://openbao.{{ infrabox_internal_domain }}:8200
```

After switching to HTTPS, the Agent must validate OpenBao against:

```text
/etc/infrabox/pki/root-ca.crt
```

Never use production settings equivalent to:

```text
tls_skip_verify=true
insecure=true
```

---

# 36. OpenBao Agent certificate definitions

Default managed server certificates:

```yaml
openbao_agent_certificates:

  - name: openbao
    common_name: "openbao.{{ infrabox_internal_domain }}"

  - name: postgresql
    common_name: "postgresql.{{ infrabox_internal_domain }}"

  - name: redis
    common_name: "redis.{{ infrabox_internal_domain }}"

  - name: nginx
    common_name: "{{ infrabox_domain }}"
    alt_names:
      - "git.{{ infrabox_domain }}"
      - "netbox.{{ infrabox_domain }}"
      - "vault.{{ infrabox_domain }}"
      - "grafana.{{ infrabox_domain }}"
```

The actual schema should also support:

```text
ip_sans
ttl
destination
certificate_mode
private_key_mode
reload_unit
```

Do not hard-code certificate subjects inside role tasks.

---

# 37. Automatic certificate rotation

For automatically rotating 14-day server certificates, use the OpenBao Agent template `secret` mechanism against the PKI issuance endpoint with:

```text
generate_lease=true
```

Do NOT base this implementation on `pkiCert`.

The intended behavior is:

```text
issue 14-day certificate

       ↓

OpenBao Agent tracks leased secret TTL

       ↓

new certificate requested at approximately 85% TTL

       ↓

roughly 2 days remain before old certificate expiration
```

Do NOT implement rotation using:

```text
cron
systemd timer
periodic Ansible execution
```

Certificate renewal is continuous OpenBao Agent runtime behavior.

---

# 38. Certificate/key consistency

One certificate/key pair must come from ONE PKI issuance.

Do not call:

```text
pki-server/issue/...
```

independently for:

```text
server.crt
server.key
chain
```

Use one returned secret and render all outputs from that same response.

Conceptually:

```text
one PKI issue request
       │
       ├── certificate
       ├── private_key
       └── ca_chain
```

The resulting files must always be mutually consistent.

---

# 39. Certificate filesystem

Canonical layout:

```text
/etc/infrabox/pki/
├── root-ca.crt
│
├── openbao/
│   ├── server.crt
│   ├── server.key
│   ├── server-chain.crt
│   └── ca-chain.crt
│
├── postgresql/
│   ├── server.crt
│   ├── server.key
│   ├── server-chain.crt
│   └── ca-chain.crt
│
├── redis/
│   ├── server.crt
│   ├── server.key
│   ├── server-chain.crt
│   └── ca-chain.crt
│
└── nginx/
    ├── server.crt
    ├── server.key
    ├── server-chain.crt
    └── ca-chain.crt
```

RootCA private key:

```text
MUST NOT EXIST HERE
```

ServerCA/UserCA private keys:

```text
MUST NOT EXIST HERE
```

They remain inside OpenBao.

---

# 40. Leaf private-key permissions

Do not fix certificate permissions by making private keys world-readable.

Forbidden:

```text
0644 server.key
```

Each consuming service role must establish an explicit access contract for its container/native service.

OpenBao Agent must be able to replace the file atomically.

The application must be able to read it.

Other services must not receive access unnecessarily.

---

# 41. Certificate reloads

After certificate rotation, OpenBao Agent triggers the minimum required runtime operation.

Target behavior:

```text
nginx
    reload

OpenBao
    reload / SIGHUP

PostgreSQL
    reload / SIGHUP

Redis
    use tested certificate reload mechanism where supported;
    otherwise controlled restart
```

Do not restart nginx or PostgreSQL when reload is sufficient.

Reload actions must be hard-coded/allowlisted.

Never construct shell commands using certificate subjects or other untrusted template data.

---

# 42. cacerts role

Role:

```text
cacerts
```

Prefix:

```text
cacerts_
```

This role operates ONLY on the AlmaLinux HOST trust store.

It does not:

```text
talk to OpenBao
issue certificates
configure containers
modify container trust stores
```

Input:

```yaml
cacerts_root_ca_source: "{{ infrabox_root_ca_path }}"
```

Install RootCA at:

```text
/etc/pki/ca-trust/source/anchors/infrabox-root-ca.crt
```

Run:

```text
update-ca-trust extract
```

Verify that host applications trust the RootCA.

If the RootCA source does not exist:

```text
FAIL
```

---

# 43. Container RootCA trust

Container trust is NOT the responsibility of `cacerts`.

Each service role that needs to verify InfraBox TLS endpoints explicitly mounts RootCA.

Canonical container path:

```text
/run/infrabox-ca/root-ca.crt
```

Conceptually:

```text
/etc/infrabox/pki/root-ca.crt
       ↓ read-only
/run/infrabox-ca/root-ca.crt
```

Applications must explicitly be told to use that CA where necessary.

Do not depend on whatever trust store happens to exist in the container image.

---

# 44. PostgreSQL

Role:

```text
postgresql
```

Prefix:

```text
postgresql_
```

PostgreSQL runs via Quadlet.

Use PostgreSQL 15 or newer.

Select one explicitly pinned version compatible with NetBox.

Persistent data:

```text
/srv/infrabox/postgresql
```

No host/public port publication.

PostgreSQL consumes:

```text
/etc/infrabox/pki/postgresql/server-chain.crt
/etc/infrabox/pki/postgresql/server.key
```

PostgreSQL must use TLS.

Final application connections must not use plaintext.

---

# 45. PostgreSQL databases

Create independent databases/users:

```text
gitea
    owner/user: gitea

netbox
    owner/user: netbox

grafana
    owner/user: grafana
```

Credentials must be independent.

The NetBox database owner must have the privileges required for NetBox migrations and required PostgreSQL extensions such as `ltree`.

No application should receive PostgreSQL superuser credentials.

---

# 46. PostgreSQL TLS clients

TLS clients:

```text
Gitea
NetBox
Grafana
```

They connect using:

```text
postgresql.infrabox.internal
```

or the configured equivalent.

Target TLS semantics:

```text
verify-full
```

Meaning:

```text
verify issuing CA
verify hostname
encrypt transport
```

Every client container mounts RootCA.

Do not use final configurations equivalent to:

```text
sslmode=prefer
sslmode=require without CA verification
```

---

# 47. Redis

Role:

```text
redis
```

Prefix:

```text
redis_
```

Redis runs through Quadlet.

It exists as NetBox infrastructure.

No public/host publication of port 6379.

Desired configuration:

```text
plaintext Redis port disabled

TLS Redis port enabled

authentication enabled

server certificate issued by ServerCA
```

Redis consumes:

```text
/etc/infrabox/pki/redis/server-chain.crt
/etc/infrabox/pki/redis/server.key
```

Client-certificate authentication is not required for the MVP.

NetBox authenticates with credentials and verifies the Redis server certificate.

---

# 48. NetBox Redis layout

Use one Redis service.

Use separate logical Redis databases:

```text
tasks
    DB 0

cache
    DB 1
```

Do not use the same logical database for both purposes.

Both NetBox connections use TLS and RootCA validation.

---

# 49. Gitea

Role:

```text
gitea
```

Prefix:

```text
gitea_
```

Gitea runs through Quadlet.

Provide:

```text
Git repositories
Pull Requests
Actions
Package Registry
OCI Registry
```

Enable:

```yaml
gitea_actions_enabled: true
```

Disable public registration by default.

Gitea uses PostgreSQL with full TLS verification.

Gitea mounts:

```text
/run/infrabox-ca/root-ca.crt
```

The Gitea HTTP application endpoint itself may remain plain HTTP behind local nginx.

---

# 50. NetBox

Role:

```text
netbox
```

Prefix:

```text
netbox_
```

NetBox is the InfraBox Source of Truth.

Use a pinned production NetBox container image.

The target NetBox line is:

```text
NetBox 4.7
```

Its dependency baseline requires:

```text
PostgreSQL 15+
Redis 6+
```

Deploy:

```text
NetBox web container
NetBox worker container
```

Do NOT deploy a separate housekeeping container.

NetBox housekeeping as a separate container is obsolete for the targeted NetBox generation.

---

# 51. NetBox responsibility

NetBox initially owns:

```text
sites
locations
devices
virtual machines
clusters
interfaces
IP addresses
prefixes
VLANs
VRFs
relationships
custom fields
config context
```

NetBox Branching is deferred.

No custom NetBox plugin is required for MVP.

NetBox must not become a dependency for bootstrapping the appliance itself.

---

# 52. NetBox dependencies

Both:

```text
netbox
netbox-worker
```

must connect to:

```text
PostgreSQL via verified TLS

Redis tasks via verified TLS

Redis cache via verified TLS
```

Both containers must receive RootCA.

NetBox DB schema migrations must be deterministic and idempotent.

Do not consider:

```text
systemd service started
```

equivalent to:

```text
NetBox ready
```

---

# 53. nginx

Role:

```text
nginx
```

Prefix:

```text
nginx_
```

nginx is native.

It is the public web/TLS edge.

Required vhosts:

```text
git.<infrabox_domain>
netbox.<infrabox_domain>
vault.<infrabox_domain>
grafana.<infrabox_domain>
```

Prometheus stays non-public by default.

nginx consumes:

```text
/etc/infrabox/pki/nginx/server-chain.crt
/etc/infrabox/pki/nginx/server.key
```

Always execute:

```text
nginx -t
```

before reload.

---

# 54. nginx upstreams

These application upstreams may be local HTTP:

```text
nginx -> Gitea
nginx -> NetBox
nginx -> Grafana
```

because the connection never leaves the InfraBox host.

OpenBao is different.

OpenBao production listener is TLS-only.

Therefore:

```text
nginx
   │
   │ HTTPS + CA verification
   ▼
OpenBao
```

nginx must validate the OpenBao ServerCert against InfraBox RootCA.

Do not disable upstream TLS verification for OpenBao.

---

# 55. OpenBao certificate SAN

OpenBao ServerCert must contain the name used by:

```text
OpenBao Agent
nginx upstream verification
host-side administrative clients
```

At minimum:

```text
openbao.<infrabox_internal_domain>
```

If the implementation uses another stable internal name, all clients and certificate definitions must agree on it.

Do not rely on an IP address unless it is explicitly present as an IP SAN.

---

# 56. Gitea Runner

Role:

```text
gitea_runner
```

Prefix:

```text
gitea_runner_
```

Gitea Runner runs inside a Quadlet container.

Reason:

```text
user workflows are potentially hostile
and must not execute directly on InfraBox host
```

The runner container itself is the initial MVP isolation boundary.

---

# 57. Gitea Runner security

Mandatory:

```text
NO /run/podman/podman.sock

NO /var/run/docker.sock

NO --privileged

NO InfraBox host root credentials

NO OpenBao admin credentials

NO production SSH credentials

NO arbitrary host filesystem mounts
```

The runner may allow root INSIDE its own container if needed by workflows.

Container root must not imply InfraBox host root.

Do not solve user build requirements by exposing the host container runtime socket.

---

# 58. Gitea Runner execution model

For the initial MVP, prefer execution of jobs in the runner container's own environment rather than host execution.

This means some workflows expecting a Docker-compatible nested runtime may not yet work.

That limitation is acceptable for MVP.

Document it.

Future architecture may move build runners to dedicated machines.

The role must be designed so the runner can later move to a separate inventory group without redesigning Gitea itself.

---

# 59. Gitea Runner CA trust

The runner communicates with Gitea through the public HTTPS endpoint.

Therefore the runner container must trust InfraBox RootCA.

Mount:

```text
/run/infrabox-ca/root-ca.crt
```

and configure the runner runtime/client to use it.

Do not disable TLS verification to make registration work.

---

# 60. Prometheus

Role:

```text
prometheus
```

Prefix:

```text
prometheus_
```

Prometheus runs through Quadlet.

Scope:

```text
monitor InfraBox itself
```

Persistent data:

```text
/srv/infrabox/prometheus
```

Configure explicit retention.

Prometheus stays internal by default.

Do not add:

```text
OTel Collector
Loki
Alertmanager
```

---

# 61. Grafana

Role:

```text
grafana
```

Prefix:

```text
grafana_
```

Grafana runs through Quadlet.

Grafana MUST use PostgreSQL as its application database.

Do NOT use SQLite.

Database:

```text
grafana
```

Database user:

```text
grafana
```

Connection:

```text
postgresql.infrabox.internal:5432
```

with full certificate and hostname verification.

Grafana container mounts:

```text
/run/infrabox-ca/root-ca.crt
```

Grafana uses Prometheus as its initial datasource.

---

# 62. Application certificate consumers

ServerCert owners:

```text
OpenBao
PostgreSQL
Redis
nginx
```

RootCA client consumers:

```text
OpenBao Agent
nginx when proxying OpenBao
Gitea
Gitea Runner
NetBox
NetBox Worker
Grafana
```

Do not inject RootCA into unrelated containers merely because it exists.

---

# 63. Initial bootstrap procedure

The bootstrap is deliberately multi-pass.

Do not encode the entire process as hidden Ansible state detection.

---

## Bootstrap Phase 1 — inventory

Set:

```yaml
openbao_tls_enabled: false

openbao_agent_openbao_address: http://127.0.0.1:8200
```

Provide protected secret values required for:

```text
TPM2 PKCS#11 token provisioning
OpenBao initialization
initial application credentials
```

---

## Bootstrap Phase 2 — host foundation

Deploy:

```text
packages
chrony
selinux
firewalld
podman
```

Verify before continuing.

---

## Bootstrap Phase 3 — TPM

Deploy:

```text
tpm2_pkcs11
```

Expected result:

```text
/dev/tpmrm0 available

PKCS#11 provider works

InfraBox token exists

openbao-unseal key exists
```

Do not continue if TPM/PKCS#11 verification fails.

---

## Bootstrap Phase 4 — OpenBao HTTP

Deploy:

```text
openbao
```

with:

```yaml
openbao_tls_enabled: false
```

OpenBao already has:

```text
PKCS#11 seal configured
TPM-backed key configured
Raft storage configured
```

Only the network listener is temporarily plaintext.

---

## Bootstrap Phase 5 — initialize OpenBao

Run:

```text
openbao_bootstrap
```

It initializes the server if required.

Verify after initialization:

```text
Initialized = true
Sealed = false
Seal type = pkcs11
```

No manual unseal operation should be required.

---

## Bootstrap Phase 6 — create PKI

`openbao_bootstrap` then creates:

```text
RootCA
ServerCA
UserCA

Server certificate issuance role

User certificate issuance role

OpenBao Agent AppRole/policy
```

It exports:

```text
/etc/infrabox/pki/root-ca.crt
```

---

## Bootstrap Phase 7 — OpenBao Agent over HTTP

Deploy:

```text
openbao_agent
```

using:

```yaml
openbao_agent_openbao_address: http://127.0.0.1:8200
```

The Agent requests initial leaf certificates.

At minimum:

```text
OpenBao ServerCert
PostgreSQL ServerCert
Redis ServerCert
nginx ServerCert
```

Verify OpenBao leaf files before proceeding.

---

## Bootstrap Phase 8 — host CA trust

Run:

```text
cacerts
```

Verify:

```text
InfraBox RootCA installed into AlmaLinux trust store
```

---

## Bootstrap Phase 9 — explicit operator transition

README must now instruct the user to CHANGE inventory:

```yaml
openbao_tls_enabled: true

openbao_agent_openbao_address: >-
  https://openbao.{{ infrabox_internal_domain }}:8200
```

This change is deliberately explicit.

Ansible must NOT make it automatically.

---

## Bootstrap Phase 10 — OpenBao TLS

Run Ansible again.

OpenBao now starts with:

```text
ServerCA-issued certificate
TPM-backed PKCS#11 auto-unseal
TLS listener
```

Plaintext listener disappears.

Verify:

```text
HTTPS works
HTTP no longer works
certificate chain is trusted
OpenBao remains unsealed
```

---

## Bootstrap Phase 11 — Agent HTTPS

Reconfigure/restart OpenBao Agent.

Verify that it now talks to:

```text
https://openbao.<infrabox_internal_domain>:8200
```

with RootCA verification.

OpenBao Agent must continue managing the existing leaf certificates after the transport switch.

---

## Bootstrap Phase 12 — remaining appliance

Run final:

```text
site.yml
```

Deploy:

```text
PostgreSQL
Redis
Gitea
NetBox
NetBox Worker
nginx
Gitea Runner
Prometheus
Grafana
```

---

# 64. Final site.yml

```yaml
---
- ansible.builtin.import_playbook: system.yml
- ansible.builtin.import_playbook: platform.yml
- ansible.builtin.import_playbook: pki.yml
- ansible.builtin.import_playbook: services.yml
- ansible.builtin.import_playbook: edge.yml
- ansible.builtin.import_playbook: ci.yml
- ansible.builtin.import_playbook: observability.yml
- ansible.builtin.import_playbook: verify.yml
```

This represents final desired state.

It is NOT the command used blindly at the very beginning of a clean installation.

---

# 65. system.yml

```text
packages
chrony
selinux
firewalld
```

Example:

```yaml
---
- name: Configure InfraBox operating system
  hosts: infrabox
  become: true

  roles:
    - role: packages
      tags: [packages]

    - role: chrony
      tags: [chrony]

    - role: selinux
      tags: [selinux]

    - role: firewalld
      tags: [firewalld]
```

---

# 66. platform.yml

Order:

```text
Podman
TPM2 PKCS#11
```

Example:

```yaml
---
- name: Configure InfraBox platform
  hosts: infrabox
  become: true

  roles:
    - role: podman
      tags: [podman]

    - role: tpm2_pkcs11
      tags: [tpm2_pkcs11]
```

---

# 67. pki.yml

Final-state roles:

```text
openbao
openbao_bootstrap
openbao_agent
cacerts
```

During the first installation they are invoked according to the documented bootstrap phases.

Do not implement automatic HTTP/TLS phase detection.

---

# 68. services.yml

Order:

```text
PostgreSQL
Redis
Gitea
NetBox
```

Example:

```yaml
---
- name: Configure InfraBox application services
  hosts: infrabox
  become: true

  roles:
    - role: postgresql
      tags: [postgresql]

    - role: redis
      tags: [redis]

    - role: gitea
      tags: [gitea]

    - role: netbox
      tags: [netbox]
```

---

# 69. edge.yml

Contains:

```text
nginx
```

nginx may only start after its certificate exists.

---

# 70. ci.yml

Contains:

```text
gitea_runner
```

This is user-facing InfraBox CI.

It is NOT InfraBox development CI.

---

# 71. observability.yml

Contains only:

```text
Prometheus
Grafana
```

Order:

```text
Prometheus
Grafana
```

Grafana additionally depends on PostgreSQL.

---

# 72. Dependency graph

```text
AlmaLinux
   │
   ├── Podman
   │
   └── TPM2
          │
          ▼
     tpm2-pkcs11
          │
          ▼
     OpenBao HTTP
      + PKCS11 seal
          │
          ▼
     operator init
          │
          ▼
    automatic unseal
          │
          ▼
 openbao_bootstrap
      │
      ├── RootCA
      ├── ServerCA
      ├── UserCA
      └── Agent AppRole
               │
               ▼
        OpenBao Agent
               │
         ┌─────┼──────────────┐
         ▼     ▼              ▼
      OpenBao PostgreSQL     Redis
       cert     cert          cert
         │        │             │
         │        │             │
         ▼        ▼             ▼
    OpenBao TLS PostgreSQL TLS Redis TLS
                    │             │
             ┌──────┼───────┐     │
             ▼      ▼       ▼     │
           Gitea  NetBox  Grafana │
                    ▲             │
                    └─────────────┘

OpenBao Agent
      │
      └── nginx cert
              │
              ▼
             nginx
              │
        ┌─────┼─────┐
        ▼     ▼     ▼
      Gitea NetBox Grafana
              │
              └── HTTPS -> OpenBao
```

---

# 73. TPM reboot behavior

After OpenBao has been initialized once:

```text
host reboot
    ↓
systemd
    ↓
Podman
    ↓
OpenBao container
    ↓
PKCS#11 provider
    ↓
TPM2
    ↓
automatic unseal
```

Expected:

```text
no human unseal action
```

This is mandatory for MVP acceptance.

---

# 74. Controlled restart test

Test both:

```text
systemctl restart openbao.service
```

and:

```text
host reboot
```

After each operation verify:

```text
OpenBao starts
OpenBao automatically unseals
OpenBao HTTPS becomes healthy
OpenBao Agent reconnects
certificate issuance remains functional
```

Do not declare TPM auto-unseal complete based solely on initial setup.

---

# 75. Health checks

`systemctl is-active` alone is insufficient.

Minimum application checks:

```text
OpenBao
    HTTPS /v1/sys/health
    initialized
    unsealed
    PKCS11 seal type

OpenBao Agent
    process active
    Auto-Auth succeeds
    certificate files valid

PostgreSQL
    pg_isready
    verified TLS connection

Redis
    authenticated TLS PING

Gitea
    HTTP health/readiness

NetBox
    web health
    worker health

nginx
    nginx -t
    HTTPS request

Prometheus
    readiness endpoint

Grafana
    health endpoint
    PostgreSQL backend
```

---

# 76. verify.yml

Verify at least:

```text
chrony healthy

SELinux enforcing

firewalld active

Podman operational

podman.socket disabled unless explicitly enabled

infrabox.network exists


TPM2:
    /dev/tpmrm0 available
    PKCS11 provider loadable
    InfraBox token exists
    OpenBao seal key exists


OpenBao:
    initialized
    seal type PKCS11
    sealed=false
    TLS enabled in final state
    plaintext bootstrap endpoint absent
    ServerCert valid


PKI:
    RootCA exists
    ServerCA exists
    UserCA exists

    RootCA in host trust

    OpenBao certificate chain valid
    PostgreSQL certificate chain valid
    Redis certificate chain valid
    nginx certificate chain valid


OpenBao Agent:
    running
    using HTTPS in final state
    Auto-Auth works
    managed certificates valid


PostgreSQL:
    TLS enabled
    gitea DB exists
    netbox DB exists
    grafana DB exists


Redis:
    TLS enabled
    plaintext disabled
    authentication required


Gitea:
    healthy
    Actions enabled
    PostgreSQL verified TLS works


Gitea Runner:
    registered
    operational
    RootCA trusted
    no host runtime socket mounted


NetBox:
    web healthy
    worker healthy
    PostgreSQL verified TLS
    Redis tasks verified TLS
    Redis cache verified TLS


nginx:
    nginx -t
    HTTPS valid
    OpenBao upstream certificate verification enabled


Prometheus:
    healthy


Grafana:
    healthy
    PostgreSQL backend active
```

---

# 77. X.509 verification

Do actual cryptographic validation.

Check:

```text
OpenBao ServerCert -> ServerCA -> RootCA

PostgreSQL ServerCert -> ServerCA -> RootCA

Redis ServerCert -> ServerCA -> RootCA

nginx ServerCert -> ServerCA -> RootCA
```

Also verify:

```text
not expired
expected SAN
serverAuth EKU
private key matches certificate
```

Do not merely test that certificate files exist.

---

# 78. Certificate rotation acceptance test

Production default:

```text
14 days
```

For automated testing, temporarily configure a substantially shorter TTL.

Verify:

```text
initial certificate issued

service works

OpenBao Agent obtains replacement before expiry

certificate serial/fingerprint changes

new key matches new certificate

reload/restart hook executes

service remains available

new connection observes new certificate
```

The production TTL remains 14 days.

---

# 79. Idempotency acceptance

Required sequence:

```text
clean AlmaLinux 10

perform documented initial bootstrap

run final site.yml

run final site.yml again

expect no unexpected changes

run verify.yml

reboot host

run verify.yml again
```

Normal Ansible execution must NOT:

```text
regenerate TPM seal key

reinitialize OpenBao

regenerate RootCA

regenerate ServerCA

regenerate UserCA

rotate valid leaf certificates
```

Leaf rotation belongs to OpenBao Agent.

---

# 80. Secrets rules

Never commit:

```text
TPM2 PKCS11 SO PIN
TPM2 PKCS11 user PIN
OpenBao initial root token
OpenBao recovery material
AppRole SecretID
database passwords
Redis credentials
Gitea runner registration secret
```

Use protected Ansible inputs.

Supported initial mechanisms may include:

```text
Ansible Vault
environment variables
protected extra-vars
root-owned local secret files
```

Do not invent a new secrets platform to bootstrap the secrets platform.

Tasks processing sensitive values must use `no_log` appropriately.

---

# 81. Version pinning

No production variable may use:

```text
latest
stable
floating major-only tag
```

Pin:

```text
OpenBao
OpenBao Agent
OpenBao HSM base image
tpm2-pkcs11 package expectations
PostgreSQL
Redis
Gitea
Gitea Runner
NetBox
Prometheus
Grafana
```

OpenBao MVP baseline:

```yaml
openbao_version: "2.6.2"
```

The OpenBao 2.7 PKCS#11 plugin migration is outside this MVP.

Future upgrade work may move from built-in PKCS#11 to the external KMS plugin explicitly.

---

# 82. README.md requirements

README is a required deliverable.

It must clearly document:

```text
hardware prerequisites

TPM 2.0 requirement

AlmaLinux 10 requirement

inventory configuration

secret inputs

TPM provisioning

PKCS11 token/key initialization

OpenBao HTTP bootstrap

OpenBao initialization

PKI bootstrap

OpenBao Agent startup over HTTP

initial certificate verification

cacerts installation

manual inventory change:
    openbao_tls_enabled=false -> true

manual Agent URL change:
    http://... -> https://...

final site.yml

verify.yml

reboot test

certificate rotation test
```

A new operator should not need to inspect Ansible tasks to discover the bootstrap sequence.

---

# 83. README security warning

README must prominently state:

```text
OpenBao plaintext HTTP exists only for initial localhost bootstrap.

After OpenBao Agent has created the OpenBao ServerCert,
the operator must enable openbao_tls_enabled and change
OpenBao Agent to the HTTPS endpoint.

InfraBox must not remain permanently in HTTP bootstrap mode.
```

---

# 84. README TPM warning

Document:

```text
Do not clear the TPM after OpenBao initialization.

Do not delete or recreate the tpm2-pkcs11 token or
openbao-unseal key as part of normal maintenance.

These operations can make the existing OpenBao storage
unusable.

TPM-loss disaster recovery is outside the MVP.
```

Do not attempt to implement backup/TPM recovery automatically.

---

# 85. Implementation order for Codex

Implement in this sequence:

```text
Phase 1
    repository skeleton
    inventories
    lifecycle/tag conventions

Phase 2
    packages
    chrony
    selinux
    firewalld

Phase 3
    podman
    quadlet helper
    infrabox.network

Phase 4
    tpm2_pkcs11
    TPM detection
    token creation
    seal key creation
    PKCS11 verification

Phase 5
    OpenBao custom HSM/TPM-capable image
    OpenBao Raft runtime
    HTTP bootstrap listener
    PKCS11 seal

Phase 6
    openbao_bootstrap
    initialization
    RootCA
    ServerCA
    UserCA
    Agent AppRole/policy
    RootCA export

Phase 7
    openbao_agent
    initial certificate issuance
    leased certificate rotation
    reload hooks

Phase 8
    cacerts

Phase 9
    OpenBao TLS final mode
    Agent HTTPS final mode

Phase 10
    PostgreSQL TLS
    Redis TLS

Phase 11
    Gitea

Phase 12
    NetBox
    NetBox Worker

Phase 13
    nginx

Phase 14
    Gitea Runner

Phase 15
    Prometheus
    Grafana with PostgreSQL

Phase 16
    verify.yml
    idempotency testing
    certificate rotation testing
    OpenBao restart test
    full host reboot test

Phase 17
    README cleanup
```

Each phase must leave the implemented portion verifiable.

Do not implement every component in one untestable batch.

---

# 86. Explicitly deferred

Do NOT implement in this MVP:

```text
Backup
Restore
Off-site backup encryption
TPM-loss disaster recovery

OpenTelemetry Collector
Loki
Alertmanager

InfraBox self-CI

NetBox Branching

Infrahub
Nautobot

Argo CD
Kubernetes management

external Linux management

third-party software pipeline

RPM repository workflow

AWX
Terraform

HA
multi-node OpenBao
multi-node InfraBox

OpenBao 2.7 KMS plugin migration

AI agent
custom InfraBox portal

dedicated CI runner nodes
```

Do not opportunistically implement deferred functionality.

---

# 87. Definition of Done

InfraBox MVP is complete when a clean AlmaLinux 10 host with physical or virtual TPM 2.0 can be provisioned using the documented Ansible procedure and reaches this state:

```text
SELinux enforcing

firewalld active

chronyd operational

Podman operational

Podman API socket disabled by default


TPM2 detected

tpm2-pkcs11 configured

InfraBox PKCS11 token created

OpenBao TPM-backed seal key exists


OpenBao 2.6.2 HSM-capable container running through Quadlet

OpenBao uses Raft storage

OpenBao uses TPM-backed PKCS11 auto-unseal

OpenBao automatically unseals after container restart

OpenBao automatically unseals after host reboot

OpenBao production listener uses TLS only


RootCA exists

ServerCA exists

UserCA exists


OpenBao Agent runs natively

OpenBao Agent authenticates without admin/root token

OpenBao Agent communicates with OpenBao over verified HTTPS
in final state

OpenBao Agent automatically rotates ServerCerts

default ServerCert TTL is 14 days


RootCA is installed into AlmaLinux host trust by cacerts

cacerts does not configure container trust


PostgreSQL runs through Quadlet

PostgreSQL uses ServerCA-issued certificate

PostgreSQL has independent:
    Gitea DB
    NetBox DB
    Grafana DB


Redis runs through Quadlet

Redis TLS enabled

Redis plaintext disabled


Gitea runs through Quadlet

Gitea uses PostgreSQL with full TLS verification

Gitea Actions enabled


NetBox runs through Quadlet

NetBox Worker runs through Quadlet

NetBox uses PostgreSQL with TLS verification

NetBox uses Redis tasks/cache with TLS verification


nginx runs natively

nginx uses ServerCA-issued certificate

nginx verifies OpenBao TLS upstream


Gitea Runner runs through Quadlet

Gitea Runner is isolated from host runtime

Gitea Runner has no host Podman/Docker socket


Prometheus runs through Quadlet

Grafana runs through Quadlet

Grafana uses PostgreSQL with full TLS verification


No OpenTelemetry Collector

No Loki

No Alertmanager

No backup implementation


all externally installed versions are pinned

all role variables are properly prefixed

all roles follow install/configure/service/verify convention

second final-state Ansible run is idempotent

certificate renewal requires no Ansible execution

host reboot requires no manual OpenBao unseal

verify.yml succeeds after reboot
```

---

# 88. Core implementation invariants

If an implementation detail is ambiguous, these invariants take precedence:

```text
1. SELinux stays enforcing.

2. Application services are containerized unless there is an
   explicit host-integration reason not to containerize them.

3. TPM2 + tpm2-pkcs11 is the OpenBao auto-unseal mechanism.

4. OpenBao is initialized with PKCS11 auto-unseal already enabled.

5. Do not initialize with Shamir and migrate later.

6. Do not recreate TPM PKCS11 objects during normal Ansible runs.

7. OpenBao HTTP is temporary and localhost-only.

8. HTTP -> TLS is an explicit operator configuration change.

9. Never automatically fall back from OpenBao TLS to HTTP.

10. RootCA signs only intermediate CAs.

11. ServerCA issues server certificates.

12. UserCA issues user certificates.

13. Server leaf certificates live for 14 days by default.

14. OpenBao Agent owns leaf-certificate lifecycle.

15. Ansible does not periodically renew certificates.

16. OpenBao Agent must rotate certificates before expiry.

17. cacerts manages only AlmaLinux host trust.

18. Container CA trust belongs to each consuming application role.

19. PostgreSQL serves Gitea, NetBox and Grafana using separate
    databases and credentials.

20. PostgreSQL application connections use verified TLS.

21. Redis traffic used by NetBox is encrypted and authenticated.

22. Gitea Runner is a potentially hostile execution component.

23. Gitea Runner never receives the host Podman/Docker socket.

24. Root inside a Runner workload must not equal root on the
    InfraBox host.

25. Persistent state does not live in container writable layers.

26. Do not use latest/floating image versions.

27. Do not implement deferred backup/DR functionality.

28. Prefer explicit failure over an automatic security downgrade.

29. Normal reboot must automatically bring OpenBao back
    unsealed through TPM2.

30. A normal Ansible run must never recreate CA or TPM root
    cryptographic material.
```

This document is the implementation contract for the InfraBox MVP.

---

# 89. Operator decisions and remaining design questions

These decisions amend the earlier sections wherever they conflict.

## Deployment target and DNS

Initial target:

```yaml
ansible_host: 192.168.32.206
ansible_user: almalinux
infrabox_domain: infrabox1.krglv.com
```

The target is a VM. A virtual TPM is acceptable and must pass the same
provisioning, restart, and reboot acceptance checks as a physical TPM.

DNS for `*.infrabox1.krglv.com` is already configured. Required service names:

```text
git.infrabox1.krglv.com
netbox.infrabox1.krglv.com
vault.infrabox1.krglv.com
grafana.infrabox1.krglv.com
```

Host-side resolution of OpenBao's internal name must be explicitly configured
and verified; public wildcard DNS does not define this internal naming contract.

## Controller secrets and administrative access

Store initialization output, recovery material, and the initial root token in
a protected, explicitly configured directory on the Ansible controller.
Do not commit these files or print their contents in Ansible output.

Retain the initial root token on the controller for subsequent Ansible
administration and recovery, including expired certificates and Agent SecretIDs.
Do not automatically revoke it. Read it from the protected controller location
only for tasks requiring it, with sensitive task inputs and output protected by
`no_log`. Do not persist it in appliance runtime configuration or supply it to
the OpenBao Agent, applications, or runner jobs. The Agent continues to use its
dedicated AppRole with rotated SecretIDs.

The choice of secret-input mechanism and controller destination path remains
configurable; the operator has selected the controller as the storage location.

## Expired certificate recovery

An Ansible re-run must repair expired leaf certificates, including OpenBao's
own listener certificate, and restore normal Agent operation. Routine renewal
remains the Agent's responsibility and requires no Ansible execution.

The recovery path must work when the Agent cannot connect because OpenBao's
certificate has expired, including simultaneous Agent SecretID expiry.
It must run before normal final-state HTTPS readiness checks would abort the
playbook. It must preserve existing CA and TPM keys and must not reinitialize
OpenBao, automatically enable HTTP, or disable TLS verification.

Before implementation, define and validate an authenticated local recovery
mechanism that does not depend on the expired listener certificate. The exact
mechanism is unresolved; this requirement does not authorize a transport
security downgrade.

Acceptance must include downtime beyond the leaf certificate lifetime followed
by an Ansible re-run, restoration of verified HTTPS, and resumed Agent renewal.

## Agent SecretID lifecycle

Use a rotated Agent AppRole SecretID. Define its lifetime, rotation mechanism,
secure delivery, and replacement ordering. Unattended rotation must continue
during normal operation; if the SecretID expires, an Ansible re-run must repair
it using independent administrative authentication.

Revoke superseded credentials after successful replacement. Verify both normal
rotation and recovery after expiry, including expiry during appliance downtime.

## Runner network access

Jobs may access NetBox through its public HTTPS endpoint and Gitea as required
for checkout, registration, and artifact/package operations.

Jobs must not access internal backend services such as PostgreSQL or Redis.
Do not attach the runner directly to the shared backend network. Implement and
test network isolation, including attempts through host addresses and service
aliases. NetBox access still requires application authorization.

Broader outbound access policy remains configurable. Do not grant access to
OpenBao administration or other internal services merely because they share
the appliance host.

## Git access and local accounts

Support both HTTPS and SSH Git access. Keep appliance administrative SSH on
port 22. Publish Gitea SSH on port 2222 and allow that port through firewalld.
Configure Gitea to advertise `git.infrabox1.krglv.com` and SSH port 2222 in
clone URLs. Verify both HTTPS and SSH Git access.

Gitea, NetBox, and Grafana use local administrator accounts for this MVP.
No SSO or user-certificate login integration is required. The UserCA remains
part of the specified PKI hierarchy, with no application integration required.

## Observability scope

Install Prometheus and Grafana, configure Grafana's PostgreSQL backend and
Prometheus datasource, and verify service health. No dashboard provisioning or
additional exporters are required for the MVP. Keep retention explicit and
Prometheus non-public as already specified.


## Development TPM key-size decision

The operator approved RSA-3072 for the development VM at 192.168.32.206
after RSA-4096 provisioning failed and TPM parameter checks accepted RSA-3072.
Set `tpm2_pkcs11_key_bits: 3072` explicitly in development inventory. Keep
RSA-4096 as the role default. Never automatically downgrade the key size.

## Agent credential rotation implementation

To implement the requested automatic SecretID rotation without a native root
token, the Agent policy additionally permits creating SecretIDs and destroying
SecretID accessors for `infrabox-openbao-agent` only. This is a narrow exception
to the original certificate-only policy. It grants no control over other roles.
A native hourly timer checks whether the seven-day SecretID is more than one day
old, verifies a replacement login, publishes it, and destroys the old accessor.
This timer rotates credentials only; certificate rotation remains Agent-driven.

A mode-0600 Unix listener in a private host directory provides authenticated
Ansible administration and expired-certificate recovery. It is not published
over TCP or mounted into applications or the runner. Network HTTP-to-TLS
transition remains an explicit operator inventory change.

# InfraBox — OpenClaw Integration Implementation Plan

## 1. Objective

Extend the already implemented InfraBox MVP with OpenClaw.

This is an incremental implementation.

Do NOT rebuild or redesign the existing InfraBox implementation unless explicitly required by this document.

The existing InfraBox already provides:

```text
AlmaLinux 10
systemd
SELinux enforcing
firewalld
Podman + Quadlet

TPM2 + tpm2-pkcs11
OpenBao with TPM-backed auto-unseal
RootCA
ServerCA
UserCA
OpenBao Agent for certificate lifecycle
cacerts

PostgreSQL
Redis
Gitea
Gitea Runner
NetBox
NetBox Worker

nginx

Prometheus
Grafana
```

Add:

```text
OpenClaw Gateway
```

as the AI/agent layer of InfraBox.

---

# 2. Resulting architecture

```text
InfraBox
│
├── Infrastructure
│   ├── Podman
│   ├── TPM2
│   └── PKI
│
├── Platform
│   ├── OpenBao
│   ├── PostgreSQL
│   ├── Redis
│   ├── Gitea
│   └── NetBox
│
├── Execution
│   └── Gitea Runner
│
├── Observability
│   ├── Prometheus
│   └── Grafana
│
├── Agent
│   └── OpenClaw Gateway
│
└── Edge
    └── nginx
```

OpenClaw runs as a Podman container managed by Quadlet.

---

# 3. Scope

IN scope:

```text
OpenClaw Gateway
OpenClaw Ansible role
agent.yml
Podman Quadlet deployment
persistent OpenClaw state
persistent workspace
nginx reverse proxy
WebSocket proxying
InfraBox RootCA trust
Gateway authentication
OpenBao Vault SecretRefs integration
dedicated least-privilege OpenBao policy
dedicated periodic OpenBao token
automatic token renewal using systemd timer
health/readiness verification
basic resource limits
optional HTTP/HTTPS proxy configuration
```

OUT of scope:

```text
direct SSH access to managed machines
Kubernetes management
NetBox write automation
Gitea PR automation
Ansible execution from OpenClaw
host Podman control
host Docker control
nested OpenClaw sandbox
dedicated sandbox workers
production infrastructure credentials
AI-driven infrastructure changes
chat-channel integrations
custom OpenClaw plugins
MCP integrations
model-provider credential provisioning
```

---

# 4. Important architecture change

Do NOT create:

```text
openbao-agent@openclaw.service
OpenClaw AppRole
OpenBao Agent token sink
AppRole RoleID/SecretID for OpenClaw
```

The existing:

```text
openbao_agent
```

component remains responsible only for the existing certificate lifecycle.

OpenClaw authentication to OpenBao uses:

```text
Ansible
   │
   │ initial credential provisioning
   ▼
OpenBao periodic orphan token
   │
   ├───────────────┐
   │               │
   ▼               ▼
OpenClaw       systemd timer
Vault plugin       │
   │               │
   │          bao token renew
   │               │
   └───────► OpenBao
```

OpenClaw talks directly to OpenBao.

There is no OpenBao Agent in this request path.

---

# 5. Why periodic token

The OpenClaw Vault plugin accepts an existing Vault/OpenBao token but does not own the lifecycle of a token supplied this way.

OpenBao periodic service tokens are suitable because:

```text
they are renewable

every successful renewal resets TTL to their configured period

they can continue indefinitely while actively renewed

they can be orphan tokens

they can be restricted to one narrow policy
```

Do NOT configure:

```text
explicit_max_ttl
```

for the OpenClaw periodic token.

A periodic token without an explicit maximum TTL remains usable indefinitely as long as renewal continues.

---

# 6. Token lifetime

Default:

```yaml
openclaw_openbao_token_period: 168h
```

This is:

```text
7 days
```

Renew it twice per day.

Default calendar:

```yaml
openclaw_openbao_token_renew_calendar: "*-*-* 00,12:00:00"
```

The large safety margin is intentional:

```text
token period:       7 days
renew attempt:      every 12 hours
normal margin:      ~6.5 days
```

The token is deliberately longer-lived than the 14-day server certificates are operationally relevant to this mechanism; the two lifecycles are independent.

---

# 7. Seven-day outage limitation

If InfraBox remains powered off or unable to contact OpenBao for more than the token period:

```text
periodic token expires
```

The systemd renewer cannot recover it because an expired token cannot renew itself.

Recovery is:

```text
run Ansible OpenClaw role
        ↓
detect invalid token
        ↓
issue replacement periodic token
        ↓
replace token file
        ↓
restart OpenClaw
```

This is acceptable for the MVP.

Do NOT give the systemd renewer privileged OpenBao credentials merely so that it can create replacement tokens.

---

# 8. Preserve existing InfraBox architecture

Keep existing conventions:

```text
SELinux enforcing

Podman + Quadlet for applications

native nginx

native OpenBao Agent for certificate lifecycle

host-only cacerts role

container CA trust owned by consuming role

role-prefixed variables

install/configure/service/verify lifecycle
```

Do NOT introduce:

```text
Docker daemon
docker-compose
Kubernetes
system-wide Podman socket
second CA
second reverse proxy
generic agent role
```

---

# 9. New repository objects

Add:

```text
agent.yml

roles/
└── openclaw/
    ├── defaults/
    │   └── main.yml
    ├── handlers/
    │   └── main.yml
    ├── tasks/
    │   ├── main.yml
    │   ├── install.yml
    │   ├── configure.yml
    │   ├── token.yml
    │   ├── service.yml
    │   └── verify.yml
    └── templates/
        ├── openclaw.json.j2
        ├── openclaw.env.j2
        ├── openclaw-token-renew.j2
        ├── openclaw-token-renew.service.j2
        └── openclaw-token-renew.timer.j2
```

Do NOT create another Ansible role for token renewal.

The token lifecycle belongs to the OpenClaw integration.

---

# 10. Required existing-code changes

Expected changes:

```text
site.yml
    add agent.yml

openbao_bootstrap
    add infrabox-openclaw policy
    add infrabox-openclaw token role

nginx
    add OpenClaw vhost

openbao_agent certificate definitions
    add claw.<infrabox_domain>
    to existing nginx ServerCert SANs

verify.yml
    add OpenClaw checks
    add OpenClaw token-renewal checks
```

Do NOT modify the existing certificate OpenBao Agent architecture.

---

# 11. agent.yml

Create:

```yaml
---
- name: Configure InfraBox agent services
  hosts: infrabox
  become: true

  roles:
    - role: openclaw
      tags:
        - openclaw
```

Add to final `site.yml`.

Prefer:

```yaml
- ansible.builtin.import_playbook: system.yml
- ansible.builtin.import_playbook: platform.yml
- ansible.builtin.import_playbook: pki.yml
- ansible.builtin.import_playbook: services.yml
- ansible.builtin.import_playbook: ci.yml
- ansible.builtin.import_playbook: observability.yml
- ansible.builtin.import_playbook: agent.yml
- ansible.builtin.import_playbook: edge.yml
- ansible.builtin.import_playbook: verify.yml
```

If the implemented InfraBox ordering differs, add `agent.yml` with minimum churn.

Required dependency:

```text
OpenBao + PKI
    before OpenClaw

OpenClaw periodic token
    before OpenClaw starts
```

---

# 12. OpenClaw role conventions

Role:

```text
openclaw
```

Prefix:

```text
openclaw_
```

Lifecycle:

```text
install
configure
service
verify
```

All OpenClaw-owned variables must begin:

```text
openclaw_
```

---

# 13. Version pinning

Required:

```yaml
openclaw_image:
openclaw_version:
```

Never use:

```text
latest
stable
main
master
```

Support immutable digest pinning where practical:

```yaml
openclaw_image_digest:
```

Prefer production image references equivalent to:

```text
image:version@sha256:...
```

Do not build OpenClaw from source unless required.

---

# 14. Persistent layout

Use:

```text
/etc/infrabox/openclaw/
├── openclaw.json
├── openclaw.env
└── secrets/
    └── vault-token

/srv/infrabox/openclaw/
├── state/
└── workspace/
```

Configuration:

```text
/etc/infrabox/openclaw
```

Persistent application state:

```text
/srv/infrabox/openclaw
```

The token is installation/runtime credential state and belongs under:

```text
/etc/infrabox/openclaw/secrets/
```

not `/srv`.

---

# 15. Token directory mount

Do NOT bind-mount only:

```text
/etc/infrabox/openclaw/secrets/vault-token
```

as an individual file.

Mount the directory:

```text
/etc/infrabox/openclaw/secrets/
        ↓ read-only
/run/openclaw-secrets/
```

This avoids inode/bind-mount problems if Ansible later performs an atomic replacement of the token file.

OpenClaw sees:

```text
/run/openclaw-secrets/vault-token
```

---

# 16. OpenClaw state mounting

Do not rely on the container writable layer.

Persist:

```text
/srv/infrabox/openclaw/state
/srv/infrabox/openclaw/workspace
```

Do not expose unrelated InfraBox storage.

In particular do not mount:

```text
/etc/infrabox
/srv/infrabox/gitea
/srv/infrabox/netbox
/srv/infrabox/openbao
InfraBox Ansible repository
host SSH directories
```

---

# 17. Permissions

Secret material must not be world-readable.

At minimum:

```text
openclaw config directory:
    restricted

openclaw state:
    0700-equivalent

openclaw.json:
    0600-equivalent

vault-token:
    readable only by root and the
    explicitly authorized OpenClaw container UID/GID
```

Establish an explicit UID/GID access contract for the pinned OpenClaw image.

Do NOT solve access problems using:

```text
chmod 0644 vault-token
```

The host renewal service runs as root and can read the same token file.

---

# 18. Container deployment

OpenClaw runs through the existing Quadlet helper.

Conceptual unit:

```text
openclaw.service
```

Requirements:

```text
pinned image

persistent state

persistent workspace

InfraBox RootCA mount

OpenBao token directory mount

localhost-only host publication

automatic restart on failure

resource limits

no privileged mode
```

---

# 19. Gateway port

Default:

```yaml
openclaw_port: 18789
```

Publish only:

```text
127.0.0.1:18789
```

Never:

```text
0.0.0.0:18789
```

firewalld must not expose this port.

External path:

```text
client
   │
 HTTPS
   ▼
nginx
   │
 HTTP/WebSocket via localhost
   ▼
OpenClaw
```

---

# 20. Gateway bind inside container

Because OpenClaw runs in bridge-networked Podman:

```text
gateway.bind = lan
```

inside the container.

Host exposure remains:

```text
127.0.0.1:18789
```

The distinction is intentional:

```text
inside container:
    listen on container interface

on host:
    publish localhost only
```

Do not configure Gateway loopback inside the container if that prevents Podman port forwarding.

---

# 21. OpenClaw TLS

Do NOT enable OpenClaw's internal Gateway TLS.

TLS terminates at nginx.

Configure equivalent to:

```text
gateway.tls.enabled = false
gateway.tls.autoGenerate = false
```

InfraBox PKI remains authoritative.

Do not create an OpenClaw self-signed CA.

---

# 22. Public hostname

Add:

```yaml
openclaw_hostname: "claw.{{ infrabox_domain }}"
```

External URL:

```text
https://claw.<infrabox_domain>
```

Configure public origin and allowed Control UI origin accordingly.

Do not enable unsafe Host-header origin fallback.

---

# 23. Gateway authentication

Use:

```text
gateway.auth.mode = token
```

nginx is a TLS reverse proxy, not an identity-aware authentication proxy.

Do NOT configure:

```text
gateway.auth.mode = trusted-proxy
```

for this implementation.

---

# 24. Gateway authentication token

The Gateway API/UI authentication token is distinct from the OpenBao token.

Do not confuse:

```text
openclaw_gateway_token
```

with:

```text
OpenBao periodic token
```

They have completely different purposes.

The Gateway token is supplied through the existing protected Ansible secret-input mechanism.

Never put a real Gateway token in:

```text
role defaults
Git inventory
README
openclaw.json
```

Use `no_log` for Ansible tasks handling it.

---

# 25. Initial OpenClaw configuration

Render a minimal secure configuration equivalent to:

```json5
{
  gateway: {
    mode: "local",
    bind: "lan",
    port: 18789,

    publicOrigin: "https://claw.infra.example.com",

    auth: {
      mode: "token"
    },

    tls: {
      enabled: false,
      autoGenerate: false
    },

    controlUi: {
      enabled: true,
      allowedOrigins: [
        "https://claw.infra.example.com"
      ]
    },

    terminal: {
      enabled: false
    }
  },

  agents: {
    defaults: {
      sandbox: {
        mode: "off"
      }
    }
  }
}
```

All values derive from variables.

---

# 26. Initial execution security model

Explicitly disable nested OpenClaw sandbox infrastructure for this change:

```text
agents.defaults.sandbox.mode = off
```

The initial execution boundary is:

```text
OpenClaw Gateway container
```

not the InfraBox host.

The container itself must therefore be constrained.

---

# 27. OpenClaw container security

Mandatory:

```text
NO --privileged

NO host Podman socket

NO Docker socket

NO /dev/tpm*

NO host root filesystem

NO arbitrary /etc mount

NO arbitrary /srv mount

NO OpenBao admin token

NO PostgreSQL credentials

NO Redis credentials

NO production SSH credentials

NO Gitea Runner credentials
```

Do not mount:

```text
/run/podman/podman.sock
/var/run/docker.sock
```

---

# 28. Container hardening

Where compatible with the official image, prefer:

```text
non-root process
NoNewPrivileges
dropped Linux capabilities
read-only mounts for CA and token
explicit resource limits
```

Do not grant capabilities merely because OpenClaw may eventually manage infrastructure.

Future execution interfaces will be designed separately.

---

# 29. Proxy support

Support optional:

```yaml
openclaw_http_proxy:
openclaw_https_proxy:
openclaw_no_proxy:
```

When unset, emit no proxy configuration.

When set, configure the runtime appropriately.

Ensure internal InfraBox endpoints bypass the corporate proxy where required.

---

# 30. InfraBox RootCA

Existing `cacerts` remains HOST ONLY.

Do not change that role.

The `openclaw` role mounts:

```text
{{ infrabox_root_ca_path }}
```

read-only as:

```text
/run/infrabox-ca/root-ca.crt
```

Configure Node/OpenClaw:

```text
NODE_EXTRA_CA_CERTS=/run/infrabox-ca/root-ca.crt
```

This adds InfraBox RootCA while preserving normal public Internet CA trust.

Never use:

```text
NODE_TLS_REJECT_UNAUTHORIZED=0
```

OpenClaw documents `NODE_EXTRA_CA_CERTS` for private Vault CA trust.

---

# 31. nginx certificate

Add:

```text
claw.<infrabox_domain>
```

to the existing nginx ServerCert SAN list managed by the existing certificate OpenBao Agent.

Do not issue a separate OpenClaw certificate.

Expected SAN set includes:

```text
git.<domain>
netbox.<domain>
vault.<domain>
grafana.<domain>
claw.<domain>
```

The existing certificate Agent must obtain a replacement certificate containing the new SAN before acceptance testing succeeds.

---

# 32. nginx vhost

Add:

```text
claw.<infrabox_domain>
```

upstream:

```text
http://127.0.0.1:18789
```

Support:

```text
HTTP/1.1 upstream
Host forwarding
X-Forwarded-For
X-Forwarded-Proto=https
WebSocket Upgrade
Connection upgrade
long-lived WebSocket timeout
```

OpenClaw token authentication remains active behind nginx.

---

# 33. OpenBao KV integration

Use OpenClaw's bundled Vault SecretRefs plugin.

OpenClaw should read model/integration credentials directly from OpenBao.

Do NOT create a custom secret resolver.

OpenClaw's Vault plugin resolves Vault SecretRefs at Gateway startup/reload, keeps resolved values in memory, and does not write resolved API keys back into `openclaw.json`.

---

# 34. OpenBao KV namespace

Use the existing InfraBox KV v2 engine.

Suggested subtree:

```text
openclaw/
├── providers/
├── channels/
└── integrations/
```

Example:

```text
kv/data/openclaw/providers/openai
```

may contain:

```text
apiKey
```

Do not populate provider secrets automatically.

---

# 35. OpenBao policy

Extend:

```text
openbao_bootstrap
```

with policy:

```text
infrabox-openclaw
```

Required capability:

```hcl
path "kv/data/openclaw/*" {
  capabilities = ["read"]
}
```

Also permit the token to inspect and renew itself:

```hcl
path "auth/token/lookup-self" {
  capabilities = ["read"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}
```

If the configured KV v2 access pattern requires metadata access, add only the minimum necessary metadata path.

Do NOT permit:

```text
other KV subtrees
PKI issuance
sys/*
auth administration
token creation
token revocation
Gitea secrets
NetBox secrets
database credentials
```

`bao token renew` without an explicit token uses the authenticated token and calls `/auth/token/renew-self`.

---

# 36. OpenBao token role

Also create an OpenBao token role:

```text
infrabox-openclaw
```

Desired semantics:

```text
allowed policy:
    infrabox-openclaw

default policy:
    disallowed

orphan:
    true

renewable:
    true

token type:
    service

maximum allowed period:
    168h by default

explicit max TTL:
    none
```

Use role configuration equivalent to:

```text
allowed_policies = infrabox-openclaw
disallowed_policies includes default
orphan = true
renewable = true
token_period = 168h
token_type = service
```

The role itself restricts what tokens may be generated.

OpenBao token roles support orphan, renewable and `token_period` constraints specifically for this purpose.

---

# 37. Token creation

The OpenClaw role creates a token against:

```text
auth/token/create/infrabox-openclaw
```

using the existing privileged OpenBao Ansible management mechanism already implemented in InfraBox.

Do NOT introduce another persistent administrative token.

The created token must explicitly request:

```text
policy:
    infrabox-openclaw

period:
    {{ openclaw_openbao_token_period }}

no default policy
```

Conceptually:

```bash
bao token create \
  -role=infrabox-openclaw \
  -policy=infrabox-openclaw \
  -period=168h \
  -no-default-policy \
  -field=token
```

The token role ensures it is orphaned.

Periodic tokens remain valid indefinitely while they continue to renew, unless an explicit maximum TTL is configured.

---

# 38. Token secret handling

Token creation is sensitive.

Ansible must:

```text
use no_log

never print token

never put token in normal facts/log output

write token directly to protected destination

avoid shell tracing
```

Destination:

```text
/etc/infrabox/openclaw/secrets/vault-token
```

Do not store the token in:

```text
Git
role defaults
openclaw.json
openclaw.env
README
/srv
```

---

# 39. Token idempotency

The OpenClaw role must NOT create a new token on every run.

Required algorithm:

```text
token file absent
    -> create token

token file present
    -> use token itself to perform lookup-self

lookup succeeds
    -> validate token properties

lookup fails because token expired/revoked/invalid
    -> create replacement token
    -> atomically replace token file
    -> restart OpenClaw
```

For a valid token verify at least:

```text
renewable = true
orphan = true
type = service
policy set exactly as expected
period matches desired configuration
```

Do not rotate a healthy token merely because Ansible ran.

---

# 40. Immutable token properties

Token properties are largely immutable after creation.

If Ansible detects that the existing token has materially incorrect properties, for example:

```text
wrong policy
not orphan
not renewable
wrong token type
wrong periodic configuration
```

create a replacement token rather than attempting to mutate the existing token.

Where the existing privileged Ansible OpenBao management mechanism allows it, revoke the superseded token after successful replacement.

Do not revoke the old token before the replacement has been safely written.

---

# 41. Token replacement

Replacement sequence:

```text
create new token
      ↓
validate new token
      ↓
atomically replace vault-token
      ↓
restart OpenClaw
      ↓
verify OpenBao SecretRef access
      ↓
revoke old token where possible
```

Because the token directory rather than an individual file is mounted into OpenClaw, atomic replacement is visible correctly after restart.

---

# 42. OpenClaw Vault configuration

Configure:

```text
VAULT_ADDR=https://openbao.<infrabox_internal_domain>:8200

OPENCLAW_VAULT_AUTH_METHOD=token_file

VAULT_TOKEN_FILE=/run/openclaw-secrets/vault-token

OPENCLAW_VAULT_KV_MOUNT=<existing InfraBox KV mount>

OPENCLAW_VAULT_KV_VERSION=2

NODE_EXTRA_CA_CERTS=/run/infrabox-ca/root-ca.crt
```

OpenClaw officially supports `token_file` as a Vault authentication source.

The Vault/OpenBao CLI is not required inside the OpenClaw container.

---

# 43. Enable bundled Vault plugin

Ensure the bundled:

```text
vault
```

plugin is enabled.

Do not install a separate third-party Vault/OpenBao resolver.

The bundled package is:

```text
@openclaw/vault
```

and is distributed with OpenClaw.

---

# 44. SecretRefs

OpenClaw configuration contains references, not resolved credentials.

Conceptually:

```json5
{
  models: {
    providers: {
      openai: {
        apiKey: {
          source: "exec",
          provider: "vault",
          id: "openclaw/providers/openai/apiKey"
        }
      }
    }
  }
}
```

Adjust SecretRef IDs to the configured KV mount semantics.

Provider configuration remains operator-controlled.

---

# 45. Provider-neutral deployment

InfraBox deployment must NOT require:

```text
OpenAI
Anthropic
OpenRouter
GitHub Copilot
```

credentials.

OpenClaw Gateway is infrastructure.

Provider selection happens after installation.

README must explain how to add provider credentials to:

```text
kv/openclaw/*
```

and reference them using OpenClaw SecretRefs.

---

# 46. Token-renew helper

Create:

```text
/usr/local/libexec/infrabox/openclaw-token-renew
```

from:

```text
openclaw-token-renew.j2
```

Keep it deliberately small.

Conceptually:

```bash
#!/usr/bin/env bash
set -euo pipefail

TOKEN_FILE="/etc/infrabox/openclaw/secrets/vault-token"

test -s "${TOKEN_FILE}"

export BAO_ADDR="https://openbao.infrabox.internal:8200"
export BAO_CACERT="/etc/infrabox/pki/root-ca.crt"

export BAO_TOKEN
BAO_TOKEN="$(<"${TOKEN_FILE}")"

exec /usr/local/bin/bao token renew -format=json >/dev/null
```

Use actual configured paths/hostnames.

The host already has the `bao` binary.

Do not install another OpenBao client solely for this helper.

---

# 47. Renewal output

The renewal script must not write token data into journald.

Redirect successful command output away from the journal.

Errors may remain visible.

Do NOT enable:

```text
set -x
```

The token value must never appear in logs.

---

# 48. Renewal service

Create:

```text
openclaw-token-renew.service
```

Conceptually:

```ini
[Unit]
Description=Renew InfraBox OpenClaw OpenBao token
After=network-online.target openbao.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/libexec/infrabox/openclaw-token-renew

User=root
Group=root

NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

ReadOnlyPaths=/etc/infrabox/openclaw/secrets/vault-token
ReadOnlyPaths=/etc/infrabox/pki/root-ca.crt
```

Adapt the exact OpenBao unit name to the existing InfraBox implementation.

Do not give this service:

```text
Podman socket
Docker socket
shell login
write access to unrelated InfraBox configuration
```

---

# 49. Why renewal service runs as root

This oneshot may run as root because:

```text
it must read the protected token
it is short-lived
it has no listener
it only performs one HTTPS request to OpenBao
systemd hardening constrains it
```

Do not weaken token file permissions just to run renewal as an unprivileged service.

A future refinement may use a dedicated credential-renewal account, but it is not necessary for this MVP.

---

# 50. Renewal timer

Create:

```text
openclaw-token-renew.timer
```

Use both a delayed boot run and a calendar schedule.

Conceptually:

```ini
[Unit]
Description=Renew InfraBox OpenClaw OpenBao token

[Timer]
OnBootSec=5min
OnCalendar=*-*-* 00,12:00:00
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
```

Use `OnCalendar` so that:

```text
Persistent=true
```

can catch a missed calendar activation after downtime.

`OnBootSec=5min` provides an additional renewal attempt shortly after normal boot.

---

# 51. Renewal failure

Renewal service failure must:

```text
return non-zero
be visible in systemd/journal
NOT modify the token file
NOT restart OpenClaw
```

A single failed renewal does not make OpenClaw unavailable because the token still has substantial remaining TTL.

The next timer activation tries again.

Do not attempt privileged automatic reissuance from the renewal script.

---

# 52. Token expiry recovery

If:

```text
bao token renew
```

fails because the token has already expired or been revoked, the timer must remain failed.

Recovery belongs to Ansible.

README procedure:

```text
run:
    ansible-playbook agent.yml --tags openclaw

Ansible:
    detects invalid token
    creates replacement token
    replaces token file
    restarts OpenClaw
    verifies SecretRefs
```

Do not put an OpenBao administrative credential into the renewal service.

---

# 53. Normal reboot flow

Expected:

```text
host reboot
     ↓
TPM2
     ↓
OpenBao starts
     ↓
OpenBao auto-unseals
     ↓
OpenClaw starts using persistent periodic token
     ↓
SecretRefs resolve
     ↓
OpenClaw ready
     ↓
5 minutes after boot
     ↓
openclaw-token-renew.service
     ↓
token TTL reset to 7 days
```

No operator action is required during a normal reboot.

---

# 54. Long shutdown behavior

If InfraBox is powered down for:

```text
less than 7 days
```

the existing token should still be valid after boot and gets renewed shortly afterwards.

If powered down for:

```text
more than 7 days
```

the token may have expired.

Expected behavior:

```text
OpenClaw SecretRef-dependent startup may fail
renew timer fails
operator reruns OpenClaw Ansible role
new token issued
OpenClaw recovers
```

Document this limitation explicitly.

---

# 55. OpenBao compatibility test

The OpenClaw plugin is branded for HashiCorp Vault while InfraBox runs OpenBao.

Explicitly test:

```text
OpenClaw Vault plugin
        ↓
OpenBao API
        ↓
KV v2 read
```

Acceptance:

```text
create disposable secret under kv/openclaw/test

reference it through OpenClaw SecretRef

start/reload OpenClaw

verify resolution

verify resolved value is not persisted into openclaw.json

delete test secret
```

OpenClaw's plugin uses the Vault HTTP API directly and requires a scoped client token; it does not require the Vault CLI inside the Gateway.

If compatibility fails:

```text
FAIL
```

Do NOT silently:

```text
disable TLS validation
give OpenClaw root token
copy secrets into config
invent a custom resolver
```

---

# 56. Negative OpenBao access test

The OpenClaw token must successfully read:

```text
kv/data/openclaw/*
```

and fail to read an unrelated InfraBox secret.

Example:

```text
allowed:
    kv/data/openclaw/test

denied:
    kv/data/gitea/test
```

The negative test is mandatory.

---

# 57. Token self-renewal test

Acceptance must test the actual service token.

Run the renewal helper and verify:

```text
token value did NOT change

token remains renewable

token TTL increased/reset toward 168h

token policies remain unchanged
```

`bao token renew` with no token argument renews the current authenticated token rather than issuing a new token.

---

# 58. Timer test

Verify:

```text
systemctl start openclaw-token-renew.service
    succeeds

systemctl enable --now openclaw-token-renew.timer
    succeeds

systemctl list-timers
    shows next execution

timer survives reboot

boot-time renewal runs
```

Do not wait seven days to validate the mechanism.

---

# 59. Gateway health

Verify directly:

```text
http://127.0.0.1:18789/healthz
http://127.0.0.1:18789/readyz
```

Then through nginx:

```text
https://claw.<infrabox_domain>/healthz
```

Use proper CA verification.

Never use:

```text
curl -k
```

in final acceptance tests.

---

# 60. TLS verification

Verify inside the OpenClaw container that:

```text
OpenBao HTTPS certificate validates
using InfraBox RootCA
```

Also verify normal public Internet HTTPS remains trusted.

Adding InfraBox RootCA must augment rather than replace the normal Node trust set.

---

# 61. nginx verification

Verify:

```text
nginx -t

certificate SAN contains claw.<domain>

HTTPS request succeeds

WebSocket upgrade succeeds

Gateway authentication remains required
```

nginx must not accidentally turn OpenClaw into an unauthenticated service.

---

# 62. verify.yml additions

Add at minimum:

```text
OpenClaw Quadlet active

OpenClaw container running

healthz healthy

readyz healthy

public HTTPS endpoint healthy

nginx certificate contains claw hostname

Gateway authentication enabled

terminal disabled

sandbox explicitly off

host Podman socket absent

Docker socket absent

TPM absent from container

RootCA mounted

OpenClaw validates OpenBao TLS

OpenBao Vault plugin enabled

periodic token file exists

periodic token is valid

token is orphan

token is renewable

token period matches desired value

token policies are exact

default policy absent

OpenClaw KV path readable

unrelated KV path denied

openclaw-token-renew.service works

openclaw-token-renew.timer enabled
```

---

# 63. Idempotency

Required:

```text
run site.yml

run site.yml again
```

Second run must NOT:

```text
create another OpenBao token

replace a healthy token file

restart OpenClaw unnecessarily

rotate nginx certificate unnecessarily

recreate OpenBao policy unnecessarily

recreate token role unnecessarily

destroy OpenClaw state

destroy OpenClaw sessions
```

A valid periodic token must survive ordinary Ansible runs unchanged.

---

# 64. Token-role configuration change

If desired token-role properties change:

```text
policy
period
orphan semantics
token type
```

the role configuration in OpenBao is updated idempotently.

Because existing token properties are not generally mutable, Ansible must then determine whether the existing token still satisfies desired state.

If not:

```text
issue replacement
validate replacement
replace file
restart OpenClaw
revoke old token where possible
```

Do not assume changing a token role retroactively changes an already-issued token.

---

# 65. Upgrade behavior

Changing:

```yaml
openclaw_version:
```

must:

```text
pull new image
replace/restart container
preserve state
preserve workspace
preserve OpenBao token
preserve SecretRefs
reverify readiness
```

Do not recreate the OpenBao token solely because OpenClaw was upgraded.

---

# 66. Logging

Use existing systemd/Podman logging.

No new logging stack.

Operational paths:

```text
journalctl -u openclaw.service

journalctl -u openclaw-token-renew.service

journalctl -u openclaw-token-renew.timer

podman logs <openclaw-container>
```

Neither the OpenBao token nor resolved provider secrets may appear in logs.

---

# 67. Resource controls

Provide configurable:

```yaml
openclaw_memory_limit:
openclaw_cpu_limit:
openclaw_pids_limit:
```

Use sensible defaults for the InfraBox host.

OpenClaw must not be able to consume all appliance resources by default.

---

# 68. README additions

Document:

```text
OpenClaw architecture

public URL

Gateway authentication

OpenBao SecretRefs

OpenBao token model

7-day token period

twice-daily systemd renewal

how to inspect token-renew timer

how to manually trigger renewal

how to detect token expiry

how to recover expired token using Ansible

where provider secrets belong

how to add a model provider

health checks

logs

restart procedure

upgrade procedure

sandbox limitation

execution limitations
```

---

# 69. README token-expiry procedure

Document explicitly:

```text
If OpenClaw cannot resolve OpenBao SecretRefs:

1. Check OpenBao health.

2. Check:

   systemctl status openclaw-token-renew.service

3. Validate the OpenClaw token.

4. If token is expired or revoked:

   ansible-playbook agent.yml --tags openclaw

5. Ansible creates a replacement token and restarts OpenClaw.

6. Verify /readyz.
```

Do not tell operators to manually create root tokens.

---

# 70. Provider-secret procedure

Example without real credentials:

```text
1. Store provider secret:

   kv/openclaw/providers/<provider>

2. Configure OpenClaw SecretRef.

3. Reload/restart OpenClaw secrets as appropriate.

4. Verify provider connectivity.

5. Confirm the resolved secret does not appear in openclaw.json.
```

Provider credentials remain operator data.

---

# 71. Security consequences of periodic token

The OpenClaw token can renew itself.

Therefore theft of this token could allow an attacker to keep the credential alive by continuing to renew it.

The mitigation is strict least privilege:

```text
read only kv/openclaw/*

lookup-self

renew-self

nothing else
```

Do NOT broaden this token later merely for convenience.

If OpenClaw needs additional InfraBox capabilities, introduce a separate deliberate security design.

---

# 72. Required security invariants

```text
OpenClaw is not privileged.

OpenClaw has no host Podman socket.

OpenClaw has no Docker socket.

OpenClaw cannot access TPM.

OpenClaw does not receive OpenBao admin credentials.

OpenClaw receives one least-privilege periodic token.

The token is orphaned.

The token has no default policy.

The token is renewable.

The token has no explicit maximum TTL.

The token reads only OpenClaw KV secrets.

The token can only lookup/renew itself in auth/token.

The systemd renewer cannot create tokens.

The systemd renewer cannot administer OpenBao.

The systemd renewer does not modify the token file.

Only Ansible may replace an expired/revoked token.

OpenClaw talks directly to OpenBao.

No OpenBao Agent is involved in OpenClaw secret access.

The existing certificate OpenBao Agent remains unchanged.

Gateway authentication remains enabled.

OpenClaw public exposure is only through nginx.

TLS verification is never disabled.

cacerts remains host-only.

OpenClaw role owns container RootCA trust.

Nested OpenClaw sandbox remains out of scope.

Provider selection remains operator-controlled.
```

---

# 73. Implementation order for Codex

```text
Phase 1
    add OpenClaw role skeleton
    add variables
    add agent.yml

Phase 2
    persistent directories
    state/workspace mounts
    Quadlet
    localhost publication

Phase 3
    minimal Gateway
    Gateway token auth
    health checks

Phase 4
    RootCA mount
    Node CA trust

Phase 5
    nginx certificate SAN
    nginx vhost
    WebSocket proxy

Phase 6
    extend openbao_bootstrap:
        infrabox-openclaw policy
        infrabox-openclaw token role

Phase 7
    implement token.yml:
        lookup existing token
        validate token
        create token when missing/invalid
        protected token file
        replacement behavior

Phase 8
    implement renewal helper
    renewal service
    renewal timer

Phase 9
    enable bundled Vault plugin
    configure token_file auth
    configure OpenBao SecretRefs

Phase 10
    positive KV access test
    negative KV access test
    renewal test

Phase 11
    verify.yml integration

Phase 12
    reboot test

Phase 13
    README

Phase 14
    final idempotency run
```

Do not implement everything before verifying the basic Gateway.

---

# 74. Acceptance tests

## Deployment

```text
site.yml succeeds
second site.yml is idempotent
```

## Gateway

```text
container running
healthz healthy
readyz healthy
```

## TLS

```text
https://claw.<domain> works
certificate chain valid
SAN valid
OpenClaw trusts OpenBao
public Internet CA trust still works
```

## Authentication

```text
unauthenticated privileged Gateway access rejected
Gateway token accepted
```

## WebSocket

```text
WebSocket control connection works through nginx
```

## OpenBao token

```text
token exists
token is service type
token is orphan
token is renewable
token period = desired value
explicit max TTL absent
policy = infrabox-openclaw
default policy absent
```

## OpenBao authorization

```text
kv/openclaw/* read succeeds
unrelated KV read fails
PKI access fails
sys administration fails
token creation fails
```

## Renewal

```text
manual renewal service succeeds

token value remains identical

token TTL resets toward 7 days

timer enabled

timer scheduled
```

## Isolation

```text
no host Podman socket
no Docker socket
no TPM
no host root filesystem
no unrelated InfraBox volumes
```

## Reboot

```text
host reboot

OpenBao auto-unseals

OpenClaw starts with existing token

SecretRefs resolve

OpenClaw becomes ready

boot-time token renewal executes

nginx endpoint works
```

---

# 75. Definition of Done

The OpenClaw integration is complete when:

```text
OpenClaw runs through Podman + Quadlet

version is pinned

state persists

workspace persists

Gateway host publication is loopback-only

public access works through nginx

nginx certificate contains claw hostname

Gateway authentication enabled

WebSocket traffic works

terminal disabled

nested sandbox disabled

container unprivileged

no host runtime socket

no TPM access

no unrelated InfraBox volumes

InfraBox RootCA mounted

OpenClaw verifies OpenBao TLS

bundled Vault plugin enabled

OpenClaw talks directly to OpenBao

infrabox-openclaw policy exists

infrabox-openclaw token role exists

periodic orphan service token exists

default token period is 7 days

token has no explicit max TTL

token has no default policy

token can read only kv/openclaw/*

token can lookup/renew itself

systemd renew service exists

systemd renew timer runs twice daily

token renewal does not change token value

no OpenBao Agent instance exists for OpenClaw

existing certificate OpenBao Agent remains unchanged

provider secrets are not stored in openclaw.json

OpenClaw deploys without requiring a model provider

healthz succeeds

readyz succeeds

verify.yml succeeds

second site.yml is idempotent

normal reboot requires no operator intervention
```

---

# 76. Core implementation invariants

If implementation details are ambiguous, these take precedence:

```text
1. OpenClaw is an application service, not an InfraBox bootstrap
   dependency.

2. OpenClaw runs in a container.

3. OpenClaw has no host root or container-runtime socket.

4. OpenClaw talks directly to OpenBao.

5. There is no OpenBao Agent instance for OpenClaw.

6. Existing OpenBao Agent remains certificate-only.

7. Ansible provisions the initial OpenClaw OpenBao token.

8. The token is a periodic orphan service token.

9. Default token period is 7 days.

10. The token has no explicit maximum TTL.

11. The token has only infrabox-openclaw policy.

12. The default policy must not be present.

13. The token may read only OpenClaw's KV subtree.

14. The token may lookup and renew itself.

15. A systemd timer renews it twice per day.

16. Renewal does not generate a new token.

17. The renewal service holds no OpenBao administrative credential.

18. Ansible is the only automated mechanism allowed to replace an
    expired/revoked token.

19. Existing healthy tokens survive Ansible runs unchanged.

20. OpenClaw uses token_file rather than embedding the OpenBao token
    in its config or environment.

21. The token directory is mounted, not only the token file.

22. OpenClaw Vault SecretRefs remain the mechanism for provider
    credentials.

23. Gateway TLS terminates at nginx.

24. Gateway authentication stays enabled behind nginx.

25. RootCA validation is never bypassed.

26. cacerts remains host-only.

27. Nested OpenClaw sandbox remains out of scope.

28. Provider choice remains operator-controlled.

29. Prefer explicit failure over authentication or TLS downgrade.

30. Normal reboot must restore OpenClaw without human intervention,
    assuming the periodic token has not expired.
```

This document is the implementation contract for adding OpenClaw to the already implemented InfraBox MVP.

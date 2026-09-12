# InfraBox — OpenClaw ↔ NetBox Onboarding Implementation Plan

The subsequent [subnet-scanning extension](InfraBox%20%E2%80%94%20OpenClaw%20Subnet%20Scanning%20Implementation%20Plan.md)
adds approved, bounded Nmap observations. Its contract supersedes this plan's
network-scanning exclusions and absolute prohibition of discovery claims only
for observations actually returned by that tool. Separate NetBox write
confirmation and all other restrictions below remain in effect.

The later [OpenAI web-search extension](README.md#web-search-through-openai)
also permits public vendor/model research with source citations. Published
specifications do not establish a particular device's identity or installed
configuration; sourced fields still require a reviewed NetBox write proposal.

## 1. Objective

Implement the first user-facing InfraBox infrastructure workflow:

```text
User
  ↓
OpenClaw
  ↓
NetBox MCP
  ↓
NetBox
```

The user describes their existing infrastructure conversationally.

OpenClaw must:

1. understand infrastructure described by the user;
2. inspect existing NetBox state;
3. ask only for missing information needed for a useful initial inventory;
4. build a proposed NetBox change;
5. show the proposal to the user;
6. require explicit confirmation;
7. create/update the allowed NetBox objects;
8. answer subsequent questions using NetBox as Source of Truth.

This iteration does **not** perform infrastructure discovery.

Do not add:

```text
SSH
Ansible execution
Gitea workflow execution
Proxmox API access
network scanning
platform automation repository
discovery pipelines
```

---

# 2. Existing architecture

InfraBox already contains:

```text
NetBox
OpenClaw
OpenBao
nginx
Podman / Quadlet
InfraBox RootCA
```

Preserve the current OpenClaw security boundary:

```text
no host Podman socket
no Docker socket
no privileged mode
no SSH keys
no direct server credentials
terminal disabled
exec disabled
process disabled
browser disabled
nodes disabled
```

Adding NetBox access must not relax these restrictions.

---

# 3. Resulting architecture

```text
                         OpenBao
                            │
                      NetBox API token
                            │
                            ▼
User ───────► OpenClaw ───────► NetBox MCP ───────► NetBox
                  │
                  │ managed onboarding skill
                  ▼
             conversation
```

The LLM must never receive the NetBox API token in conversation context.

---

# 4. NetBox MCP

Use:

```text
ZenixSolutions/netbox-mcp-server
```

Use an explicitly pinned tested version.

Never install from:

```text
latest
master
main
unpinned npm package
```

Expected MCP tools:

```text
netbox_global_search
netbox_discover
netbox_describe
netbox_read
netbox_write
```

Do not implement a custom MCP server in this iteration.

---

# 5. MCP execution model

The selected MCP implementation runs over stdio.

Run it as a child process of OpenClaw.

Do not introduce a separate HTTP service.

```text
OpenClaw container
│
├── OpenClaw Gateway
│
└── netbox-mcp
        │
        │ HTTPS
        ▼
      NetBox
```

---

# 6. OpenClaw image

Extend the existing InfraBox OpenClaw image so it contains:

```text
OpenClaw
pinned NetBox MCP package
required runtime dependencies
InfraBox MCP launcher
```

Do not dynamically install MCP software on every container start.

The runtime image must be reproducible from pinned versions.

---

# 7. NetBox connectivity

Use the existing HTTPS NetBox endpoint reachable from the OpenClaw container.

Prefer the internal InfraBox endpoint if available.

TLS verification is mandatory.

The MCP process must trust the existing InfraBox RootCA.

Never configure:

```text
NODE_TLS_REJECT_UNAUTHORIZED=0
validate_certs=false
NETBOX_INSECURE=true
```

---

# 8. Dedicated NetBox identity

Create a dedicated NetBox service account:

```text
infrabox-openclaw
```

It must be:

```text
non-superuser
non-staff unless technically required
dedicated only to OpenClaw
```

Do not use an administrator or human user's token.

---

# 9. NetBox API token

Create a dedicated write-enabled NetBox token for:

```text
infrabox-openclaw
```

Requirements:

```text
write enabled
no expiration
dedicated to OpenClaw
not shared with Ansible
not shared with Gitea
not shared with users
```

Authorization must be controlled by NetBox object permissions.

---

# 10. NetBox permissions

Grant:

```text
view
add
change
```

but explicitly **not delete**.

Initial allowed object types:

```text
dcim.site
dcim.location
dcim.manufacturer
dcim.devicetype
dcim.devicerole
dcim.device
dcim.interface

ipam.prefix
ipam.ipaddress
ipam.vlan

virtualization.clustertype
virtualization.cluster
virtualization.virtualmachine
virtualization.vminterface

extras.tag
```

Add another model only if required by NetBox relationships during implementation.

Do not grant permissions for:

```text
users
groups
permissions
API tokens
webhooks
event rules
scripts
jobs
data sources
administrative configuration
```

---

# 11. Delete protection

OpenClaw must never be able to delete NetBox objects.

Enforce this at two levels:

```text
OpenClaw onboarding policy:
    never request delete

NetBox permissions:
    no delete permission
```

Do not rely solely on prompting.

A malicious or mistaken `netbox_write` delete operation must fail in NetBox.

NetBox 4.7 also grants implicit self-service permissions, including API token
creation, outside explicit ObjectPermission records. Exclude those defaults for
the dedicated integration account using a narrowly scoped authorization backend
configured before NetBox's stock backend. Keep ordinary users' self-service
permissions intact. Verify effective permissions, not only the stored grant.

---

# 12. Secret ownership

Store the NetBox API token in OpenBao.

Canonical path:

```text
kv/openclaw/integrations/netbox
```

Field:

```text
apiToken
```

Do not store the token in:

```text
Git
Ansible inventory
openclaw.json
SKILL.md
README
```

OpenBao remains the persistent source of truth for this integration credential.

---

# 13. Runtime token materialization

Materialize the OpenBao secret into the existing OpenClaw secret directory:

```text
/etc/infrabox/openclaw/secrets/
├── vault-token
└── netbox-token
```

Permissions:

```text
0600
OpenClaw runtime owner only
```

The complete secrets directory remains bind-mounted read-only into the container:

```text
/run/openclaw-secrets/
```

Result:

```text
/run/openclaw-secrets/netbox-token
```

Continue mounting the directory rather than an individual file so atomic file replacement works correctly.

---

# 14. NetBox MCP launcher

Add a very small InfraBox-owned executable:

```text
/usr/local/bin/infrabox-netbox-mcp
```

Its only responsibilities:

```text
1. verify /run/openclaw-secrets/netbox-token exists
2. verify it is non-empty
3. read the token
4. export NETBOX_TOKEN
5. verify NETBOX_URL exists
6. exec the pinned netbox-mcp binary
```

Conceptually:

```bash
#!/usr/bin/env sh
set -eu

TOKEN_FILE=/run/openclaw-secrets/netbox-token

test -s "${TOKEN_FILE}"

export NETBOX_TOKEN="$(cat "${TOKEN_FILE}")"

test -n "${NETBOX_URL:-}"

exec /path/to/netbox-mcp
```

Requirements:

```text
no set -x
no secret logging
no business logic
no HTTP logic
no NetBox manipulation
```

The launcher exists only to bridge file-based secrets into the child process environment.

---

# 15. OpenClaw MCP configuration

Extend the managed OpenClaw configuration with:

```text
mcp.servers.netbox
```

Conceptually:

```json
{
  "mcp": {
    "servers": {
      "netbox": {
        "command": "/usr/local/bin/infrabox-netbox-mcp",
        "env": {
          "NETBOX_URL": "https://netbox.example.internal"
        }
      }
    }
  }
}
```

Do not put `NETBOX_TOKEN` in `openclaw.json`.

---

# 16. OpenClaw tool policy

The current `minimal` tool profile does not expose MCP tools.

Change the profile to the narrowest supported profile that enables MCP, expected to be:

```text
messaging
```

Retain explicit denial for:

```text
exec
process
browser
nodes
terminal
```

Do not use:

```text
coding
full
```

unless testing proves it is unavoidable.

The final effective tool set must provide NetBox MCP without providing shell execution.
A workspace-restricted read tool may load the read-only managed skill. Keep file
writes and delegation disabled; do not expose unrestricted filesystem reads.

---

# 17. Onboarding skill

Create an InfraBox-managed OpenClaw skill:

```text
netbox-onboarding
```

Example managed path:

```text
/home/node/.openclaw/workspace/skills/netbox-onboarding/SKILL.md
```

The skill is delivered by Ansible and is not user-generated workspace content.
It may be mounted read-only beneath workspace/skills so a workspace-restricted
read tool can load it without accessing credentials.

Its purpose is to define policy and conversation behavior.

It does not contain credentials.

---

# 18. Core onboarding rules

The skill must explicitly tell OpenClaw:

```text
NetBox is InfraBox's infrastructure Source of Truth.

Read existing NetBox state before creating objects.

Never invent infrastructure facts.

Prefer incomplete but correct inventory over detailed guessed inventory.

Never claim that user-provided information has been verified.

Never delete NetBox objects.

Always prepare a proposed change before writing.

Always require explicit confirmation before every logical write operation.

A direct imperative from the user is NOT sufficient to skip confirmation.
```

This confirmation requirement applies both during initial onboarding and later changes.
The operator accepts enforcement through the managed skill for this iteration;
a separate programmatic write-approval gate is not required.

Example:

```text
User:
Add server03 with IP 192.168.32.23.

OpenClaw:
I will add:
  Device: server03
  IP: 192.168.32.23

Proceed?

User:
Yes.

OpenClaw:
write
```

---

# 19. Confirmation semantics

One confirmation may authorize a coherent batch of operations.

Example proposal:

```text
Create:

Site:
  home

Prefix:
  192.168.32.0/24

Devices:
  pve01
  pve02
  nas01

Cluster:
  home-pve
```

One:

```text
Yes, proceed.
```

may authorize all writes required to implement exactly that proposal.

If OpenClaw discovers during execution that materially different objects are required, it must stop and request a new confirmation.

---

# 20. Initial conversation

The onboarding flow is conversational rather than wizard-like.

A user should be able to say:

```text
I have two Proxmox nodes, a NAS and a router at home.
The network is 192.168.32.0/24.
```

OpenClaw should:

```text
extract known facts
inspect existing NetBox
identify genuinely missing information
ask minimal follow-up questions
build proposal
request confirmation
write
```

Do not ask the user to fill every NetBox field manually.

---

# 21. Basic inventory scope

The first version should model only useful high-level information:

```text
sites
locations where explicitly useful
physical devices
virtual machines
virtualization clusters
prefixes
known IP addresses
known interfaces
device roles
basic device types
manufacturers
```

Do not attempt to establish:

```text
CPU details
RAM
serial numbers
disks
exact OS version
complete interfaces
MAC addresses
packages
services
hardware components
```

Those belong to later discovery.

---

# 22. Generic placeholder hardware

Create bootstrap NetBox objects for hardware whose exact model is not yet known.

Manufacturer:

```text
InfraBox Generic
```

Device Types:

```text
Generic Server
Generic Hypervisor
Generic NAS
Generic Network Device
```

These exist specifically so user-described physical infrastructure can be represented before automated discovery.

Add descriptions such as:

```text
Temporary InfraBox device type used until hardware model is verified.
```

Discovery may replace these later with accurate manufacturer/device-type relationships.

OpenClaw must not pretend that a generic type represents detected hardware.

---

# 23. Device roles

Create or reuse a small initial role vocabulary:

```text
server
hypervisor
nas
router
switch
firewall
```

Reuse existing roles whenever possible.

Avoid creating unnecessarily specific roles from casual user language.

---

# 24. Site handling

If a user clearly has one environment but provides no site name, ask for one.

Example:

```text
What should I call this site?
For example: home, lab, berlin-office.
```

Do not invent organization-specific site names.

Always search for an existing matching site first.

---

# 25. Virtualization modeling

When the user explicitly identifies a virtualization platform such as:

```text
Proxmox
VMware
KVM
Hyper-V
```

OpenClaw may create:

```text
cluster type
cluster
known VM objects
```

provided the user actually supplied that information.

Example:

```text
I have a Proxmox cluster home-pve with nodes pve01 and pve02.
```

This is sufficient to model the cluster relationship.

Do not query Proxmox in this implementation phase.

---

# 26. Network modeling

If the user provides:

```text
192.168.32.0/24
```

OpenClaw may propose a Prefix.

If the user provides:

```text
server01 = 192.168.32.20
```

OpenClaw may propose the IP address.

Do not infer IP addresses from ranges.

---

# 27. Interfaces

Never invent realistic-looking interface names:

```text
eth0
ens18
eno1
enp2s0
```

If NetBox modeling requires an interface before an IP can be assigned and the real interface is unknown, create an explicitly generic placeholder such as:

```text
infrabox-unknown
```

with a description indicating:

```text
Placeholder interface created from user-provided inventory.
Awaiting discovery.
```

Prefer incomplete data over false precision.

---

# 28. InfraBox tags

Ensure these tags exist:

```text
infrabox-managed
infrabox-user-provided
```

`infrabox-managed` means:

> InfraBox is expected to manage or inspect this object in later platform automation.

`infrabox-user-provided` means:

> This object's initial information came from conversational onboarding rather than automated discovery.

Apply `infrabox-user-provided` where appropriate to newly created infrastructure objects.
`infrabox-managed` is an explicit choice for later automation, not an OpenClaw
access restriction. OpenClaw may modify tagged or untagged permitted objects
after confirmation, including adding/removing the management tag association.
Preserve unrelated tags. Ask about automation management when the user has not
specified it and show the choice in the proposal.

Do not build a more complex provenance system in this phase.

---

# 29. Read-before-write

Before creating or modifying an object, OpenClaw must inspect relevant current state.

Use:

```text
netbox_global_search
netbox_read
netbox_describe
```

where appropriate.

The onboarding skill must explicitly prohibit blind creates.

---

# 30. Idempotency

Repeated onboarding should not create duplicates.

Example:

```text
User:
I have server01.

NetBox:
server01 already exists in site home.
```

Expected behavior:

```text
recognize existing object
reuse it
do not create server01-2
do not create a second equivalent device
```

---

# 31. Conflict handling

If NetBox and the user disagree:

```text
NetBox:
server01 = 192.168.32.20

User:
server01 = 192.168.32.21
```

OpenClaw must say conceptually:

```text
NetBox currently records 192.168.32.20.
You provided 192.168.32.21.

I propose changing it to 192.168.32.21.
Proceed?
```

Never silently prefer either value.

---

# 32. No implied deletion

Statements such as:

```text
I have three servers.
```

must not imply that a fourth server currently in NetBox should be removed.

No deletion/reconciliation-by-absence exists in this phase.

---

# 33. No discovery claims

Until the later discovery feature exists, OpenClaw must distinguish:

```text
user-provided
stored in NetBox
verified
```

Only the first two exist here.

Allowed language:

```text
You told me...
NetBox currently records...
I added...
I updated...
```

Avoid:

```text
I detected...
I discovered...
I verified...
I found on the server...
```

---

# 34. NetBox token provisioning

Provision the integration idempotently.

Desired lifecycle:

```text
service identity missing
  → create

permissions missing/wrong
  → reconcile

OpenBao token missing
  → create NetBox token
  → store in OpenBao

healthy token exists
  → preserve

stored token invalid
  → create replacement
  → validate replacement
  → store in OpenBao
  → atomically replace runtime file
  → restart OpenClaw
  → remove/revoke obsolete token where practical
```

Do not rotate a healthy token on every Ansible run.

---

# 35. Component ownership

Keep responsibilities aligned with existing concrete roles.

NetBox role owns:

```text
service user
object permissions
API token creation
generic placeholder objects
InfraBox tags
```

OpenClaw role owns:

```text
OpenBao secret handling for integration
runtime token materialization
MCP dependency
MCP launcher
OpenClaw MCP config
tool policy
onboarding skill
```

Do not create a generic `mcp` or `integration` role at this stage.

---

# 36. Variables

Example OpenClaw variables:

```yaml
openclaw_netbox_enabled: true
openclaw_netbox_url: "https://netbox.{{ infrabox_domain }}"
openclaw_netbox_mcp_version: "<PINNED_VERSION>"
openclaw_netbox_token_file: "{{ openclaw_config_dir }}/secrets/netbox-token"
```

NetBox-side variables:

```yaml
netbox_openclaw_username: infrabox-openclaw
netbox_openclaw_token_description: InfraBox OpenClaw MCP
```

All secret values must remain out of inventory variables.

---

# 37. Verification

Extend InfraBox verification to test:

```text
NetBox service identity exists

expected permissions exist

delete permission is absent

NetBox token is valid

token is stored in OpenBao

runtime token file exists with correct permissions

token is absent from openclaw.json

NetBox MCP binary exists

NetBox MCP version equals pinned version

OpenClaw has MCP server "netbox"

OpenClaw can establish MCP session

expected five tools are exposed

NetBox read succeeds

Effective NetBox permissions permit only view/add/change on the listed models

Effective NetBox permissions exclude deletion and administration

OpenClaw shell/exec remains unavailable
```

---

# 38–43. Acceptance scope (operator decision)

Automated OpenClaw conversational acceptance, paid model calls, temporary live
NetBox fixtures, live write/delete probes, and disruptive acceptance tests are
not required in this implementation. The operator will exercise conversational
onboarding, confirmation, repeat, correction, management-tag changes, and refusal
of deletion manually later. Do not implement those acceptance playbooks or claim
those scenarios passed.

Retain local syntax/unit checks, non-destructive credential and permission
verification, pinned package checks, an actual MCP session and NetBox read,
OpenClaw MCP discovery, and existing service/isolation verification. Necessary
Gateway restarts to deploy configuration or replacement credentials remain part
of normal deployment. No reboot or expiry acceptance is required for this change.

---

# 44. Documentation

Update the InfraBox README/user documentation with the initial workflow:

```text
1. Deploy InfraBox.
2. Configure an OpenClaw model provider.
3. Open claw.<domain>.
4. Tell OpenClaw what infrastructure exists.
5. Answer minimal follow-up questions.
6. Review proposed inventory.
7. Confirm.
8. Inspect resulting inventory in NetBox.
```

Clearly state:

```text
At this stage InfraBox records user-provided information.

It has not yet verified the managed servers.

Verification and enrichment will be introduced by the later Ansible discovery pipeline.
```

---

# 45. Out of scope

Do not implement:

```text
SSH
Ansible
Gitea platform repository
Gitea platform pipelines
discovery
Proxmox API access
network scanning
hardware detection
drift detection
automatic reconciliation
NetBox deletion
NetBox branching
custom InfraBox UI
custom MCP server
multiple agents
generic MCP administration
```

---

# 46. Implementation order

## Phase 1 — NetBox integration identity

```text
service user
permissions
generic roles/types/tags
API token
OpenBao storage
runtime token materialization
```

## Phase 2 — MCP

```text
pin dependency
add MCP to OpenClaw image
add launcher
configure MCP server
enable MCP in tool policy
verify connectivity
```

## Phase 3 — onboarding behavior

```text
managed skill
read-before-write
generic placeholders
proposal generation
mandatory confirmation
conflict behavior
no-delete behavior
```

## Phase 4 — testing

```text
read-only integration verification
effective permission inspection
local credential lifecycle regression tests
deployment rerun/idempotency verification
manual conversational acceptance left to operator
documentation
```

---

# 47. Definition of Done

Implementation and deployment are complete after the structural checks below.
Conversational behavior remains a manual operator acceptance responsibility and
is not claimed from structural checks alone.

The intended workflow and security contract are:

```text
OpenClaw can read NetBox through MCP.

OpenClaw can create and update only permitted inventory objects.

OpenClaw cannot delete objects.

OpenClaw cannot administer NetBox.

The NetBox API token is stored in OpenBao.

The runtime token is delivered through a restricted file and launcher.

The token is absent from openclaw.json.

NetBox MCP is pinned to a tested version.

OpenClaw shell/exec capabilities remain disabled.

Generic placeholder hardware types exist.

A user can describe a small environment conversationally.

OpenClaw reads existing NetBox before writing.

OpenClaw presents a human-readable proposal.

Explicit confirmation is required before every logical write operation.

Direct commands such as "add server X" still require confirmation.

Confirmed objects are written correctly.

Repeated onboarding does not create duplicates.

Conflicts are surfaced instead of silently overwritten.

OpenClaw never claims user-provided information has been discovered or verified.

No SSH, Ansible or discovery functionality exists in this phase.
```

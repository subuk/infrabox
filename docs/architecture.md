# Architecture

[Documentation index](README.md) · [Installation](installation.md)

InfraBox is a single AlmaLinux 10 appliance managed from a separate Ansible
controller. It brings Git/CI, infrastructure inventory, secrets, identity,
monitoring and an optional model-backed operator interface onto one host.
It uses Podman Quadlet and systemd; it does not require Kubernetes.

## Components

| Component | Responsibility | Runtime |
| --- | --- | --- |
| nginx | Public HTTPS, home page and WebSocket proxy | Native host service |
| OpenBao | Secrets, PKI and human OIDC provider | Container; TPM-backed auto-unseal |
| Certificate Agent | Routine leaf issuance and renewal | Native OpenBao Agent |
| LLDAP | Passwords, identity types and role membership | Container with PostgreSQL storage |
| Gitea | Git repositories, SSH on 2222 and Actions | Container |
| NetBox and worker | IPAM/DCIM source of truth and background jobs | Containers |
| PostgreSQL / Redis | Application data / NetBox tasks and cache | Internal containers with TLS clients |
| Prometheus / Grafana | Metrics, alert state and provisioned health dashboard | Containers |
| Generic Gitea runner | Shell/Git CI jobs | Isolated container and network |
| OpenClaw | Token-authenticated chat, NetBox MCP, health and discovery tools | Non-root container |
| Subnet scanner | Approved Nmap probes | Separate container with raw-packet capability |
| Platform runner | Optional fixed discovery workflow | Separate trusted runner and network |

Host services also provide clock synchronization, enforcing SELinux, firewalld,
TPM PKCS#11 support and credential renewal timers. Shared Quadlet roles own
container/network definitions; generated units use Quadlet's install section.

## Request and data flow

Users reach nginx through the service DNS names over HTTPS. Gitea, NetBox and
Grafana authenticate humans through OpenBao OIDC, backed by LLDAP passwords and
roles. OpenClaw uses its own Gateway token and device pairing. See
[identity](identity.md) for first login and service identity boundaries.

The controller owns static appliance inventory, protected bootstrap inputs and
the retained OpenBao management credential. NetBox is the source of inventory
for managed-host discovery, not for bootstrapping InfraBox itself. Platform reads
prepared NetBox inventory and trusted Config Context, fetches scoped credentials
from OpenBao and publishes per-host facts as Gitea workflow artifacts. OpenClaw
can request that fixed workflow and propose NetBox enrichment; writes require
separate confirmation. See [Platform](platform.md) and [discovery](openclaw-discovery.md).

OpenClaw resolves model keys through the bundled Vault plugin and its restricted
periodic token. The certificate Agent has a separate AppRole and owns routine
certificate renewal. Ansible handles repair using independent controller
credentials. Neither runtime Agent receives the controller root token.

## Network and execution boundaries

Public ports are TCP 22 (host SSH), 80, 443 and 2222 (Gitea SSH). Backend ports
are not exposed on external interfaces. nginx applies route restrictions in
addition to host/network filtering; private container DNS is separate from
public service DNS. Client trust uses the exported InfraBox RootCA.

The generic runner uses label `infrabox-shell`, a mapped host UID and its own
network. It has shell/Git, no host runtime socket, Docker execution or Node
actions. Jobs can reach Gitea/NetBox HTTPS but not backend databases, Redis,
host management, Vault, Grafana or OpenClaw. Jobs share the runner container and
persistent work area; stronger per-job isolation is not provided.

The optional Platform runner has independent credentials and a separate network.
It can reach authorized managed targets and scoped local HTTPS services; it
must not inherit generic-runner or provisioner credentials. Its trusted Config
Context and source branch are execution inputs, not untrusted chat instructions.

OpenClaw has no shell/terminal execution, host runtime socket, TPM access or
managed-host SSH key. The scanner's raw-packet capability belongs only to its
separate worker. Model-visible facts and artifacts are data, never instructions.
See [OpenClaw](openclaw.md) for tools, consent and credential delivery details.

## Limits

This is a single-node deployment with shared failure domains. HA, full-appliance
backup/restore and TPM-loss recovery are not implemented. Monitoring has no
Alertmanager notification delivery, and whole-host loss needs an external
observer. Providers require operator-supplied credentials; a healthy Gateway
does not prove a model call works. See [security](security.md) and
[monitoring](monitoring.md) for the corresponding operational limits.

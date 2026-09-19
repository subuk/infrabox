# InfraBox

InfraBox turns an AlmaLinux 10 host into a single-node infrastructure appliance
using Ansible, Podman Quadlet and systemd. It brings Git and CI, infrastructure
inventory, secrets, central identity and monitoring together behind HTTPS.

It is intended for operators who want to manage a small infrastructure environment
from one self-hosted system and are comfortable administering Linux and Ansible.
OpenClaw adds a conversational interface for inventory onboarding and discovery;
model credentials remain operator-supplied.

## What it provides

| Capability | Service |
| --- | --- |
| Git repositories and Actions jobs | Gitea, SSH on port 2222, isolated shell/Git runner |
| Infrastructure inventory and IPAM/DCIM | NetBox |
| Secrets, private PKI and TPM-backed auto-unseal | OpenBao and certificate Agent |
| Central user accounts and application sign-in | LLDAP and OpenBao OIDC |
| Service and integration health | Prometheus and the Grafana **InfraBox Health** dashboard |
| Conversational inventory work | OpenClaw with confirmed NetBox writes, subnet scanning and web search |
| Optional managed-host facts discovery | Dedicated Platform runner and fixed Gitea workflow |
| Managed server configuration | NetBox desired state, Platform roles and configure check/apply workflow |

nginx is the public HTTPS entry point. Application containers use internal
PostgreSQL/Redis services; SELinux and firewall isolation remain enforced.
See [architecture](docs/architecture.md) for component and network boundaries.

## Prerequisites

- An AlmaLinux 10 host with SSH key authentication, sudo and SELinux support.
- A persistent TPM 2.0 device at `/dev/tpmrm0`; persistent virtual TPM is supported.
- A controller with Python/venv and access to the pinned Ansible dependencies.
- Service DNS, a verified SSH host key, and access to package/container registries.
- Compatible LAN/VPN and runner subnets; use x86_64 for the included scanner build.

Use your own host and domain. The checked-in development inventory belongs to a
specific development environment, and `ansible.cfg` selects it by default.
The repository does not publish a measured minimum hardware profile.

## Install

Follow the complete [installation and bootstrap guide](docs/installation.md)
from the repository root. It contains the configuration values and ordered
commands; the installation flow is:

1. Create a local inventory with your target, domain and explicit TPM choice.
2. Install pinned controller dependencies and generate protected per-appliance inputs.
3. Apply foundation twice and verify it.
4. Start OpenBao in temporary localhost-only HTTP mode; explicitly initialize it
   once, retain recovery material and bootstrap PKI.
5. Start the certificate Agent, verify its certificates and install host trust.
6. Explicitly switch OpenBao and the Agent to verified HTTPS.
7. Deploy `site.yml`, repeat for stability, then run `verify.yml`.

**Do not start an empty appliance with `site.yml`.** An existing appliance uses
the [operations and repair procedure](docs/operations.md), without reinitialization.

## First use

Import `artifacts/<inventory_hostname>/root-ca.crt` into your client trust store,
then open `https://<infrabox_domain>/`. With example domain `infrabox.example.com`:

| Service | Example address | Sign-in |
| --- | --- | --- |
| Home | `https://infrabox.example.com/` | Links to the main services |
| LLDAP | `https://ldap.infrabox.example.com/` | Technical administrator for initial account creation |
| Gitea | `https://git.infrabox.example.com/` | Personal account through OpenBao OIDC |
| NetBox | `https://netbox.infrabox.example.com/` | Personal account through OpenBao OIDC |
| Grafana | `https://grafana.infrabox.example.com/` | Personal account through OpenBao OIDC |
| OpenBao | `https://vault.infrabox.example.com/login/` | Personal LDAP password; self-service profile |
| OpenClaw | `https://claw.infrabox.example.com/` | Separate Gateway token and device pairing |

Use `svc-identity-admin` and the protected `lldap_admin_password` to create a
personal LLDAP account. Set `infraboxIdentityType=human` and assign the required
`infrabox:*` roles. Your first OpenBao login creates the identity and asks for
email/display name; no per-user Ansible run is needed. Mandatory MFA is currently
disabled. Follow [identity and access](docs/identity.md) for details.

In Grafana, open **InfraBox / InfraBox Health** after fresh observations arrive.
For chat, follow [OpenClaw setup](docs/openclaw.md) and configure a
[model provider](docs/openclaw-providers.md), including a local LAN Ollama server with separate selectable endpoints. Enable [Platform](docs/platform.md)
only after preparing its source and managed-host credentials.
[Server configuration](docs/platform-configuration.md) uses the same trusted
runner with separate PR check and explicit apply modes. Platform remembers
SSH host keys on first connection and rejects changed keys; adding a managed
host requires no Ansible run to update SSH trust.

In OpenClaw, **Inspect / Query** reads NetBox, **Network Scan** probes an approved
subnet, and **Ansible Discovery** collects facts from known hosts. Discovery automatically applies its [owned fields](docs/discovery-reconciliation.md)
to NetBox, including VM disks and identifiable physical disk modules; manual
inventory changes require a confirmed proposal. See [Gateway setup](docs/openclaw.md) for workflows
and the `openclaw_skills` tag for updating only the managed skill files.

## Security and recovery

Keep protected controller inputs, the initial OpenBao root token and recovery
shares private and associated with the correct appliance. Runtime integrations
use scoped credentials. Never clear the initialized TPM, recreate its seal key
or discard OpenBao data to fix an outage. Full backup/restore, TPM-loss recovery
and HA are not implemented. Read [secrets, certificates and recovery
boundaries](docs/security.md) before deployment or repair.

## Documentation and development

The [documentation index](docs/README.md) maps installation, identity, architecture,
OpenClaw/Platform, operations, monitoring and troubleshooting guides.
For contributions, use [development and acceptance](docs/development.md) and
[AGENTS.md](AGENTS.md). [Implementation status](IMPLEMENTATION_STATUS.md) records
historical evidence and outstanding checks; it is not an installation guide or
proof of health for a new target.

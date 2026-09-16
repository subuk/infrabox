# InfraBox documentation

Start with the [project README](../README.md) for the product overview and first
steps. These guides describe the current repository; historical deployment
results do not establish the health of your appliance. Commands in guides are
operator procedures, not authorization to run them during documentation work.

## Install and understand

| Guide | Use it to |
| --- | --- |
| [Installation and bootstrap](installation.md) | Prepare inventory and controller inputs, follow the explicit HTTP-to-HTTPS bootstrap, then complete the stack |
| [Architecture](architecture.md) | Understand services, data flow, execution/network boundaries and single-node limits |
| [Identity and access](identity.md) | Create a personal account, sign in and understand human/service identities |
| [Secrets, certificates and recovery](security.md) | Handle controller secrets and client trust; understand rotation, repair and unsupported recovery |

## Use integrations

| Guide | Use it to |
| --- | --- |
| [OpenClaw Gateway](openclaw.md) | Pair a client, understand NetBox onboarding, scan consent, tools and token recovery |
| [OpenClaw model providers](openclaw-providers.md) | Store provider keys in OpenBao, configure SecretRefs and select a session model |
| [Platform discovery](platform.md) | Prepare the trusted runner, source revision, managed-host credentials and Config Context |
| [OpenClaw discovery and enrichment](openclaw-discovery.md) | Launch selected-host discovery, resume requests and review confirmed NetBox proposals |

## Operate

[Operations and maintenance](operations.md) covers established-appliance changes,
component ownership and home-page updates. [Monitoring](monitoring.md) explains
the health dashboard, cadence, retention, coverage and stabilization requirements.
Backup/restore is not implemented; read the [recovery scope](security.md#recovery-scope)
for the distinction between credential/certificate repair and lost-appliance recovery.

## Troubleshooting

| Symptom | Runbook |
| --- | --- |
| Disk, memory, clock or host availability | [Host](runbooks/host.md) |
| Application, TLS or central login failure | [Services and central identity](runbooks/services.md) |
| Gateway, Vault SecretRef or NetBox MCP failure | [OpenClaw](runbooks/openclaw.md) |
| CI execution or canary cleanup failure | [Runner](runbooks/runner.md) |
| Missing, stale or inconsistent health evidence | [Monitoring coverage](runbooks/monitoring.md) |

## Develop

[Development and acceptance](development.md) maps local checks and disruptive
acceptance boundaries. [AGENTS.md](../AGENTS.md) contains repository agent
instructions, target selection and secret-handling rules. Documentation-only
KRG-19 work uses manual/static inspection only, without executable checks or
appliance access.

## Design and implementation history

The following documents stay at the repository root to preserve existing links
and development references. They are implementation contracts/history, not
alternative installation instructions. Later accepted changes supersede earlier
scope decisions; follow the current guides above for operations.

| Document | Purpose and qualification |
| --- | --- |
| [Original MVP plan](../InfraBox_plan.md) | Foundational architecture and invariants; local-admin-only, no-dashboard and no-AI scope was subsequently extended |
| [Implementation status](../IMPLEMENTATION_STATUS.md) | Dated, target-specific evidence, failures and remaining work; older entries are intentionally retained |
| [OpenClaw integration plan](../InfraBox%20%E2%80%94%20OpenClaw%20Integration%20Implementation%20Plan.md) | Gateway isolation, scoped token and renewal contract; later integrations extend its initial tool scope |
| [NetBox onboarding plan](../InfraBox%20%E2%80%94%20OpenClaw%20NetBox%20Onboarding%20Implementation%20Plan.md) | MCP provisioning and confirmed inventory-write contract; current identity behavior is described in the access guide |
| [Subnet scanning plan](../InfraBox%20%E2%80%94%20OpenClaw%20Subnet%20Scanning%20Implementation%20Plan.md) | Fixed probe limits, worker isolation and per-call consent |
| [Monitoring plan](../KRG-15%20%E2%80%94%20Monitoring%20Implementation%20Plan.md) | Monitoring design and acceptance contract; current runtime details live in the monitoring guide |

The [identity guide](identity.md) links the KRG-17 design and explains its later
first-login/MFA amendment. Historical examples and target addresses in plans and
status records must not be copied into a new deployment without operator choices.

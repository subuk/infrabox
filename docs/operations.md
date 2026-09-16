# Operations and maintenance

[Documentation index](README.md) · [Monitoring](monitoring.md)

## Apply or repair configuration

For an established appliance, use its existing inventory, protected inputs and
controller initialization record. The examples use alias `infrabox1`; substitute
your alias consistently. Keep SSH host-key checking enabled and select only the
authorized target, adding `--limit` if the inventory contains other appliances.

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml site.yml -T 60 -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml verify.yml -T 60 -e @.secrets/infrabox1/inputs.json
```

`site.yml` includes monitoring baseline/stabilization as well as component
verification. Stop on a failed stage and repair the owning configuration before
continuing. Run changes sequentially against a host. Preserve runtime data,
identity, credentials and CA/TPM state; never reinitialize to repair an outage.

For expired certificates or certificate Agent credentials, use:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml pki.yml -e @.secrets/infrabox1/inputs.json
```

Recovery authenticates through the protected local Unix socket, repairs expired
leaves and Agent credentials, and resumes verified HTTPS. It does not enable
network HTTP or bypass certificate validation. See [security and recovery
boundaries](security.md) before changing credentials or handling lost state.

## Component ownership

| Entry point | Purpose |
| --- | --- |
| `pki.yml` / `certificate-agent.yml` | PKI recovery / certificate Agent configuration |
| `services.yml` | PostgreSQL and Redis backends |
| `lldap.yml` / `identity.yml` | Directory runtime / role catalog and authentication infrastructure |
| `applications.yml` | Gitea and NetBox configuration |
| `edge.yml` | nginx HTTPS routes and home page |
| `automation.yml` | Optional [Platform runner and source synchronization](platform.md) |
| `agent.yml` | [OpenClaw Gateway and integration credentials](openclaw.md) |
| `observability.yml` | Grafana, exporters, integration checks and Prometheus |
| `monitoring-deploy.yml` | [Monitoring update with baseline and stabilization](monitoring.md#deployment-and-tests) |
| `ci.yml` | Generic Gitea runner |

These are component entry points, not an alternative bootstrap order. For user
creation or profile changes follow [identity](identity.md); no `identity.yml`
rerun is required. Configuration is Ansible-owned. Carry necessary runtime fixes
back into their owning configuration so a rerun and reboot preserve them.

## Home page

The base-domain home page links to Gitea, NetBox, Grafana, OpenBao and OpenClaw.
It uses the effective nginx hostnames, including `openclaw_hostname`; it does
not check service health. LLDAP is reached directly at `https://ldap.<domain>/`.

The nginx role installs the static page at
`/usr/share/nginx/html/infrabox/index.html` and adds the main-domain vhost.
On an existing appliance, deploy the page and vhost through the nginx role:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml edge.yml --tags configure,service
.venv/bin/ansible-playbook -i inventories/local/hosts.yml edge.yml --tags nginx_landing
```

The first command applies nginx configuration through its normal handler. For
subsequent page-only updates, use just the second command: it deploys static
files and checks the home page without reloading or restarting nginx. HTML
responses use `Cache-Control: no-cache`, allowing browser storage with
revalidation on the next visit or refresh. The page does not require a frontend
build step. The `nginx_landing` tag assumes the vhost is already installed.

## Health and troubleshooting

Open **InfraBox / InfraBox Health** in Grafana for service health, integration
checks, freshness, resources and pending/firing alerts. Prometheus remains
internal. Alertmanager and notification delivery are not configured. A green
application page alone does not establish that integrations work.

Use [monitoring](monitoring.md) for cadence, retention and evidence requirements,
and the [runbook index](README.md#troubleshooting) to select a failure procedure.
The read-only OpenClaw `infrabox_health` tool exposes bounded health results;
it cannot repair services or launch probes. Whole-host loss requires an external
observer, because the appliance cannot report through its own failed network.

Inspect only necessary log and container fields: full environment/inspection
output can expose credentials. Preserve sanitized evidence and distinguish fresh
observations from historical results in [implementation status](../IMPLEMENTATION_STATUS.md).

## Updates and unsupported recovery

Versions, checksums and image digests are pinned. Native foundation packages
follow distribution versions; no automatic OS upgrade is run. Treat upgrades as
separate reviewed changes, preserve state and protected controller inputs, and
account for application migrations before attempting a rollback. Reverting an
image alone does not guarantee state compatibility.

Full backup/restore, TPM-loss recovery and HA are not implemented. See
[recovery boundaries](security.md#recovery-scope); controller recovery shares and
a public CA export are not a full appliance backup.

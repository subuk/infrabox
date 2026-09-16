# OpenClaw Gateway

[Documentation index](README.md) · [Model providers](openclaw-providers.md)

OpenClaw runs as a non-root Podman container at `https://claw.<infrabox_domain>`.
nginx terminates HTTPS and proxies WebSockets to `127.0.0.1:18789`. The existing
certificate Agent adds the hostname to nginx's certificate. OpenClaw augments
Node's public CA trust with the InfraBox RootCA; its own TLS server is disabled.
nginx overwrites forwarded client IPs, and OpenClaw trusts only the discovered
backend bridge gateway for proxy attribution. Authentication remains token-based.
The host-only OpenBao loopback alias is excluded from the container's hosts file,
so backend DNS resolves OpenBao correctly.

`agent.yml` deploys OpenClaw. The certificate Agent playbook is now
`certificate-agent.yml`; `pki.yml` includes it. On an established appliance:

```sh
.venv/bin/python scripts/create-controller-secrets.py
.venv/bin/ansible-playbook -i inventories/local/hosts.yml pki.yml agent.yml edge.yml \
  -e @.secrets/infrabox1/inputs.json
```

These commands assume the `infrabox1` alias; substitute your alias in both the
generator (`--inventory-hostname`) and protected input path. Integration
acceptance is separate and requires authorization for Gateway restarts.

The generator adds `openclaw_gateway_token` to existing inputs without replacing
other credentials. This token authenticates Gateway clients and is separate from
the OpenBao service token. Retrieve it privately from your controller inputs for
the Control UI or CLI; never put it in a URL, inventory, or `openclaw.json`.
Keep the application's device-pairing checks enabled when enrolling clients.
After entering the Gateway token, approve the specific pending browser/device
request from the appliance:

```sh
sudo podman exec openclaw node openclaw.mjs devices list --json
sudo podman exec openclaw node openclaw.mjs devices approve <request-id>
```

Check the requested device and scopes before approval; do not disable pairing or
approve unrelated pending requests.

Review these settings in your local inventory's `group_vars/all.yml`:

| Setting | Local setup choice |
| --- | --- |
| `openclaw_hostname` | Defaults to `claw.<infrabox_domain>`; configure DNS to the appliance. |
| `openclaw_version`, `openclaw_image_digest`, `openclaw_image` | Pinned official release and digest. Update version and digest together. |
| `openclaw_memory_limit`, `openclaw_cpu_limit`, `openclaw_pids_limit` | Defaults: 2 GiB, 2 CPUs, 512 processes. |
| `openclaw_openbao_kv_mount` | KV v2 mount, default `kv`; an existing incompatible engine is rejected. |
| `openclaw_openbao_token_period` | Whole hours, default `168h` (seven days). |
| `openclaw_openbao_token_renew_calendar` | Default midnight and noon daily. |
| `openclaw_http_proxy`, `openclaw_https_proxy`, `openclaw_no_proxy` | Optional runtime proxy; internal service names must bypass it. Keep proxy credentials in protected inputs. |
| `openclaw_model_providers` | Optional provider configuration using Vault SecretRefs; empty by default. |

The pinned image uses UID/GID 1000. Configuration and credentials live under
`/etc/infrabox/openclaw`. Ansible builds a local runtime image from the pinned
official image, correcting `/usr/local/bin/node` ownership to UID/GID 1000
(mode 0755). OpenClaw's exec SecretRef validation requires its executable to be
owned by the running user; the official image supplies a root-owned Node binary.
With NetBox onboarding enabled, the build also installs NetBox MCP 0.2.0 using
the committed npm lockfile and integrity hashes. Only image construction needs
registry access; container startup installs nothing. The container still runs
without capabilities.
Ansible verification runs the full SecretRef audit to catch resolver failures.
Persistent state and workspace live under
`/srv/infrabox/openclaw`. The container receives only these component mounts and
the public RootCA. Configuration is read-only inside the container; change the
inventory and rerun `agent.yml` to update it. Its token directory is mounted read-only, so atomic token
replacement remains visible. It has no host runtime socket, TPM device, SSH
credentials, database credentials, or arbitrary infrastructure execution interface.
Managed-host execution is limited to the fixed [discovery tools](openclaw-discovery.md). Nested
sandboxing, terminal access, and execution tools are disabled for this stage.
Runner jobs cannot access the OpenClaw nginx route.

## OpenBao credentials and recovery

OpenClaw uses the bundled Vault plugin with `token_file` authentication. There is
no OpenClaw AppRole or additional OpenBao Agent. The orphan service token has
exactly the `infrabox-openclaw` policy, without `default`: read access under
`kv/data/openclaw/*`, lookup-self, and renew-self. It cannot create tokens, issue
certificates, administer OpenBao, or read unrelated KV paths.

`openclaw-token-renew.timer` runs the native `bao` renewal helper twice daily and
five to ten minutes after boot. Renewal preserves the token value. The helper
cannot create replacement credentials; a failed renewal remains visible through
systemd. Its seven-day period requires a successful renewal within that window.
After an outage longer than the period, run the established-appliance playbooks
above. Ansible uses the retained controller management credential to repair PKI
and issue a replacement service token, then restarts OpenClaw. Healthy tokens
survive ordinary reruns. A token with incorrect properties is replaced, and its
superseded token is retired only after the replacement passes Gateway and bundled
resolver checks.

## NetBox conversational onboarding

On established appliances, `agent.yml` also provisions the NetBox integration:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml agent.yml \
  -e @.secrets/infrabox1/inputs.json
```

Use your selected inventory for another appliance. NetBox and its HTTPS endpoint
must already be healthy. `site.yml` includes this integration on normal full-stack
runs. No model provider is required for deployment or structural verification.

| Setting | Meaning |
| --- | --- |
| `openclaw_netbox_enabled` | Defaults to `true`. Disabling removes the MCP configuration and skill mount; preserves the identity, inventory, and protected credential. |
| `openclaw_netbox_url` | Defaults to `https://netbox.<infrabox_domain>`, the existing nginx HTTPS route. The internal NetBox container endpoint is HTTP and is not used for this integration. |
| `openclaw_netbox_mcp_version` | Pinned to `0.2.0`; change the package manifest and lockfile together when deliberately upgrading. |
| `netbox_openclaw_username` | Dedicated service identity, default `svc-openclaw`. |
| `netbox_openclaw_token_description` | Credential ownership label, default `InfraBox OpenClaw MCP`. Keep it stable after provisioning. |

The service identity authenticates with its own LLDAP password only to obtain
its native application token. It has no local password, superuser status or
account-administration permissions. Its exact permissions are view/add/change/delete on
the onboarding plan's inventory models and tags, including platforms, MAC
addresses, Config Contexts, and existing untagged records. Native LDAP mirrors its central editor group. The NetBox role configures group
ObjectPermissions, generic hardware types, starter roles, and tags without overwriting
existing inventory. The OpenClaw role invokes those NetBox tasks, then owns
credential storage, materialization, MCP configuration, and the managed skill.

NetBox 4.7's [default permissions](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/netbox/settings.py)
grant every user permission to manage their own API tokens,
bookmarks, subscriptions, and notifications. A small NetBox authorization backend
excludes those defaults for LDAP service identities and denies fallback grants.
A separate final authentication backend rejects local-password fallback after
native LDAP has been attempted. Human accounts retain their normal self-service permissions. This backend
is mounted read-only into both NetBox containers; deploying its configuration
requires their normal service restart. Inventory access still comes from NetBox
object permissions, and the integration's effective permissions are checked exactly.

The NetBox v2 API token is write-enabled and **has no expiration**. OpenBao KV v2
stores it at `kv/openclaw/integrations/netbox`, field `apiToken`. The runtime file
is `/etc/infrabox/openclaw/secrets/netbox-token` (UID/GID 1000, mode 0600), visible
inside the read-only secrets-directory mount as `/run/openclaw-secrets/netbox-token`.
The launcher passes it only to the MCP child's environment. It is absent from
`openclaw.json`, the skill, and the Gateway environment. The existing OpenBao
token and certificate Agent identities remain separate.

Healthy Ansible reruns preserve the token. To repair a revoked token or restore
a missing runtime file, rerun `agent.yml` with the protected inputs. Ansible
validates a replacement through HTTPS before publishing it to OpenBao, atomically
replaces the runtime file, and restarts OpenClaw. It disables superseded tokens
belonging to this exact service identity and description only after verification.
A persistent `netbox-restart-required` marker allows an interrupted deployment to
resume safely. Credential permissions are enforced on every provisioning run.

The `messaging` tool profile exposes the five NetBox MCP tools. A workspace-only
`read` tool loads the Ansible-managed skill, mounted read-only at
`/home/node/.openclaw/workspace/skills/netbox-onboarding/SKILL.md`. Shell, terminal,
process, browser, node access, file writes, and delegation remain denied. The
skill requires reading NetBox, presenting a concrete proposal, and receiving
explicit confirmation before each logical write batch, including direct commands
such as "add server02". This confirmation is a skill policy; NetBox permissions
independently restrict access to the permitted models. Deletion proposals must
identify exact objects, affected relationships, and cascading deletions before
confirmation. Migrations verify the replacement and transferred relationships
before deleting the superseded object. Config Context and device/VM local context
may be updated after confirmation; proposals explain effects on future Ansible
runs and preserve unrelated keys. Credentials belong in OpenBao, not context.

To use the workflow:

1. Configure a model provider using an OpenBao SecretRef in the [provider guide](openclaw-providers.md).
2. Open `https://claw.<infrabox_domain>`, start a new chat, and select the model.
3. Describe your infrastructure and answer the necessary follow-up questions.
4. Review the proposed inventory, placeholder hardware/interfaces, and tags.
5. Confirm the proposal, then inspect the resulting records in NetBox.

`infrabox-user-provided` records conversational provenance. `infrabox-managed`
selects objects for later automation; it is not an OpenClaw permission boundary.
You can ask OpenClaw to add or remove that tag association after confirmation.
Unrelated tags are preserved. A generic hardware type or `infrabox-unknown`
interface is an explicit placeholder, not a detected fact.

Conversational onboarding records user-provided information. With Platform
discovery enabled, OpenClaw can also run the fixed Ansible workflow and propose
confirmed enrichment from actual per-host facts; see [discovery and enrichment](openclaw-discovery.md). Conversational acceptance
is performed manually by the operator. Automated verification opens an MCP
session, checks the five tools, reads NetBox with verified TLS, and checks
credentials, effective object permissions, and isolation. It makes no model calls,
creates no temporary inventory fixtures, and performs no live write/delete probes.

## Optional subnet scanning

`openclaw_subnet_scan_enabled` defaults to `true`. The native
`infrabox_scan_subnet` tool accepts one canonical IPv4 CIDR from `/24` through
`/32`, with no address allowlist. It discovers responsive addresses, checks 28
common TCP ports, and attempts Nmap OS fingerprinting. Every call presents a
one-time approval prompt naming the subnet and explaining active probes,
possible alerts or disruption, and uncertain OS guesses. Approving confirms
that this is your own local network. Denial, timeout, or an unavailable approval
surface blocks execution; persistent approval is not offered.
Setting it to `false` stops the worker and removes its container unit, the
Gateway tool/plugin configuration, and the socket mount. Cached images and the
dedicated network are retained for later re-enablement.

Use an approval-capable OpenClaw UI or chat channel. Scans can inform NetBox
onboarding, but inventory writes still require a separate proposal and
confirmation. Results distinguish observed IPs/open ports from heuristic OS
matches. Missing hosts and timeouts do not prove absence. Larger networks must
not be split into batches to evade the limit.

Nmap runs in a separate container with only raw-packet capability, its own
automatically allocated bridge, fixed arguments, and a three-minute deadline.
The Gateway keeps its existing privileges and connects over a private Unix
socket. Check that Podman's allocated scanner subnet does not overlap your
intended scan targets or LAN/VPN routes. Routed scanning may limit discovery
and fingerprint accuracy. The checksum-locked package build supports x86_64.
The full port list and runtime limits are in the
[subnet-scanning contract](../InfraBox%20%E2%80%94%20OpenClaw%20Subnet%20Scanning%20Implementation%20Plan.md).

Apply changes with `agent.yml` and your explicit inventory and protected inputs
as above. Component verification checks isolation, Nmap version, socket access,
and rejected invalid targets without sending scan probes or invoking a model.
Local test entry points are documented in the [development guide](development.md).
Conversational approval and a real network scan remain operator checks.

## Web search through OpenAI

`openclaw_web_search_enabled` defaults to `true` and adds `web_search` to the
allowed tools independently of NetBox onboarding and subnet scanning. Select
one of your configured direct OpenAI Responses models (`provider: openai`,
`api: openai-responses`, and the official OpenAI API endpoint). OpenClaw then
uses OpenAI's hosted search with that model's existing OpenBao SecretRef.
Model and hosted-search usage is charged through the same OpenAI account.

The configuration deliberately leaves `tools.web.search.provider` unset, as
required for the [native OpenAI search path](https://docs.openclaw.ai/tools/web#auto-detection).
There is no separate search API key or managed search provider. Search through
other model providers or OpenAI-compatible proxies needs separate configuration.
Set `openclaw_web_search_enabled: false` to disable search explicitly.

Use search for general questions, current information, or product research.
For NetBox onboarding, the managed skill prefers manufacturer product pages and
datasheets, cites sources, distinguishes public specifications from the actual
device's configuration, and keeps private inventory details out of queries.
Researched fields remain part of a separately confirmed NetBox write proposal.
Browser automation and shell tools remain disabled.

Keep your `openclaw_model_providers` definitions in controller inputs or the
selected inventory using SecretRefs; see the [provider guide](openclaw-providers.md).
Changes made only to the appliance's generated JSON can be replaced by Ansible. Apply `agent.yml`
with the selected inventory and protected inputs. Verification exercises the
pinned OpenClaw native search wrapper and effective tool policy without sending
a model/search request; a real conversational search remains an operator check.

## Operations and validation

On the appliance:

```sh
sudo systemctl status openclaw openclaw-token-renew.timer
sudo journalctl -u openclaw -u openclaw-token-renew.service
sudo systemctl list-timers openclaw-token-renew.timer
sudo systemctl start openclaw-token-renew.service
sudo systemctl restart openclaw
curl --fail http://127.0.0.1:18789/healthz
sudo podman exec openclaw node -e \
  'fetch("http://127.0.0.1:18789/readyz").then(r => process.exit(r.status === 200 ? 0 : 1))'
```

Probe readiness inside the container or through public HTTPS. Host-to-container
traffic shares nginx's trusted bridge address, and the Gateway rejects readiness
requests from that address without an attributable non-loopback client. The
public HTTPS route receives accurate client headers from nginx automatically.

If SecretRefs stop resolving, first check OpenBao health and
`systemctl status openclaw-token-renew.service`. The role's verification task
checks the token through the running container without printing it. For an
expired or revoked token, rerun `agent.yml --tags openclaw` with your explicit
inventory and protected inputs; use `pki.yml` first if certificates also expired.
Then verify `/readyz` again.

Treat logs and container inspection as sensitive; complete environment output
contains the Gateway token. For upgrades, back up state and protected controller
inputs, select a reviewed official version/digest pair, rerun Ansible, and run
acceptance. Reverting an image does not guarantee compatibility with migrated
application state.

`acceptance-openclaw.yml` temporarily restarts the Gateway and uses a disposable
KV fixture to test the bundled resolver and runtime SecretRef reload. It also
checks token renewal, denied OpenBao operations, Gateway authentication, and
WebSockets through nginx using a temporary, explicitly paired client. It removes
that client, restores configuration, and deletes the KV fixture.
`acceptance-openclaw-token-lifecycle.yml` tests period changes, superseded-token
revocation, failed renewal of a revoked token, and normal Ansible repair. It
requires the default seven-day period and restores it after the period test.
`acceptance-openclaw-expiry.yml` uses a five-second periodic fixture to test real
expiry and restores the configured period through normal Ansible repair.
`acceptance-openclaw-reboot.yml` additionally reboots the appliance, checks that
the token survives, waits for scheduled boot renewal, and repeats integration
acceptance. Read [implementation status](../IMPLEMENTATION_STATUS.md) for what
has actually passed on the test host.

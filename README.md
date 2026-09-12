# InfraBox Ansible

InfraBox deploys a single-node AlmaLinux 10 appliance through Ansible and Podman
Quadlet. The implementation contract is [InfraBox_plan.md](InfraBox_plan.md);
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) records the completed
development-VM acceptance checks. The MVP is implemented and verified on the
development host.

For AI-assisted bootstrap and maintenance, see [AGENTS.md](AGENTS.md) for
repository instructions, deployment workflow, and required validation.

SSH key authentication, sudo, SELinux support, and a persistent TPM 2.0
device at `/dev/tpmrm0` are required. Virtual TPM is supported. This README
uses `infrabox.example.com` as an example domain. Production inventory is
intentionally empty.

## Configuration for a local setup

Create a separate inventory for your appliance. The checked-in development
inventory contains deployment-specific values; replace them before use.

```sh
mkdir -p inventories/local/group_vars
cp inventories/development/hosts.yml inventories/local/hosts.yml
cp inventories/development/group_vars/all.yml inventories/local/group_vars/all.yml
export ANSIBLE_INVENTORY="$PWD/inventories/local/hosts.yml"
```

`ANSIBLE_INVENTORY` makes the commands below use your local inventory instead
of the default in `ansible.cfg`. Export it again in a new shell, or pass
`-i inventories/local/hosts.yml` to each Ansible command.

Edit `inventories/local/hosts.yml` to set the target address and SSH user. Keep
the `infrabox` group, which the playbooks target. For example:

```yaml
all:
  children:
    infrabox:
      hosts:
        infrabox1:
          ansible_host: 192.0.2.10  # Replace with your appliance address.
          ansible_user: almalinux  # Replace with your SSH login.
          # ansible_ssh_private_key_file: ~/.ssh/id_ed25519
```

`infrabox1` is an example inventory alias, not a DNS name. Keeping that alias
matches the supplied secret generator and command examples. If you rename it,
update the generator's output directory and the `-e @.secrets/.../inputs.json`
paths below. Initialization records and exported artifacts are stored under
`.secrets/<inventory_hostname>/` and `artifacts/<inventory_hostname>/`.

Review these settings in `inventories/local/group_vars/all.yml`:

| Setting | What to configure |
| --- | --- |
| `infrabox_domain` | Your service base domain, such as `infrabox.example.com`. Configure wildcard DNS for `*.infrabox.example.com`, or individual `git`, `netbox`, `grafana`, and `vault` records, pointing to the appliance. |
| `infrabox_internal_domain` | The private container DNS suffix. The supplied `infrabox.internal` can normally remain; it does not need public DNS records. |
| `openbao_agent_openbao_address` | Match the internal suffix: `https://openbao.<infrabox_internal_domain>:8200`. This is the Agent's internal endpoint, not the public `vault` URL. |
| `openbao_tls_enabled` | Keep `true` for the final configuration. Use the explicit temporary overrides in the bootstrap procedure for a new appliance. |
| `tpm2_pkcs11_device` | The host TPM resource-manager device, normally `/dev/tpmrm0`. |
| `tpm2_pkcs11_key_bits` | Set the seal-key size supported by your TPM before initialization. The role default is `4096`; the copied development inventory overrides it to `3072`, so review that value explicitly. |

Keep the supplied storage/configuration paths, TPM token/key labels, and runtime
UID/GID values for a standard installation. Some helper scripts and systemd units
also use fixed paths, so changing a path variable alone is not a supported
relocation procedure. Once initialized, preserve the TPM store, seal-key identity,
and corresponding OpenBao data.

Check that the runner subnet `10.90.0.0/24` does not overlap your LAN or VPN.
If it must change, coordinate `gitea_runner_subnet`, `gitea_runner_gateway`,
and the runner source-range rule in `roles/nginx/templates/nginx.conf.j2`.
The backend network uses Podman's automatic subnet allocation. The standard
public ports are TCP 22, 80, 443, and 2222; allow them through any upstream
firewall as needed.

Generate controller secrets for your own appliance using the next section.
The generator preserves an existing inputs file; it does not generate a fresh
identity over another appliance's saved credentials. Keep passwords and TPM PINs
in the protected controller inputs rather than inventory files.

## Controller setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/ansible-galaxy collection install -r requirements.yml -p .ansible/collections
python3 scripts/create-controller-secrets.py
```

The secret generator creates `.secrets/infrabox1/inputs.json` once with mode 0600
inside private directories. Existing values are preserved. `.secrets/` is ignored
by Git. Protect these files and never print their contents in logs. Initialization
later writes `.secrets/infrabox1/openbao-init.json`, including the retained root
token and recovery shares. OpenBao Agent receives only its dedicated AppRole.

Verify the VM's SSH host key before deployment. Host key checking remains enabled.
Commands below assume your normal known-hosts file contains the correct key.
If you use a separate known-hosts file, pass its path explicitly, for example:

```sh
--ssh-common-args='-o UserKnownHostsFile=/path/to/known_hosts'
```

## Bootstrap stages

Your local inventory should describe the final TLS state.
For a **new, uninitialized VM only**, use explicit localhost HTTP overrides during
bootstrap. Run each stage and resolve failures before proceeding.

```sh
.venv/bin/ansible-playbook foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook verify-foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook openbao-runtime.yml -e @.secrets/infrabox1/inputs.json -e openbao_tls_enabled=false
.venv/bin/ansible-playbook pki-bootstrap.yml -e openbao_bootstrap_initialize=true
.venv/bin/ansible-playbook pki-bootstrap.yml
.venv/bin/ansible-playbook certificate-agent.yml -e openbao_agent_openbao_address=http://127.0.0.1:8200
.venv/bin/ansible-playbook host-trust.yml
```

Repeated provisioning must preserve TPM objects, OpenBao initialization, and CA
keys. The TPM role refuses to create missing seal material over existing OpenBao
data. Select the TPM key size in your local inventory before initialization;
the role default is RSA-4096. There is no automatic key-size or software-unseal
fallback.

**OpenBao HTTP is temporary and localhost-only.** After certificate verification,
explicitly select the final inventory values, using your internal DNS suffix:

```yaml
openbao_tls_enabled: true
openbao_agent_openbao_address: "https://openbao.{{ infrabox_internal_domain }}:8200"
```

Then apply runtime and Agent configuration:

```sh
.venv/bin/ansible-playbook openbao-runtime.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook certificate-agent.yml
```

Do not leave the appliance permanently in bootstrap HTTP mode. No automatic
transport transition or fallback is implemented. The [OpenBao Unix listener](https://openbao.org/docs/configuration/listener/unix/)
is restricted to a private directory and mode 0600 for authenticated local
administration without exposing another TCP endpoint.

For an established appliance, deploy or repair the full stack with:

```sh
.venv/bin/ansible-playbook site.yml -T 60 -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook verify.yml -T 60 -e @.secrets/infrabox1/inputs.json
```

`site.yml` applies foundation, expiry recovery, PKI, databases, applications,
HTTPS proxy, monitoring, and runner, then verifies the final state. Component
playbooks remain available for targeted changes. No initialization is automatic.

## Services

| Service | Address | Local administrator |
| --- | --- | --- |
| Gitea | https://git.infrabox.example.com | `admin` |
| NetBox | https://netbox.infrabox.example.com | `admin` |
| Grafana | https://grafana.infrabox.example.com | `admin` |
| OpenBao | https://vault.infrabox.example.com | retained controller root token |

Passwords are the corresponding `*_admin_password` entries in the protected
controller inputs. Trust the appliance's public RootCA in clients before using
HTTPS. The CA is `/etc/infrabox/pki/root-ca.crt` on the VM and is exported by
PKI configuration to `artifacts/infrabox1/root-ca.crt` on the controller. It
contains no private key. Gitea SSH uses port 2222. Prometheus is available to Grafana internally;
the provisioned **InfraBox / InfraBox Health** dashboard shows continuous service
and integration checks, freshness, resource metrics and Prometheus pending/firing
alerts. Alertmanager is not configured. See [monitoring operations](docs/monitoring.md)
for cadence, runbooks, the read-only `infrabox_health` tool and deployment acceptance.
The private Gitea canary runs every five minutes and retains at most 12 completed
runs for one hour, with no artifacts.

The runner label is `infrabox-shell`. Jobs execute in its container with shell
and Git available. This MVP does not provide Node actions or Docker execution.
The runner has its own network and mapped host UID, no runtime socket, and access
to Gitea/NetBox HTTPS. Backend databases, Redis, host management ports, Vault,
and Grafana are blocked. Jobs share this runner's container and persistent work
area; stronger isolation between jobs requires a later execution design.

## Certificate and credential lifecycle

[Agent leased templates](https://openbao.org/docs/agent-and-proxy/agent/template/)
own routine certificate issuance and renewal. Each response produces one
certificate/key/chain generation, validated before publication and reload.
Default leaf lifetime is 14 days. A repeat Ansible run does not restart an
unchanged Agent. Explicit Agent restarts can issue replacement certificates.

Agent SecretIDs have a seven-day lifetime. A native hourly timer checks for daily
rotation using the existing Agent token. The policy permits replacement and
accessor destruction for its own AppRole only, in addition to server certificate
issuance. The replacement login is tested before publication. This timer handles
credentials, not leaf certificate renewal. The development acceptance playbook exercises this rotation and checks that
the old SecretID is rejected.

Ansible can repair a missing/expired Agent SecretID using the protected controller
root token. `pki.yml` first repairs expired leaf certificates through the protected local
Unix listener, then repairs Agent credentials and resumes verified HTTPS. It
never switches the TCP listener back to plaintext. SecretID repair checks the
recorded expiration timestamp and revokes an expired ID even if it is still
returned by lookup: OpenBao 2.6.2 performs
[expired SecretID cleanup asynchronously](https://github.com/openbao/openbao/blob/v2.6.2/builtin/credential/approle/path_tidy_user_id.go).
If failed retries have locked the Agent RoleID, Ansible also unlocks that specific
identity after credential repair. Other identities and the lockout policy are unchanged.

## Host boundaries and maintenance

SELinux stays enforcing. The OpenBao policy grants TPM-device access only to its
dedicated process domain and listener binding on TCP 8200/8201. Firewalld permits
public TCP 22, 80, 443, and 2222. Port 22 is host administration; 2222 is reserved
for Gitea SSH. Backend ports are not published to external interfaces.

**Do not clear the TPM or recreate its token/seal key after initialization.**
Doing so can make the existing OpenBao storage unusable. TPM-loss recovery and
backup/restore are outside the MVP.

Native OS foundation packages currently follow distribution versions; Podman,
TPM packages, controller dependencies, and application image versions are pinned.
No automatic OS upgrade is run.

## Local checks

```sh
.venv/bin/ansible-playbook foundation.yml --syntax-check
.venv/bin/ansible-playbook openbao-runtime.yml --syntax-check
.venv/bin/ansible-playbook pki-bootstrap.yml --syntax-check
.venv/bin/ansible-playbook certificate-agent.yml --syntax-check
.venv/bin/ansible-playbook services.yml --syntax-check
.venv/bin/python -m unittest discover -s tests
```

## Development acceptance

These tests change the development appliance temporarily. Run them sequentially,
with the controller inputs and verified SSH host-key options used above:

```sh
.venv/bin/ansible-playbook acceptance-applications.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook acceptance-renewal.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook acceptance-recovery.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook acceptance-reboot.yml -e @.secrets/infrabox1/inputs.json
```

Application acceptance creates and removes a temporary private repository and
SSH key, testing cloning/pushing over both Git transports and an actual Actions job. Renewal testing
uses three-minute certificates and restores 14-day issuance. Recovery testing
briefly stops Agent, lets one-minute leaves and an Agent SecretID expire, and
runs normal Ansible recovery. Expect a short HTTPS outage during that test.
Reboot acceptance verifies TPM auto-unseal, preserved CA identity, and the full
appliance after restart. Completed results and test logs are recorded in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) and `artifacts/infrabox1/`.

## OpenClaw Gateway

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
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-openclaw.yml \
  -e @.secrets/infrabox1/inputs.json
```

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
credentials, database credentials, or infrastructure execution interface. Nested
sandboxing, terminal access, and execution tools are disabled for this stage.
Runner jobs cannot access the OpenClaw nginx route.

### OpenBao credentials and recovery

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

### NetBox conversational onboarding

On established appliances, `agent.yml` also provisions the NetBox integration:

```sh
.venv/bin/ansible-playbook -i inventories/development/hosts.yml agent.yml \
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
| `netbox_openclaw_username` | Dedicated service identity, default `infrabox-openclaw`. |
| `netbox_openclaw_token_description` | Credential ownership label, default `InfraBox OpenClaw MCP`. Keep it stable after provisioning. |

The service identity has no password login, staff/superuser status, deletion
permission, or administrative object permissions. Its exact permissions are
view/add/change on the onboarding plan's inventory models and tags, including
existing untagged records. The NetBox role reconciles this dedicated identity,
permissions, generic hardware types, starter roles, and tags without overwriting
existing inventory. The OpenClaw role invokes those NetBox tasks, then owns
credential storage, materialization, MCP configuration, and the managed skill.

NetBox 4.7's [default permissions](https://github.com/netbox-community/netbox/blob/v4.7.0/netbox/netbox/settings.py)
grant every user permission to manage their own API tokens,
bookmarks, subscriptions, and notifications. A small NetBox authorization backend
excludes those defaults for the dedicated integration username and denies fallback
grants. Human accounts retain their normal self-service permissions. This backend
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
independently enforce the deletion and administrative restrictions.

To use the workflow:

1. Configure a model provider using an OpenBao SecretRef as described below.
2. Open `https://claw.<infrabox_domain>`, start a new chat, and select the model.
3. Describe your infrastructure and answer the necessary follow-up questions.
4. Review the proposed inventory, placeholder hardware/interfaces, and tags.
5. Confirm the proposal, then inspect the resulting records in NetBox.

`infrabox-user-provided` records conversational provenance. `infrabox-managed`
selects objects for later automation; it is not an OpenClaw permission boundary.
You can ask OpenClaw to add or remove that tag association after confirmation.
Unrelated tags are preserved. A generic hardware type or `infrabox-unknown`
interface is an explicit placeholder, not a detected fact.

InfraBox currently records what you provide; it has not verified the managed
servers. Discovery and enrichment remain future work. Conversational acceptance
is performed manually by the operator. Automated verification opens an MCP
session, checks the five tools, reads NetBox with verified TLS, and checks
credentials, effective object permissions, and isolation. It makes no model calls,
creates no temporary inventory fixtures, and performs no live write/delete probes.

### Optional subnet scanning

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
[subnet-scanning contract](InfraBox%20%E2%80%94%20OpenClaw%20Subnet%20Scanning%20Implementation%20Plan.md).

Apply changes with `agent.yml` and your explicit inventory and protected inputs
as above. Component verification checks isolation, Nmap version, socket access,
and rejected invalid targets without sending scan probes or invoking a model.
Local scanner tests also include `node --test tests/test_subnet_plugin.mjs`.
Conversational approval and a real network scan remain operator checks.

### Web search through OpenAI

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
selected inventory using SecretRefs, as described below. Changes made only to
the appliance's generated JSON can be replaced by Ansible. Apply `agent.yml`
with the selected inventory and protected inputs. Verification exercises the
pinned OpenClaw native search wrapper and effective tool policy without sending
a model/search request; a real conversational search remains an operator check.

### Optional model providers

The Gateway starts without provider credentials. InfraBox does not provision
model keys or enable production integrations. An operator can store an API key in
KV v2 at `kv/openclaw/providers/<provider>` with a string field named `apiKey`,
then configure an appropriate provider using a reference such as:

```yaml
openclaw_model_providers:
  example:
    baseUrl: https://api.example.com/v1
    api: openai-completions
    models: [] # Supply the model definitions required by your provider.
    apiKey:
      source: exec
      provider: vault
      id: openclaw/providers/example/apiKey
```

The SecretRef ID omits the mount name and KV v2 `/data/` API segment. Resolved keys
are runtime values; configuration retains references. See the official
[Vault plugin guide](https://docs.openclaw.ai/plugins/vault) and
[container documentation](https://docs.openclaw.ai/install/docker).

#### Example: OpenAI API key in OpenBao

This example uses the default `kv` mount and an OpenAI Platform API key. The
OpenAI key is separate from both the Gateway login token and OpenClaw's OpenBao
service token.

First, open `https://vault.infrabox.example.com` (substitute your service domain)
and sign in with an operator credential that can write the secret. For the MVP,
the retained controller root token is in
`.secrets/infrabox1/openbao-init.json`, under `root_token`; use it only for
administration, never as the provider key or OpenClaw's runtime credential.
In **Secrets**, open the **kv** engine, create a secret at
`openclaw/providers/openai`, and add a string field named **apiKey** whose value
is your OpenAI API key. Save it before deploying the provider configuration.

| Item | Value with the default mount |
| --- | --- |
| KV engine | `kv` (version 2) |
| Secret path inside the engine | `openclaw/providers/openai` |
| Field containing the OpenAI API key | `apiKey` |
| OpenBao API path | `kv/data/openclaw/providers/openai` |
| OpenClaw SecretRef ID | `openclaw/providers/openai/apiKey` |

Add this to `inventories/local/group_vars/all.yml`, merging it with any existing
`openclaw_model_providers` entries:

```yaml
openclaw_model_providers:
  openai:
    baseUrl: https://api.openai.com/v1
    api: openai-responses
    models:
      - id: gpt-6-astra
        name: GPT-6 Astra
        reasoning: true
        input: [text, image]
        contextWindow: 1050000
        maxTokens: 128000
    apiKey:
      source: exec
      provider: vault
      id: openclaw/providers/openai/apiKey
```

`api: openai-responses` selects OpenAI's Responses API protocol. The `baseUrl`
points directly to OpenAI, and `models[].id` selects the actual hosted model.
`openai-completions` is the Chat Completions adapter, not a model name or a mock
provider. This example uses Responses for direct OpenAI access.

`gpt-6-astra` is the current flagship example, checked on 2026-09-12. Your
OpenAI API project must have access to it. When selecting another model, update
its capabilities and limits as well as its ID. The inventory contains only a
reference, never the key. If you changed `openclaw_openbao_kv_mount`, use that
engine in OpenBao; the SecretRef ID still omits the mount and `/data/` segment.

Model entries were checked against the
[OpenClaw 2026.9.4 configuration schema](https://github.com/openclaw/openclaw/blob/v2026.9.4/src/config/zod-schema.core.ts).
Only `id` and `name` are required within each explicitly configured model entry;
the other fields below are optional. The example makes GPT-6 Astra's capabilities
and limits explicit using its [official model specifications](https://developers.openai.com/api/docs/models/gpt-6-astra).

| Model entry field | Meaning |
| --- | --- |
| `id` | Provider model ID, such as `gpt-6-astra`; omit the `openai/` prefix here. |
| `name` | Display label in OpenClaw. |
| `reasoning` | Whether the model supports reasoning/thinking controls; `true` for GPT-6 Astra. |
| `input` | Supported input types. GPT-6 Astra accepts `text` and `image`; declare only capabilities the selected model supports. |
| `contextWindow` | Native context limit in tokens. |
| `contextTokens` | Optional smaller runtime context budget for session budgeting and compaction. |
| `maxTokens` | Maximum output token budget, separate from the context window. |
| `cost` | Optional USD-per-million-token accounting fields: `input`, `output`, `cacheRead`, `cacheWrite`, and optional `tieredPricing`. These describe costs; they do not enforce a spending limit. |
| `api`, `baseUrl` | Optional per-model overrides of the provider's adapter and endpoint. |
| `params`, `compat`, `thinkingLevelMap` | Advanced request parameters, adapter compatibility, and reasoning-level mapping; use only settings supported by the selected provider/model. |

The schema also accepts `agentRuntime`, `headers`, `mediaInput`, and
`metadataSource`; these are not needed for this example. Keep credentials in the
Vault SecretRef, including when considering custom headers. Do not copy model
limits or reasoning flags to a different model without checking its specifications.

In InfraBox, `openclaw_model_providers` becomes `models.providers` in OpenClaw's
JSON configuration. Each provider's `models` value is a list of model objects,
not a list of model-name strings. Top-level `models.mode` (`merge` or `replace`)
and `agents.defaults.model.primary` are separate OpenClaw settings; the current
Ansible role does not expose variables for them. Use session model selection
below; listing models here does not configure a default or an access allowlist.

Apply the configuration from the controller:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml agent.yml -e @.secrets/infrabox1/inputs.json
```

Open `https://claw.infrabox.example.com`, authenticate with the Gateway token,
and select `openai/gpt-6-astra` for the chat session using the model picker or
`/model openai/gpt-6-astra`. Send a short message to verify an actual provider call.
Adding a provider alone does not set the agent's default model. Keep configuration
changes in Ansible because the deployed `openclaw.json` is read-only.

To rotate the OpenAI key, update the same OpenBao secret's `apiKey` field and
run `sudo systemctl restart openclaw` on the appliance to resolve the new value.
A healthy Ansible rerun may make no changes and does not itself guarantee a
secret reload. The OpenBao service token does not need replacement for this
rotation. See OpenClaw's [OpenAI provider guide](https://docs.openclaw.ai/providers/openai)
and [model selection guide](https://docs.openclaw.ai/concepts/models).

### Operations and validation

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
acceptance. Read `IMPLEMENTATION_STATUS.md` for what has actually passed on the
test host.

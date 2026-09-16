# Platform discovery deployment

[Documentation index](README.md)

[OpenClaw discovery integration](openclaw-discovery.md) can launch this fixed
workflow and use confirmed proposals to enrich NetBox through its existing MCP.

Platform provides an optional trusted runner and managed Gitea automation
repository. Target-specific acceptance and remaining checks are recorded in
[implementation status](../IMPLEMENTATION_STATUS.md). Discovery does not add a
recurring monitor. The generic CI runner keeps its independent identity and restrictions.

## Configure and deploy

Use the authorized inventory and its existing protected controller inputs.
For example, add the following non-secret settings to the selected inventory:

```yaml
platform_enabled: true
platform_source: https://github.com/subuk/infrabox-platform.git
platform_ref: master
```

LLDAP group `infrabox:gitea:<organization>:operator` controls Operators membership.
Native LDAP/OIDC maps add and remove membership on login; Ansible never restores
an old per-user list. Core configures Operators with Code Read / Actions Write,
Developers with Code Write / Actions Read and Readers with Code Read / Actions
Read. Project admins map to Owners; only the global admin group grants instance
administration. Trusted execution-branch pushes remain restricted to the single
central technical administrator `svc-identity-admin`; its provisioning PAT stays
on the controller/host management path and never reaches a runtime runner.

For development, set `platform_source` to the controller's local
`infrabox-platform` directory and `platform_ref` to a committed branch/tag/SHA.
Core makes a private Git bundle, transfers it and preserves the exact commit IDs.
There is no required upstream push and no generated deployment commit. The local
source mode remains selected on reruns until the inventory is changed.

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml automation.yml -e @.secrets/infrabox1/inputs.json
```

The feature is disabled by role default. `site.yml` includes it when
`platform_enabled` is true. Do not enable it against an empty/uncommitted source; prepare a source commit first. This is an
established-appliance integration, not a replacement for the documented appliance
bootstrap stages.

The role builds the selected runtime, provisions separate NetBox/OpenBao/Gitea
identities, synchronizes the execution branch, installs a repository-scoped
runner and verifies its actual mounted credential against local services.
Root/admin credentials reach management only through protected Ansible stdin.
They never enter the runner or Git history.

## Target credentials and trust

Before live discovery, ask the operator for the designated test host. The
operator installs the public SSH key on that host and writes its private part
to `kv/platform/ssh/default`, field `private_key` (KV v2 API path
`kv/data/platform/ssh/default`). Do not generate a replacement over an existing
trusted key. Core creates `kv/platform/netbox`, field `token`, for read-only
inventory access. Namespace paths are independent of OpenClaw's namespace.

SSH uses trust on first use (`StrictHostKeyChecking=accept-new`). The first
connection automatically trusts and records the presented key; it does not
independently verify that first key. A changed known key blocks the connection.
Keys persist on the appliance in `{{ platform_directory }}/ssh-trust/known_hosts`,
mounted writable at `/run/platform/ssh-trust/known_hosts` in the runner. Ansible
only initializes a missing file and does not overwrite learned keys. Adding a
host needs no Ansible run. Runner recreation and reboot preserve the file;
CA trust remains mounted read-only separately. There is no migration of the old
trust file or controller-supplied host-key setting.

For a legitimate key replacement, verify the new fingerprint independently,
then remove only the affected host entry from the appliance's persistent file
using `ssh-keygen -R HOST -f PATH_TO_KNOWN_HOSTS` (use `[HOST]:PORT` for a
nonstandard SSH port). Run this as the file owner, or preserve its mapped UID/GID
when administering it as root. Use the actual SSH address (`ansible_host`). The
next workflow run records the new key. Do not clear the entire trust file.

Configure the target's native Ansible variables in NetBox Config Context and tag
it `infrabox-managed`. Do not create customer inventory as part of provisioning.
For multi-host/subset/partial-failure acceptance, arrange enough explicitly
authorized fixtures rather than inventing a second target.

Core uses an independent seven-day periodic orphan OpenBao token which may read
the Platform namespace and look up/renew itself. A native timer renews it at boot
and twice daily. Healthy reruns preserve credentials. The old accessor is retired
only after the replacement works from the runner over verified HTTPS. Operators
rotate the target SSH key in OpenBao; each new job materializes the current value.

Config Context is trusted execution configuration, including connection and
interpreter settings. The repository ACL alone does not make arbitrary context
changes safe. Platform uses native variables and does not apply a hostvar whitelist.

## Isolation and synchronization

The Platform runner has its own bridge and UID mapping. Confirm the default
`10.91.0.0/24` and `fd90:91::/64` do not overlap the deployment network. Its network
allows target connection traffic and local HTTPS services while denying backend
networks and host management ports. nginx denies Platform access to Grafana and
OpenClaw; the generic runner remains denied access to OpenBao as well.

Forced updates to the fixed execution branch are deliberate. Branch/tag/SHA and
fork changes resolve to a candidate commit before touching the deployed branch.
Repository settings, job history, artifacts and registration are retained. Only
the execution branch is synchronized. No blanket mirror push is used.

Updates pause the repository-scoped runner and drain active jobs before cutover.
Runtime/configuration/revision mismatches fail clearly; queued old-revision jobs
must not silently run against an incompatible runtime. If a cutover fails, repair
the owning role/configuration and rerun. To roll back, select the previous
compatible source revision and rerun the same procedure. Never clear job history,
remove credentials or reinitialize OpenBao as a repair strategy.

External pinned Gitea Actions are allowed. Normal runs may require internet access
to fetch checkout/upload action code even when Platform source came from a local
bundle. No global DEFAULT_ACTIONS_URL change is required.
Upload uses the Gitea-compatible v4 fork recommended in the
[Gitea v4 artifact announcement](https://blog.gitea.com/release-of-1.22.0/).
The pinned Gitea REST artifact handlers filter for v4 artifacts; a successful v3
upload alone does not satisfy the REST download acceptance check.

## Verification

Run Core syntax/unit checks and Platform fixture tests before deployment. The
initial compatibility gate checked manual dispatch, actual local SHA checkout,
and a tiny downloaded artifact on the pinned Gitea/runner versions. It passed on
the development appliance and its temporary workflow was removed. The following
command is only for a revision that still contains that temporary workflow;
normal acceptance uses the discovery command below.

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-platform-compatibility.yml -e @.secrets/infrabox1/inputs.json
```

The gate requires the temporary `compatibility.yml` workflow in the selected
Platform revision. It checks for that file before dispatch; a missing fixture
is not a successful test. Dispatch errors retain an uncertain status and never
trigger an automatic second launch. It saves a sanitized result, run URL and checked SHA to
`artifacts/<inventory_hostname>/platform-compatibility.json`. It does not access
a managed target or require its SSH key. Component verification also checks
actual scoped OpenBao/NetBox access and network/UID/SELinux/socket isolation.

For a prepared normal discovery revision, run a selected managed-host check
(substitute the explicitly authorized target's native inventory name):

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-platform.yml -e @.secrets/infrabox1/inputs.json -e platform_acceptance_targets=testbox
```

The helper allows the discovery workflow its full execution/upload deadline and
checks downloaded JSON, source/run identity, native facts, counts and excluded
secret-bearing fact families. Results retain the Gitea run URL in the controller artifact directory.
For a no-target test, use `platform_acceptance_targets=testbox:!testbox` and
`platform_acceptance_outcome=no_targets`. Never run an all-managed-host test
against inventory containing targets which have not been authorized for testing.

Live acceptance then covers native Config Context/patterns, all/subset runs,
partial failure with preserved facts, no-target behavior, permissions, runtime
isolation, credential/trust failures, upload failure and idempotent updates.
Inspect downloaded JSON and record actual run URLs/revisions and passed/failed/
not-run results. No host expiry/reboot tests are implied by this feature request.

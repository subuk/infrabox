# Implementation status

This is a dated development and acceptance record, not an operator runbook.
Entries describe the named target and revision; failures, superseded decisions
and historical evidence are retained intentionally. Use [current documentation](docs/README.md)
for installation and operation. Earlier local-admin-only, mandatory MFA,
no-dashboard and no-OpenClaw statements do not describe the current product.

## LAN Ollama provider — 2026-09-17

Added `ollama/qwen3.5:9b` alongside OpenAI on the existing development appliance
`infrabox1` (`192.168.32.206`) using `inventories/development/hosts.yml` and the
preserved protected controller inputs. Ollama at `http://192.168.32.38:11434`
reported version 0.34.1; `/api/version` and `/api/tags` returned HTTP 200 from
both appliance and Gateway container without credentials. `/api/show` reported
text generation, vision, tools and thinking; model metadata lists a 262144-token
context. The configured output budget is 8192; effective serving context and
inference performance have not been measured.

The role enables the bundled Ollama plugin and allows only its non-secret
`ollama-local` marker as an alternative to scoped Vault SecretRefs. Real provider
keys retain the existing Vault requirement. The development endpoint is included
in NO_PROXY. Default model and fallback policy remain unchanged. Configuration
follows OpenClaw documentation; separate version-compatibility probes were
explicitly omitted at the operator's request.

Local validation: all 92 Python unit tests and development `site.yml`
syntax-check passed. `agent.yml` deployment passed with `ok=131 changed=2
unreachable=0 failed=0`; Gateway restart, liveness/readiness, isolation,
SecretRef audit and existing integration verification succeeded.
Sanitized evidence: `artifacts/infrabox1/openclaw-ollama-deploy-20260917.log`.
Idempotency repeat passed: `ok=130 changed=0 unreachable=0 failed=0`.
Evidence: `artifacts/infrabox1/openclaw-ollama-repeat-20260917.log`.
No inference, conversational tool acceptance,
NetBox writes, discovery dispatch or reboot acceptance was performed for Ollama.

## Platform discovery error reporting deployed — 2026-09-17

Platform commit `4bf6a462f7504001f1c5d5a384b439605f472847` publishes bounded,
redacted per-host error messages (including failed gather-facts modules) and
Ansible process diagnostics in `run.json`, `summary.md` and the discovery step
log. Known runtime credentials and common secret fields are redacted; callback
`no_log` errors remain suppressed. Raw result dictionaries and hostvars are not
published. Inventory authentication diagnostics are retained even when Ansible
returns zero. This replaces the previous reason-code-only error reporting.

All seven focused discovery tests passed locally, including actual error text
in manifests/summaries and credential redaction. The first local invocation
lacked ansible-playbook on PATH; correcting the controller venv PATH resolved
that environment issue. A new assertion caught missing diagnostics for a
zero-exit denied inventory; corrected before commit and deployment.

Applied `automation.yml` with explicit development inventory, limit `infrabox1`
(`192.168.32.206`) and existing protected inputs: `ok=109 changed=13
unreachable=0 failed=0`. Runtime finalization, runner readiness and scoped
HTTPS/isolation verification passed. Existing SSH trust was not overwritten.
Evidence: `artifacts/infrabox1/platform-discovery-errors-deploy-20260917.log`.
No discovery workflow was dispatched; the operator must start a new workflow
on updated `master` to collect the current failure details. No live discovery
acceptance or resolution of the original discovery failure is claimed.

## Platform SSH trust deployed to development — 2026-09-17

At the operator's request, applied `automation.yml` to the existing development
inventory target `infrabox1` (`192.168.32.206`, `infrabox1.krglv.com`) with the
existing protected controller inputs and SSH host-key checking. Platform's
local `master` source was committed as
`db8140a259eeb218ace258fd4fc9c1dcb9915144`; that revision was built, synchronized
to the execution repository and started in the runner. Core changes remain
local working-tree changes. Development inventory syntax-check passed.

Deployment succeeded: `ok=111 changed=17 unreachable=0 failed=0`. Included
NetBox reconciliation updated its shared model catalog and restarted web and
worker; both recovered and passed service/TLS checks. Platform readiness,
scoped service access, HTTPS and runtime isolation checks passed. A read-only
post-deployment check confirmed the exact runtime revision, configured
`accept-new`, a writable SSH trust mount and empty `known_hosts` with mode 0600,
while CA trust remains read-only. No old host keys were migrated.

Evidence: `artifacts/infrabox1/platform-ssh-tofu-deploy-live-20260917.log` and
`artifacts/infrabox1/platform-ssh-tofu-runtime-20260917.json`. The initial
`platform-ssh-tofu-deploy-20260917.log` and `platform-ssh-tofu-deploy-retry-20260917.log`
record controller sandbox failures before any remote changes; deployment then
ran with approved SSH access and a workspace-local ControlPath directory.
No discovery workflow, reboot, concurrent-run test or idempotence rerun was
performed. Learning and rejecting host keys remain for the operator's workflow
check; no discovery acceptance is claimed.

## Platform persistent SSH trust — 2026-09-17

Local changes in Core and the adjacent `infrabox-platform` repository switch
discovery to SSH trust on first use (`StrictHostKeyChecking=accept-new`). Core
initializes a persistent `platform_directory/ssh-trust/known_hosts` only when
missing and mounts its directory writable with SELinux labeling and mapped
ownership. CA trust stays read-only. Controller-supplied host-key configuration
and its generation/restart dependency are removed; old trust is not migrated.
Unknown keys are accepted on first connection; changed known keys are rejected.

Local validation passed: `site.yml --syntax-check` with
`inventories/local/hosts.yml`, Python AST parsing of `scripts/discover.py`, and
`git diff --check` in both repositories. Per the requested scope, tests were not
edited or run, including concurrent workflow checks. No appliance was contacted
or deployed to and no workflow was dispatched. Runtime behavior remains for the
operator to check by rerunning the workflow after deploying the updated role
and committed Platform source. No new live acceptance is claimed.

## Personal login MFA repair — 2026-09-16

Read-only diagnostics on `192.168.32.206` (`infrabox1.krglv.com`, selected local
inventory alias `infrabox-krg17`) confirmed that Gitea, Grafana, LLDAP and OpenBao
were active. The personal account `matvey` had the human identity type and the
required Gitea/Grafana administrator roles. nginx recorded successful HTTP 200
LDAP login responses, followed by no token lookup from the login page.

OpenBao still had the legacy `infrabox-humans` MFA enforcement attached to the
current `ldap-human` mount, contrary to the deployed password-only login flow.
With explicit operator approval, deleted only that enforcement through the local
management socket and verified its absence by a second read. The installed
`identity_openbao` helper already removes this same rule; no code change was
needed. The origin of the remaining/reintroduced rule was not established.
Passwords, role memberships and TOTP enrollment were not changed.

Sanitized evidence: `artifacts/infrabox-krg17/login-mfa-repair-20260916.json`.
Personal browser login awaits the operator's retry; no personal password was
used and no end-to-end login, deployment, reboot or acceptance suite is claimed.

## KRG-19 documentation reorganization — 2026-09-16

Reworked the root README as a product/installation entry point and added a
purpose-based documentation index. Installation, identity, PKI/security,
architecture, operations, development and OpenClaw/provider details now live
under `docs/`; existing Platform, discovery, monitoring and runbooks remain
linked. Root plans retain historical contracts with explicit current-guide
pointers. Updated stale MFA, local-account, future-integration and README links.

Changes are Markdown documentation only. Reviewed wording, headings, repository
paths and internal links by manual/static inspection. Executable validation was
intentionally not run: no tests, syntax checks, linters, validation scripts,
playbooks, workflows, deployments or appliance/remote-host access. This entry
makes no new runtime or acceptance claim.

## Latest runtime checkpoint before documentation work — 2026-09-16

Pre-commit validation on 2026-09-16 passed all 91 Python tests, all 12 Node
tests and `site.yml --syntax-check` with the selected development inventory.
The Node socket tests required running outside the controller sandbox, which
otherwise denied temporary Unix sockets (`EPERM`). After the operator applied
the OpenAI provider settings and rebooted, read-only diagnostics confirmed the
Vault SecretRef was accessible and both default and configured Gateway model
catalogs returned the four configured OpenAI models as available. The operator
confirmed the interface was working. No model inference was performed by these
diagnostics.

## KRG-17 native first login and self-service profile — 2026-09-16

The operator changed the human-login contract: mandatory MFA is disabled, and
users supply their own email in OpenBao. This supersedes the TOTP enrollment and
per-user preparation behavior described in the historical checkpoints below.
On the same `infrabox-krg17` appliance, LDAP now creates each human entity on first
login using its immutable `entryUUID`; adding a person no longer requires running
`identity.yml`. The LDAP identity type and application role groups remain required.
Existing entities, aliases, TOTP secrets and application identifiers are retained.
The retired enrollment mount rejects new logins.

The existing login page collects email and display name using the user's own
finite OpenBao token. A templated ACL permits reading/updating only that entity's
metadata. It does not permit policy, alias, name or disabled-state changes, or
access to other entities. OIDC username uses native LDAP alias metadata; roles
use external groups. User-controlled metadata cannot grant either identity or
roles. Email is explicitly unverified and Gitea automatic account linking remains
disabled. Configuration reruns no longer import or overwrite human profiles.
No synchronization job or privileged identity service was introduced.

Local validation passed 91 Python tests, three login-page mocked-DOM Node tests,
and the site and identity acceptance syntax checks. An isolated OpenBao 2.6.2
instance passed 13 real ACL checks, including attempted root policy injection,
foreign entity access, alias changes and mixed metadata/policy writes. Evidence:
`profile-self-service-python.log`, `profile-self-service-node.log` and
`profile-self-service-syntax.log` in `artifacts/infrabox-krg17/`.

Owning-role deployment passed: `identity.yml` (`ok=8 changed=2 failed=0`) and
`edge.yml` (`ok=21 changed=2 failed=0`), including verified HTTPS health routes.
Evidence: `profile-self-service-identity.log` and `profile-self-service-edge.log`.
Native application/project acceptance passed all 82 checks (`ok=13 changed=3
failed=0`): native first login, own-profile writes and privilege boundaries,
actual OIDC sessions in Gitea/NetBox/Grafana, native service credentials, role
demotion, Gitea PAT/SSH project scope, profile preservation across configuration
and LDAP email changes, and a new entity after username deletion/recreation.
Disposable users were removed and their tokens revoked. Evidence:
`profile-self-service-acceptance.log` / `.json`.

The sequential `identity.yml`, `edge.yml` repeat and full `verify.yml` passed
(`ok=127 changed=0 failed=0`, cumulative recap). This includes TPM communication,
OpenBao and certificate Agent checks, actual application database/Redis TLS,
verified public HTTPS, runner isolation, OpenClaw's native MCP read, service
credential verification and Platform/runtime boundaries. Evidence:
`profile-self-service-repeat-verify.log`. Browser acceptance remains excluded by
the operator; no reboot or disruptive expiry/outage test was repeated.

## KRG-17 second attempt — deployed and stabilized; discovery pending, 2026-09-16

The operator recreated the appliance and confirmed `almalinux@192.168.32.206`,
`infrabox1.krglv.com`, persistent vTPM and RSA-3072. The selected inventory is
`inventories/local/hosts.yml`, alias `infrabox-krg17`. Fresh protected inputs and
artifacts use that alias; the previous `infrabox1` initialization record remains
untouched. Strict host-key checking, repeated SSH, passwordless sudo, AlmaLinux
10.2, SELinux Enforcing, TPM 2.0 and DNS were verified. Previous appliance data
and TPM store were absent. Historical acceptance below is not new-target evidence.

The operator explicitly excluded browser acceptance on 2026-09-14. Continue
Ansible and native HTTP/API integration checks; browser JavaScript/UX is not
accepted and is not a blocker for the authorized implementation work.

Outage, token lifecycle and controlled reboot tests passed. Following the MCP
transport repair below, final stabilization passed with fresh observations for
all 53 controls. Earlier failed windows remain preserved as historical evidence.
The only pending live acceptance is discovery, which awaits explicit confirmation
of the proposed permanent NetBox Site/Device after automatic approval review
rejected the ambiguous authorization. No deployment or disruptive test is running.

After the operator reported the hypervisor repaired, another bounded gate still
returned inconclusive (`hypervisor-fixed-stabilization.log` / `.json`), now with
LDAP telemetry, MCP and Vault SecretRef observations affected. A fresh sample
still measured 11.65% CPU steal. Three native MCP diagnostic reads succeeded but
took 95.6 seconds cold and 21.7/17.8 seconds thereafter
(`hypervisor-fixed-mcp-diagnostic.jsonl`). The monitor now retains its native
transport, while rereading policy/configuration and performing a real API read
on every observation. A full-config/token-file digest change or any failure
closes the transport before reuse; shutdown disposes its native child. Local
validation passed 91 Python tests, nine Node tests and both syntax checks.
Owning-role deployment passed (`ok=131 changed=3 failed=0`,
`mcp-connection-deploy.log`). Focused live acceptance passed (`ok=13 changed=1
failed=0`, `mcp-connection-acceptance.log`): retained-transport fresh reads,
same-process policy deny/restore, helper replacement with terminated old native
children, unchanged Gateway invocation and private socket permissions.
Final stabilization passed (`ok=4 changed=1 failed=0`,
`mcp-connection-stabilization.log` / `.json`), generation `54196aabf0b0928f`,
from `2026-09-16T13:22:16Z` through `13:26:55Z`: all 53 controls had at least four
distinct fresh successful observations, with no final new issues or unstable
checks. An initial LDAP telemetry failure remains in `observed_failures`; the
verifier established a successful observation window after recovery. The final
runtime snapshot also passed (`mcp-connection-runtime-evidence.json` / `.log`):
healthy complete coverage, six verified HTTPS endpoints, five normal certificate
lifetimes, native renewal success and all five unrelated tokens preserved.

The user authorized discovery, but automatic approval review rejected creating
the proposed permanent Site/Device because that reply did not explicitly confirm
the records. No records were created. An explicit exact-record confirmation was
requested; do not retry that write until it arrives.

The full deployment now passes on this target. The single central technical
administrator, human TOTP/OIDC flow, service authentication without MFA and
application role boundaries are deployed. The full-site checkpoint before the
supervised MCP repair is preserved under
`artifacts/infrabox-krg17/`:

| Check | Full-site checkpoint result | Evidence |
| --- | --- | --- |
| Local validation | 91 Python tests, 3 Node tests, Ansible syntax passed | `krg17-local-tests.log`, `monitoring-node-tests.log`, `krg17-syntax.log` |
| Human/service identity and project permissions | 67 native HTTP/API checks passed; disposable fixtures removed | `identity-projects-final.log` / `.json` |
| Complete site deployment and verification | `ok=726 changed=12 failed=0` | `site-mcp-lane-repeat.log` |
| Stabilization at this checkpoint | 53 checks, at least 3 fresh observations each, no observed failures or unstable checks | `site-mcp-lane-stabilization.json` |
| Monitoring role repeat at this checkpoint | `ok=47 changed=0 failed=0` | `monitor-mcp-lane-repeat.log` |
| Runtime snapshot at this checkpoint | 53/53 healthy; 6 verified HTTPS endpoints; 6 tokens unchanged; native renewal passed; all 5 leaf lifetimes normal | `final-runtime-evidence.json` |

The full run's 12 changes are confined to the monitoring repair, its validated
configuration generation/reload and baseline/verifier evidence. Application,
identity, PKI and runtime integration configuration remained unchanged; see
`site-mcp-lane-changes.json`. Stabilization generation `f02772eef2447209` passed
from `2026-09-14T23:36:28Z` through `23:39:56Z` (September 15 local time).

The operator authorized dependency outages, certificate expiry, OpenClaw token
replacement/revocation and one combined appliance/OpenClaw reboot on September 15.
The previously selected testbox was reconfirmed: `almalinux@192.168.32.207`,
`testbox.net.krglv.com`. Direct SSH with the existing key and preserved host trust
passed; no Device/VM record exists in the new NetBox. A concrete proposal for an
Acceptance site and the minimal former Device/context is awaiting confirmation.

The identity outage helper passed all 13 observations: expected critical LDAP/OIDC
alerts, restored service login and verified OIDC HTTPS, and unchanged OpenBao
cluster/root CA. The subsequent identity rerun and full runtime verification
passed, but the final stabilization gate failed (`ok=114 changed=3 failed=1`):
intermittent MCP startup delays and transient probe coverage loss. Evidence:
`acceptance-identity-recovery.log`, `identity-recovery-stabilization-failed.json`.
The entire acceptance stage is not yet passed. Direct and isolated systemd MCP
reads then passed in 4–6 seconds; no timeout or alert threshold was relaxed.
The stabilization-only repeat also failed (`ok=2 changed=0 failed=1`), preserved
in `identity-recovery-stabilization-repeat.log` / `.json`. CPU sampling/profile
confirmed intermittent repeated native module-startup cost despite the compile
cache. No OpenClaw memory pressure or OOM occurred (peak below 1 GB, limit 2 GB).
A dedicated supervised MCP process now retains loaded code while rereading policy,
recreating/disposing the native connection and making a fresh read each time.
Its fixed private Unix socket, per-operation watchdog and exact-process stop are
covered by seven passing Node tests; all 91 Python tests and syntax checks pass.
The new image passed full OpenClaw deployment/verification (`ok=131 changed=4
failed=0`, `mcp-runtime-gateway-deploy.log`); monitoring deployment passed
(`ok=48 changed=9 failed=0`, `mcp-runtime-monitoring-deploy.log`). Live helper
acceptance passed (`ok=11 changed=1 failed=0`, `acceptance-monitoring-mcp.log`):
a real read, private socket permissions, helper replacement with no orphan and
unchanged Gateway invocation, plus current-policy deny/restore in the same native
process using a disposable configuration. Stabilization then passed (`ok=4 changed=1 failed=0`, generation
`54196aabf0b0928f`, `mcp-runtime-stabilization.log` / `.json`): all 53 checks had
at least three fresh successful observations, with no final issues/unstable checks.
Transition coverage/MCP failures are retained in the report; a new successful
window was established after recovery. The original failed outage playbook log
remains unchanged; subsequent renewal/recovery results follow below.

Automated leaf renewal passed on this target (`ok=40 changed=4 failed=0`,
`acceptance-renewal.log`): all five server certificates were observed replaced
on verified TLS before their previous expiry, NetBox retained its invocation,
and the Agent restored the normal fourteen-day leaves. Controlled certificate
and Agent SecretID expiry/recovery passed (`ok=132 changed=8 failed=0`,
`acceptance-recovery.log`), including the full appliance verifier. A fresh
September 16 preflight confirmed healthy complete monitoring, all five leaves
at fourteen days, and removal of the disposable expired SecretID.

The remaining authorized stages now run sequentially with stop-on-failure and
a persistent progress record: `final-acceptance-sequence-20260916.json`. The
existing testbox SSH key was restored to its scoped KV path with create-only CAS
and exact read-back; different existing credentials would not be overwritten.
Platform SSH trust preparation passed (`ok=106 changed=5 failed=0`,
`final-20260916-prepare-testbox-platform.log`). No Device/VM record was created.

A six-hour September 16 history review found intermittent failures; it does not
establish uninterrupted stability. The largest MCP/coverage failure window
(approximately 07:29–07:40 UTC) followed a VM boot at 07:27:56 UTC, outside this
acceptance sequence. Gateway and the supervised MCP helper started automatically
and had no restarts; runner retries occurred during startup. Peak sampled CPU
usage was approximately 97%, including up to 28% CPU steal. These observations
correlate with startup/resource delays but do not prove the cause of every failed
probe. A separate short MCP failure around 05:50 UTC is retained in history.
Evidence: `monitoring-history-20260916.json`,
`monitoring-history-detail-20260916.json`, and
`resource-incident-events-20260916.json`. This incidental boot does not count as
the still-pending controlled reboot acceptance.

Monitoring outage acceptance passed (`ok=5 changed=3 failed=0`,
`final-20260916-monitoring-outages.log` / `.json`): ten observations establish
NetBox failure/critical escalation and recovery, frozen-success handling,
Prometheus outage/recovery, and actual Gateway health socket/tool invocation.
A transient service LDAP login timeout was observed during recovery; complete
healthy monitoring subsequently returned without changing deadlines or policy.
The separate diagnostic is retained in
`openbao-monitoring-login-observation-20260916.json`.

OpenClaw token lifecycle acceptance passed (`ok=433 changed=23 failed=0`,
`final-20260916-openclaw-token-lifecycle.log`). A one-hour period required a
replacement, followed by verified Gateway operation and retirement of the old
token. The seven-day period was restored. Explicit revocation produced a visible
native renewal failure without changing the credential file or restarting the
Gateway; the normal role then replaced the token, verified Gateway integrations
and successful native renewal. The combined appliance/OpenClaw reboot sequence
passed after this successful stage (`ok=179 changed=3 failed=0`,
`final-20260916-combined-reboot.log`). Its single authorized reboot established
TPM auto-unseal, preserved CA identity and full `verify.yml` appliance
verification. The OpenClaw token remained unchanged across boot and its scheduled
boot renewal succeeded. Disposable SecretRef, authenticated WebSocket through
nginx, verified HTTPS, unauthorized-request rejection and fixture cleanup passed.
The reboot is complete; do not repeat it to resume later checks.

The monitoring rerun passed unchanged (`ok=47 changed=0 failed=0`,
`final-20260916-monitoring-repeat.log`), and both native restricted token renewals
passed. The final stabilization gate did not pass (`ok=2 changed=0 failed=1`,
`final-20260916-final-stabilization.log` / `.json`): `openbao_metrics` remained
unstable, with one MCP failure also observed. Its failed record is preserved and
the guarded sequence stopped before runtime evidence collection. Four subsequent
fixed probe rounds passed: LDAP login took 7.4–8.3 seconds, telemetry reads
approximately 0.2 seconds; revocation succeeded. Nginx recorded a client-aborted
login during the failed window. A single stabilization-only quiet repeat also
failed (`ok=2 changed=0 failed=1`, `final-stabilization-quiet-repeat.log` / `.json`),
with the same two unstable checks. Sixty five-second resource samples recorded
peak CPU steal of 28.75% (mean 9.42%) and peak total busy time of 83.96%. The VM
exposes eight logical CPUs and approximately 16 GiB RAM; a later idle sample had
approximately 13 GiB available. Resource contention is a hypothesis, not a proven
explanation of every failure; the operator was asked to check hypervisor CPU
limits/load. No timeouts or alert limits changed.
See `final-stabilization-auth-diagnostic.json` and
`final-stabilization-resource-samples.jsonl`. The matching Prometheus series in
`final-stabilization-probe-history.json` show probe durations of 1.8–11.8 seconds
for `openbao_metrics` and 2.9–32.7 seconds for `openclaw_netbox`, with failed
observations in both series.

The post-acceptance runtime snapshot passed independently at
`2026-09-16T12:20:49Z` (`post-acceptance-runtime-evidence.json` / `.log`): all 53
checks healthy with complete coverage, six verified controller-side HTTPS
interfaces, five normal fourteen-day certificate lifetimes, and successful
native Platform/OpenClaw renewal. The five unrelated runtime tokens were
preserved; only the intentionally replaced OpenClaw OpenBao token changed.
This healthy snapshot does not replace either failed stabilization gate.

The later successful stabilization and final runtime evidence are summarized at
the top of this section. Remaining live acceptance: discovery.
Discovery uses the previously selected testbox and awaits confirmation of its
concrete new-NetBox record proposal. These remaining scenarios have not yet passed
on this recreated VM. Browser execution remains excluded. The detailed checkpoints
below retain earlier failures and do not supersede the latest results above.

### Implementation and verification checkpoints

Gitea native LDAP/OIDC source deployment now passed (`ok=16 changed=2`), and
its repeat passed without changes (`ok=16 changed=0`). HTTP health and SSH 2222
checks passed. Fixed the native source handler's `two_factor_policy` field and
host-loopback DNS inheritance (`--hosts-file=none`) in owning Quadlet templates.
OpenBao's equivalent container DNS change was applied with successful TPM
unseal/health verification (`ok=33 changed=2`). Evidence: `gitea-native-final.log`,
`gitea-native-repeat.log`, and `openbao-container-dns.log` under the selected
artifact alias. NetBox deployment passed (`ok=35 changed=9`) after correcting required
ObjectPermission actions at creation; web, worker and both PostgreSQL/Redis TLS
checks passed (`netbox-role-fix.log`). Subsequent LDAP integration corrected
the image's `/etc/netbox/config/ldap/ldap_config.py` mount and supplied the CA
explicitly before creating each LDAP TLS context. The repaired role passed
(`ok=33 changed=4`, `netbox-ldap-trust.log`); native `svc-platform` authentication
returned only the central reader group.

Initial application identity API acceptance passed 52 checks (`ok=12 changed=2`), recorded
in `identity-applications-api.json`/`.log`: actual PKCE/OIDC exchange, first TOTP
setup and recovery, human/service isolation, native Gitea PAT, NetBox v2 token
positive/negative permissions, role removal and administrator demotion in all
three applications. Tests use native HTTP flows without running a browser.
The latest successful run removed its disposable identities and tokens.

Grafana's last-server-admin guard required keeping the same central technical
`svc-identity-admin` as its native LDAP administrator. Its initial central
Grafana role was assigned once on this in-progress fresh appliance and is in the
fresh-bootstrap defaults; normal reruns still preserve removed memberships.
LDAP admits only that service identity with the central Grafana admin group.
The built-in local-password client and login form are disabled; Basic reaches
only LDAP. Live acceptance rejected a human LDAP password, another service and
an actual disposable local password. Technical Grafana deployment passed
(`ok=28 changed=6`, `grafana-central-technical.log`). Generic OAuth warning logs
could contain opaque access tokens, so that logger now emits only errors.
Monitoring provisioning now uses native Grafana service-account/token APIs,
not database writes; the successful deployment is recorded below.

Local checks currently pass 91 Python tests, three Node monitoring tests, Python source
parsing and site/application-identity syntax checks. Component/API checks below
are current-target evidence. Full-site verification now passes as summarized
above; outage and reboot acceptance remain incomplete. The first full `site.yml` run
stopped in Platform installation at the missing `git-core` dependency. The
owning role now installs it. Subsequent Platform runs built the pinned image
and corrected NetBox's LDAP loader stdout handling; an early nginx check of
the not-yet-installed OpenClaw was moved to the final verification stage.
Platform subsequently passed deployment and real runtime isolation checks
(`ok=109 changed=12`, `platform-edge-order.log`). Its mapped runner UID,
SELinux confinement, scoped NetBox/OpenBao reads, HTTPS routes and restricted
backend ports were verified. OpenClaw then passed deployment (`ok=138 changed=44`,
`openclaw-central-first.log`): native periodic renewal, isolation/private and
public TLS trust, NetBox reads through stdio and the Gateway's native MCP client,
service-role/credential validation, Gitea workflow access and runtime tool
registrations. No model calls, external scans or discovery dispatch ran.
Monitoring deployment passed (`ok=76 changed=28`, `monitoring-central-first.log`),
including native Grafana Viewer service-account/token creation, `svc-monitor`
provisioning and active schedulers. The post-deployment stabilization gate was
still pending at that checkpoint. The
general runner and stricter Gitea monitoring PAT scope checks were subsequently
applied (`ci-central-first.log`: `ok=32 changed=13`; `monitoring-scoped-final.log`:
`ok=21 changed=1`). A component-only monitoring rerun needed independent discovery
of its existing backend address; the role now handles that without requiring
the node-exporter role to run first. A live snapshot reports all 53 checks
healthy with complete coverage (`health-before-sites.json`). Application transport
acceptance passed (`ok=6 changed=3`, `applications-central-acceptance.log`): private
Git HTTPS/SSH clone and push, and an actual general-runner Actions job. The old
Platform compatibility gate returned HTTP 404: revision `e0af645` intentionally
removed its temporary `compatibility.yml` fixture. This is not a passed Platform
workflow test. The helper now checks the selected revision before dispatch and
records whether dispatch was attempted/confirmed. Current discovery acceptance
requires an explicitly selected prepared managed host; the operator was asked
for that target. Full-site repetition was still pending at that checkpoint.
Gitea's external-credential and regular-organization-creation guards were
applied (`ok=17 changed=2`, `gitea-password-guards.log`); password reset routes
are blocked at nginx. Expanded native project/credential acceptance passed
67 checks (`ok=13 changed=2`, `identity-projects-final.log`/`.json`), including
local-password/reset rejection, three-project separation, human PAT/SSH,
organization-creation denial and project access removal across a configuration
rerun. Disposable identities, repositories, organizations, LDAP/OpenBao groups
and tokens were cleaned up. The initial expanded run hit Gitea's requirement
to delete repositories before their organization; the helper was corrected and
the exact three old fixtures were removed (`project-cleanup.json`) before the
successful full repeat. Browser execution remains excluded.
The first complete `site.yml` traversal reached and passed all component/runtime
verification (`site-central-first.log`: `ok=723 changed=2 failed=1`), but its final
stabilization gate was **inconclusive**, not passed. All 53 checks were currently
healthy; intermittent `openclaw_netbox` timeouts reset its fresh observation window.
Safe parallel-worker diagnostics reproduced a 20-second native MCP deadline
before the NetBox read: policy loading reached the read at 20.1 seconds. Other
rounds finished in 5.7 and 7.2 seconds; no memory-limit/OOM event occurred.
Evidence: `mcp-worker-timing.log`. The runtime budget is now 60 seconds with a
75-second host-command bound; the actual NetBox read remains bounded to ten
seconds. Fixed phase/timing diagnostics omit credentials and native log text.
The corrected image/monitoring deployment and stabilization subsequently passed
(`mcp-runtime-repair.log`: cumulative `ok=208 changed=13 failed=0`). Generation
`3530cf098c1e146f` established at least three fresh observations for all 53 checks,
with no final issues or unstable checks. Transition/coverage failures during
generation replacement remain in the report; the verifier required a new
successful window after recovery. The final full-site result is above. Neither
the earlier failed gate nor standalone timing rounds count as successful
stabilization acceptance.
The subsequent full repeat preserved all application/runtime configuration
(`site-central-repeat.log`: `ok=723 changed=1 failed=1`; the sole successful
mutation was baseline evidence), and every component verification passed.
Its final gate again returned **inconclusive**, with recovered Podman-command
timeouts affecting PostgreSQL/runner/MCP probes and a coverage reset. The
current host had no OOM and no lasting application failure; this does not
establish a successful full-site acceptance. Fixed probes now use the pinned
Podman's native attached `exec --no-session` to avoid repeated session database
locking. Source documentation and installed CLI support were checked. This
monitoring-only repair applied (`monitor-sessionless-repair.log`: `ok=73
changed=9`); its immediate repeat added 72 tasks and zero changes. Stabilization
still returned inconclusive for MCP alone (`ok=147 changed=9 failed=1`), with
one internal timeout lasting 69.7 seconds. Four exact installed-probe diagnostic
runs using pipes completed in 5.9–7.9 seconds (`native-mcp-timing.log`); these
do not establish final acceptance. The worker now drains stdout/stderr through
bounded pipes instead of temporary regular files, retaining both output and
process-exit deadlines. Regression checks cover both streams above pipe
capacity, output limits, and a child that reports success but never exits.
The capture change applied and its immediate repeat added 72 tasks with zero
changes. Its stabilization passed with all 53 checks, at least three fresh
observations, no observed failures and no unstable checks (generation
`3c4ff6b99fccfa62`, `monitor-pipe-repair.log`: cumulative `ok=149 changed=10
failed=0`). The subsequent complete site run again passed component checks
but failed stabilization (`site-central-final.log`: `ok=723 changed=1 failed=1`).
Historical Prometheus metrics distinguish the actual MCP timeout (62.3 seconds)
from stale HTTPS/unit observations: those probes had succeeded, but the common
worker lock delayed their next cycle beyond the 110-second freshness limit.
The final runtime snapshot was healthy (53/53); controller TLS for all six
interfaces, normal 14-day leaf lifetimes, native token renewal and preservation
of all six runtime credentials passed (`final-runtime-evidence.json`). This is
snapshot evidence, not a successful stabilization gate.
MCP now has an independent bounded systemd timer/worker lock; the deployment
verifier dispatches that lane separately. Core probes retain their existing
cadence and freshness requirements; MCP failures remain visible. Six exact-capture native MCP rounds passed in 6.4–12.6 seconds
(`exact-capture-timing.log`); they do not establish long-term stability. The repair
applied successfully (`monitor-mcp-lane-repair.log`: `ok=48 changed=5 failed=0`),
and all three schedulers are active. The first repeat captured an incomplete
new-generation baseline and was deliberately stopped during certificate-Agent
fact gathering (`site-mcp-lane-final.log`, controller exit 143); it is not a passed
run. A fresh 53/53 healthy preflight was recorded (`mcp-lane-preflight.json`)
before starting `site-mcp-lane-repeat.log`, which subsequently passed deployment
and stabilization with the additional compile-cache setting described below. The first component command omitted
the `node_exporter` prerequisite tag and stopped before Prometheus configuration
activation (`monitor-mcp-lane-apply.log`: `ok=24 changed=5 failed=1`); the corrected
command includes that dependency. No application authorization or isolation
has been relaxed.

The independent lane kept 52 other checks fresh during another MCP timeout;
coverage stayed complete. Fixed phase evidence and CPU sampling showed expensive
native runtime/module startup, rather than a slow policy decision or network
read (`mcp-policy-phases.jsonl`: one successful 55.1-second run;
`mcp-cgroup-timing.jsonl`). The pinned container uses Node.js 24.19.0. Three
actual probes with Node's native compile cache passed in 9.8 seconds cold and
about 5–6 seconds warm (`mcp-compile-cache-timing.jsonl`), using approximately
13 MiB of temporary container storage. The worker now enables this cache only
for MCP, preserving current policy evaluation, real reads and all deadlines.
Local checks passed before the ongoing full run reached the monitoring role;
that run deployed this final worker configuration and passed stabilization
with no observed failures. The monitoring repeat also passed with zero changes (`ok=47 changed=0 failed=0`).

The bounded `acceptance-identity-recovery.yml` LLDAP/OpenBao outage and critical
alert scenarios are prepared and syntax-checked, but have not run; explicit
outage authorization is still required.

Local disposable fixtures using synthetic credentials verified LLDAP 0.6.3,
OpenBao 2.6.2, Gitea 1.26.4 and NetBox 4.7.0-5.1.1. Sanitized passing results are
under `artifacts/infrabox-krg17/phase1/`; these are compatibility checks, not live
appliance or browser acceptance:

- LLDAP's non-editable `infraboxIdentityType` attribute supports mutually
  exclusive human/service filters with a restricted bind reader. Humans can
  edit their own profile/email, but cannot edit the managed type or another user.
- OpenBao's normal human mount requires TOTP and issues no application token
  for a password alone. Service LDAP login has no MFA. A separate, short-lived
  enrollment mount can issue an entity-bound token restricted to native TOTP
  self-generation. That token cannot read KV, authorize OIDC, create tokens or
  use administrative MFA operations. The static enrollment implementation was
  subsequently deployed; its browser/UX execution is excluded from acceptance.
- Stable LDAP `entryUUID` aliases and controller projection of email preserve
  the canonical entity and TOTP across email changes. Actual OIDC code exchange,
  RS256 signature validation and claims verified unchanged `sub`/username with
  the updated email. Application policies must stay off the shared entity and
  its identity groups so they cannot leak into enrollment tokens.
- Gitea service LDAP login provisions its own PAT through the native API;
  human passwords are rejected. A central service administrator can configure
  the final LDAP source through native administration without argv secrets or
  a local administrator. Native LDAP group/team mapping grants and removes team
  membership on login.
- NetBox's native LDAP token endpoint provisions a v2 token for the authenticated
  service without a usable local password; human passwords are rejected.
  The early fixture's negative API requests used an incomplete v2 credential;
  their HTTP 403 results do not prove authenticated authorization boundaries.
  Live acceptance now builds the complete `nbt_<key>.<secret>` credential and
  requires a positive inventory read before negative permission checks.
  A small OIDC pipeline
  adapter can pass allowlisted claims to native `configure_groups`; promotion,
  demotion, membership replacement and rejection of foreign role names passed.
  Full live role permissions remain unaccepted at this fixture checkpoint.

The first foundation run stopped at a firewalld startup readiness race. The
owning role now waits for `firewall-cmd --state` before immediate rule changes.
The retry passed (`ok=45 changed=10`), its stable repeat passed (`ok=44 changed=0`),
and `verify-foundation.yml` passed (`ok=19 changed=0`). The TPM completed actual
RSA OAEP checks without key replacement.

The first OpenBao runtime run exposed a pre-existing template error: the
documented `-e openbao_tls_enabled=false` string selected TLS branches in Jinja.
Both runtime templates now use explicit boolean conversion; a regression test
covers string and boolean overrides. The corrected localhost-only bootstrap
runtime passed (`ok=33 changed=4`) with the actual PKCS11 seal. The initialized
server is now on final HTTPS (`ok=34 changed=4`). PKI bootstrap passed
(`ok=24 changed=10`), followed by a repeat without initialization
(`ok=21 changed=0`). All three CA fingerprints were unchanged. Recovery material
remains on the controller; public CA exports are under the new artifact alias.

Certificate Agent bootstrap passed (`ok=20 changed=13`), host trust passed
(`ok=4 changed=2`), and final HTTPS Agent configuration passed
(`ok=19 changed=3`), including actual AppRole authentication, certificate chains
and hostnames. The five leaf consumers are OpenBao, PostgreSQL, Redis, LLDAP and
nginx. LLDAP certificate renewal uses the existing Agent's validated atomic
publication followed by a controlled LLDAP restart; renewal acceptance is pending.

PostgreSQL/Redis deployment passed (`ok=35 changed=17`): all four database roles,
including LLDAP, connected with verified TLS; authenticated Redis TLS worked and
anonymous requests were rejected. The sequential backend repeat passed
(`ok=29 changed=0`).
LLDAP runtime deployment passed (`ok=19 changed=8`) and its stable repeat passed
(`ok=16 changed=0`). Native health, actual LDAPS certificate/hostname validation
and the directory's active TLS PostgreSQL connections passed. Local syntax
validation and 74 Python tests passed; no full-stack acceptance is implied.

The operator selected one technical superadministrator (`svc-identity-admin`)
shared by Ansible and the initial LLDAP operator login. It is typed `service`,
has no MFA and is excluded from human SSO. Personal users are created manually in
LLDAP; no initial human username/email is required in inventory. Dedicated
reader/OpenClaw/Platform identities keep separate limited access. The controller's
retained OpenBao root token remains an independent infrastructure credential.

Live directory bootstrap passed after fixing duplicate membership of the native
LLDAP administrator (`ok=4 changed=2`), followed by a stable repeat
(`ok=4 changed=0`). The helper also passed fixture checks for preserved password
rotation, removed memberships and intentional deletion. Service identities are
bootstrapped once; Ansible does not restore centrally removed assignments.

`identity.yml` now prepares native OpenBao human/service/enrollment mounts,
TOTP enforcement, stable entryUUID aliases, metadata, role groups and OIDC
registrations. Canonical API values are compared (LDAP lowercases userattr;
the OIDC provider returns its effective issuer), yielding an unchanged configuration
repeat. Only prepared human UUIDs may enter the human/enrollment mounts; their
aliases are linked before publishing the login filter. Entities and identity
groups carry no permission policies, preventing enrollment privilege leakage.
Application OIDC clients use only their own allowlisted external role groups.

Actual LDAPS authentication first failed because OpenBao's restricted SELinux
domain denied outbound port 6360. Its owning role now labels that single port
and permits only the required LDAPS egress, retaining Enforcing. Runtime
configuration/verification passed (`ok=23 changed=3`). Native identity acceptance
subsequently passed 21 checks for identity type separation, service login without
MFA, restricted first TOTP enrollment, canonical identity continuity, post-MFA
KV administration without PKI administration, and real OIDC authorization.
The test helper's auth-envelope parsing was corrected before the successful run.

`identity-edge.yml` deployed Grafana without a local administrator and the native
HTTPS edge (`ok=49 changed=28`). Host-trusted HTTPS passed for OpenBao, the static
login page, LLDAP and Grafana. `acceptance-identity-grafana.yml` passed 26 checks,
including Grafana's real PKCE code exchange, a personal application session and
native Viewer role mapping and denial of NetBox OIDC authorization without a
NetBox role. Disposable directory users, received tokens and the
Grafana mirror were removed by the successful test. These are native HTTP/API
checks, not browser execution of the new static first-login page.
Final sequential repeats passed: `identity.yml` (`ok=8 changed=0`) and
`identity-edge.yml` (`ok=39 changed=0`). The preceding edge repeat applied the
last static-page error-handling change (`changed=1`); it was not treated as a
stable repeat. Final read-only health confirmed all seven deployed services
active, SELinux Enforcing and trusted OpenBao/Grafana HTTPS responses; see
`artifacts/infrabox-krg17/identity-health.json`.

At the earlier browser checkpoint the controller did not trust the recreated
appliance CA; browser acceptance was subsequently excluded. No browser TLS
validation was bypassed. The earlier automatic approval rejection of old-test
enumeration was resolved with a narrowly constrained read-only diagnostic.
Two confirmed old synthetic service entities and their login leases were
removed, with exact alias/UUID and absent-directory checks. Evidence is in
`old-bao-probe-guards.json` and `old-bao-probe-cleanup.json`. Old Gitea/NetBox test
mirrors left by a failed cleanup were also removed by exact IDs and names;
see `application-probe-cleanup.json`.

The earlier 77-test checkpoint preceded the application/service conversion
recorded above. Browser acceptance was subsequently excluded by the operator.
Application API acceptance subsequently passed as recorded above. The first
`site.yml` reached Platform (`ok=297 changed=5`) and stopped because that role
had relied on a host Git package absent on a clean VM. Git is now an explicit
role dependency. The pinned Platform image built; its first management attempt
then exposed LDAP-loader stdout mixed with helper JSON. The owning NetBox helper
now isolates native informational output; the corrected Platform run is pending.
Full-stack and disruptive acceptance remain incomplete.
Earlier base health (`artifacts/infrabox-krg17/base-health.json`) confirmed actual
verified OpenBao HTTPS, an unsealed server, authenticated certificate Agent,
verified LDAPS and all five active base services. Disposable local fixture
containers were removed after saving their sanitized results.

## KRG-9 OpenClaw discovery and NetBox enrichment — 2026-09-13

Implemented and deployed to the authorized existing appliance `infrabox1`,
`almalinux@192.168.32.206`, using `inventories/development/hosts.yml` and existing
domain, TPM and protected controller inputs. Only the explicitly authorized
`testbox.net.krglv.com` (Device ID 12, `192.168.32.207`) was discovered.

The native OpenClaw plugin exposes start/status/result for the fixed Platform
`discover.yml` workflow. It checks explicit managed NetBox identities, passes
comma-separated names through the existing Ansible pattern input, persists
request/run metadata across Gateway restarts, and does not redispatch an
uncertain request. Results validate bounded native ZIP artifacts against the
run, attempt, deployed SHA and selected identities, and page successful hosts'
Ansible facts. The Platform repository/pipeline was not changed for KRG-9;
execution revision remains `e0af645f3decb0c2a1381145a25808f4896f4c10`.

A separate Gitea account/team has Code Read and Actions Write only on the
execution repository. Its scoped token is owned by OpenBao and delivered through
a private runtime file; healthy reruns preserve it. Replacement validation
precedes publication, and superseded tokens are retired after Gateway-side
verification. Neither runner/provisioner credentials nor arbitrary workflow
operations are exposed to the model.

The managed onboarding skill now joins discovery facts to concrete NetBox
proposals, preserves provenance, supports standard fields and Device-to-VM
correction, and leaves additional facts visible without new custom fields.
Operator-approved inventory permissions now include deletion, platforms, MAC
addresses, Config Context and local Device/VM context. Every NetBox write still
requires confirmation of the concrete proposal, including affected relationships
for deletion/migration. Earlier no-delete statements below describe historical
acceptance and are superseded by this deployment.

Completed checks:

- Local validation: 68 Python tests and 16 Node tests passed. Coverage includes
  expanded NetBox grants, credential preservation/replacement failures,
  persistent request deduplication, lost dispatch responses, name ambiguity,
  revision/attempt/identity checks, unsafe/oversized ZIP rejection, partial
  results and bounded native fact paging. `site.yml` and
  `acceptance-openclaw-discovery.yml` syntax checks used the explicit development
  inventory; `git diff --check` passed.
- Final component deployment via `agent.yml --skip-tags subnet_scan` passed:
  `ok=104 changed=5 failed=0`. Actual Gateway registration of all three optional
  tools, Gitea identity/permissions, HTTPS workflow access, NetBox MCP reads,
  effective expanded NetBox permissions and existing OpenClaw checks passed.
- Healthy repeat of the same component deployment passed:
  `ok=102 changed=0 failed=0`. The image, configuration and all integration
  credentials were preserved; no Gateway restart or token retirement occurred.
- Live tool acceptance made no model calls or NetBox writes. Request
  `krg9-testbox-20260913-01` dispatched
  [run 200](https://git.infrabox1.krglv.com/infrabox-platform/automation/actions/runs/200).
  Attempt 1, artifact 8: selected 1, succeeded 1, failed/unreachable/unfinished 0;
  107 native fact fields were available through Gateway. Artifact observation
  time was `2026-09-13T16:11:43.430053+00:00`.
- Gateway restart acceptance passed (`ok=11 changed=3 failed=0`): the same
  request recovered run 200, artifact 8 and the same SHA without a new workflow.
  The acceptance helper additionally supports status/result-only replay; its
  post-restart path cannot create a replacement run if persistence is missing.
- The final status/result-only replay passed (`ok=6 changed=1 failed=0`, with
  only the local report created), retaining run 200/artifact 8 and recording
  `persisted_request_read_without_dispatch`. The original dispatch and restart
  reports are preserved separately.

The initial deployment stopped at the existing MCP stdio verifier with a generic
session failure (`ok=105 changed=11 failed=1`). An independent read-only probe
then passed; the precise initial cause was not established. The verifier now
reports sanitized phase/code flags and the role retries this read-only check
within a bounded limit. Final deployment and discovery acceptance passed.

Conversational proposals, confirmed NetBox writes/deletes and Device-to-VM
migration were not exercised live. Multi-host/partial/error cases and credential
replacement failure scenarios have local fixture coverage, not live acceptance.
No managed-host changes, appliance reboot, expiry/recovery tests or full-stack
acceptance were performed for KRG-9. Sanitized logs and bounded reports are under
`artifacts/infrabox1/krg9/`; operator instructions are in
[docs/openclaw-discovery.md](docs/openclaw-discovery.md).

## KRG-16 InfraBox home page — 2026-09-13

Implemented and deployed to the authorized existing appliance `infrabox1`,
`almalinux@192.168.32.206`, using `inventories/development/hosts.yml`.
The home page is `https://infrabox1.krglv.com/`.

The nginx role adds a static vhost and manages a self-contained HTML file under
`/usr/share/nginx/html/infrabox/`. Five permanent cards link to Gitea, NetBox,
Grafana, OpenBao, and OpenClaw using the effective nginx upstream hostnames.
Embedded CSS/SVG and system fonts require no JavaScript or external assets.
The `nginx_landing` tag updates static content and verifies the page without
notifying nginx reload/restart handlers. Browser responses use revalidation
through `Cache-Control: no-cache`.

Completed checks:

- User approved the actual desktop/mobile design before deployment.
- Local browser checks with JavaScript disabled at 1440, 1024, 768, 390, and
  320 px: five cards, no horizontal overflow, visible keyboard focus, and no
  external asset requests. Desktop/mobile screenshots were preserved.
- Python unittest: 56 passed, including four home-page rendering checks for
  the configured domain, upstream overrides, the existing OpenClaw hostname,
  and self-contained assets. `site.yml` syntax-check passed with the explicitly
  selected development inventory.
- Initial nginx/page deployment (`edge.yml --tags configure,service`):
  `ok=12 changed=4 failed=0`. The static directory, HTML, and vhost were added;
  the existing nginx handler applied the changed configuration.
- Repeat of the same deployment: `ok=10 changed=0 failed=0`, with no nginx
  reload handler invocation.
- Static-only apply and ordinary-URL verification after DNS propagation
  (`edge.yml --tags nginx_landing`): `ok=4 changed=0 failed=0`, with no service
  reload or restart tasks.
- Deployed page smoke check: HTTP 200, all five expected links, 16,503-byte
  HTML, `Cache-Control: no-cache`, ETag revalidation returning 304, and an
  unknown path returning 404. The initial smoke used an explicit DNS address
  override; a later request to the ordinary URL from the controller returned
  200 after DNS propagation.

The operator added the main-domain A record during deployment. The first
`nginx_landing` verification encountered a cached DNS failure after the two
static tasks completed with no changes. It passed on retry after propagation;
the separate failed-run log is retained.
No TLS configuration, service enablement logic, or application configuration
was changed. No full appliance regression, reboot, expiry, or recovery tests
were run for this feature.

Page-specific logs, the public CA, and HTTP results are preserved under
`artifacts/infrabox1/`; visual evidence is under `artifacts/home-page/` in the
implementation worktree. A durable copy of the KRG-16 evidence is also saved in
the main checkout under `artifacts/infrabox1/krg16/`.

## KRG-6 Platform discovery — 2026-09-13, single-host acceptance passed

Implemented Platform source/runtime/workflows in the separate local
`infrabox-platform` repository and optional Core provisioning in `automation.yml`.
The existing `platform.yml` remains the foundation Podman/TPM playbook.
Development selects committed local Platform history and transfers a Git bundle;
no GitHub push has been made. Updates force-synchronize the execution branch while
preserving repository settings, run history, artifacts and runner registration.

The implementation uses native NetBox Config Context flattening, Ansible patterns
and facts, a separate repository-scoped runner/network/UID mapping, read-only
NetBox credentials and an independent renewable OpenBao token. Native connection
variables and ports remain under Ansible control, without an OS restriction.
External checkout/upload Actions are pinned by commit. No Platform scheduler or
pipeline monitoring was added.

The authorized existing appliance is `infrabox1`, `almalinux@192.168.32.206`, with
`inventories/development/hosts.yml` and preserved TPM/domain/controller inputs.
Live deployment of Platform `45f544eaa81b2561480694b659a8123fa1505bfb` completed:
`ok=92 changed=6 failed=0`. Local Gitea's branch and the runner's embedded revision
matched. Final source `e0af645f3decb0c2a1381145a25808f4896f4c10` removes the temporary
compatibility workflow and adds explicit missing-credential-field reasons;
its final deployment completed with `ok=95 changed=13 failed=0`. The final
component checks passed, and Gitea/runtime revisions match.

Completed live checks:

- Runtime readiness, actual scoped OpenBao/NetBox HTTPS reads, denied Core secrets,
  UID/capability/SELinux confinement, no socket mounts, backend/management port
  isolation and expected local HTTPS restrictions passed. NetBox web/worker
  PostgreSQL and Redis TLS and nginx application readiness also passed.
- Gitea compatibility run 166 passed dispatch, exact-SHA checkout, v4 upload and
  REST download with an exact 41-byte payload. The action requested seven-day
  retention; Gitea recorded creation `2026-09-13T12:49:24Z` and expiration
  `2026-09-19T12:49:24Z` (six elapsed days). Actual expiry cleanup was not waited for.
  The workflow context reports attempt `1`; the REST run field reports `0`.
- Real discovery run 168 with `testbox:!testbox` passed negative acceptance:
  workflow failure with `no_targets`, zero selected hosts, retained downloaded
  JSON/summary and successful workspace cleanup. No target connection was made.
- Native `platform-token-renew.service` renewed the seven-day scoped token and
  preserved token/registration files, NetBox credential/version and Platform/
  NetBox container identities. Token replacement/revocation recovery is not yet
  live-accepted.

Earlier failed checks were diagnosed and repaired in their owning code/config:
Gitea REST exposes v4 artifacts, so the initial successful v3 upload in run 111
could not be downloaded by the acceptance API; the pinned Gitea-compatible v4
fork now passes. Healthy reruns read Actions variable values from response field
`data` while writes use `value`. Granular teams return top-level `permission=none`
and effective Code Read / Actions Write in `units_map`; comparison now uses that
representation. Regression tests cover stable reads and repair of code-write
permission drift. Run 167 found the
operator key under `sshkey`; the identical value was added as agreed `private_key`
in the same OpenBao secret, preserving the existing field. No key was generated
or replaced. Discovery now reports missing expected fields explicitly.

Current local checks: 52 Core Python tests, seven Platform tests on the controller
and in the final Linux runtime with no network/capabilities, and relevant Ansible
syntax checks passed. Earlier five Node tests passed; no Node code changed here.
Fixtures exercise the actual pinned NetBox inventory plugin and native Ansible
selection/facts, arbitrary flattened variables, partial success, denied inventory
and exclusion of credential-bearing output. They do not establish live multi-host
acceptance.

Evidence under `artifacts/infrabox1/`: `platform-deploy-v4-repair.log`,
`platform-compatibility-166.json`, `platform-discovery-168.json`. Earlier failed
`platform-deploy-v4.log` and `platform-discovery-167.json` remain failed evidence.
Final deployment evidence: `platform-deploy-final.log`. The first healthy-rerun check (`platform-idempotence.log`) reported three changes
and restarted the runner because of the granular-team comparison above. Its
preservation check (`platform-preservation-first.json`) confirmed unchanged
credentials/registration and NetBox token/version, but failed container identity
preservation. The correction deployed successfully (`platform-idempotence-repair.log`,
`ok=91 changed=5 failed=0`). The final healthy rerun then passed with
`ok=90 changed=0 failed=0`; token/registration file hashes, inodes and mtimes,
NetBox credential/version, and Platform/NetBox container identities all remained
unchanged. Evidence: `platform-idempotence-final.log`,
`platform-preservation-final.json` and `platform-renewal.json`. Temporary baseline
state was removed after comparison.

The operator designated `almalinux@192.168.32.207` as the only managed test target.
Its verified controller known_hosts entries are installed in Platform trust.
The private key is available in OpenBao at `kv/platform/ssh/default`, field
`private_key`, and on the controller at `/tmp/id_ed25519`; it is only for testbox,
not the appliance. Direct SSH with that local key and host-key checking passed.

The operator updated Device ID 12 to `testbox.net.krglv.com`, tagged it
`infrabox-managed`, and supplied native Config Context variables
`ansible_host=192.168.32.207` and `ansible_user=almalinux`. Platform and primary IP
remain empty; native SSH gathering works with these context variables and no
additional Platform OS restriction. No NetBox inventory write was made by this
implementation or acceptance.

Live discovery run 178 on final Platform revision
`e0af645f3decb0c2a1381145a25808f4896f4c10` passed with exactly one selected and
successful host, Device ID 12. The native facts report AlmaLinux 10.2, kernel
`6.12.0-211.47.1.el10_2.x86_64`, one logical CPU and 1961 MiB memory. All workflow
steps passed, including exact-SHA checkout, facts gathering, v4 upload and cleanup.
The downloaded archive contains only `run.json`, `summary.md` and
`facts/device-12.json`; run/revision/counts/native facts and excluded sensitive
fact families were checked. Evidence: `platform-discovery-178.json` and private
local extracted results in `platform-discovery-178/` under the controller
artifact directory. The managed-host prerequisite blocker is resolved.

A native rerun of the same Gitea run also passed on the same single target.
Attempt `2` produced separate artifact ID 6 (`discovery-178-2`) while preserving
artifact ID 5 (`discovery-178-1`). Downloaded manifest attempt/run/revision and
facts were checked again. Evidence: `platform-discovery-rerun-178.json` and
`platform-discovery-178-attempt-2/`. This confirms that the native workflow
attempt context distinguishes reruns despite the REST run field reporting zero.

Live all-host/partial-failure scenarios, credential/trust failure injection,
operator permission probes and token replacement/revocation recovery remain
unverified. Actual inventory-plugin/native-Ansible fixture tests cover selection
and partial result preservation, but do not establish those live scenarios.
No reboot, certificate expiry or connection to another managed host was performed.

## KRG-15 continuous monitoring — 2026-09-12/13

Implemented and deployed to the authorized existing development appliance:
`infrabox1`, `almalinux@192.168.32.206`, AlmaLinux 10.2, using
`inventories/development/hosts.yml` and its preserved controller inputs.

The generated contract contains 47 checks and 159 Prometheus rules. Native
node_exporter metrics and bounded fixed probes cover units, verified HTTPS,
served certificates, host resources/security/storage, authenticated application
dependencies, RQ workers/queues, OpenBao and certificate Agent authentication,
OpenClaw readiness/Vault/MCP/diagnostics, Grafana datasource access, and actual
Gitea runner execution. Basic checks and scrape/evaluation run every 30 seconds;
integration checks run every 60 seconds; the isolated runner canary runs every
five minutes. Its private repository retains at most 12 completed runs for one
hour and produces no artifacts. Prometheus retains 15 days with a 2 GB size cap.

Grafana provisions `InfraBox / InfraBox Health` with pending/firing alerts,
explicit unknown/incomplete coverage, service/integration state, metrics and
history. Alertmanager is absent. The read-only `infrabox_health` OpenClaw tool
and host CLI use the same bounded contract. Trusted post-change verification
requires three distinct new observations spanning at least 120 seconds.

Completed checks:

- Python unittest: 41 passed; Node tests: 5 passed; Ansible syntax checks passed
  for `site.yml`, `monitoring-deploy.yml` and `acceptance-monitoring.yml`.
- Generated rules passed pinned promtool validation and semantic fixtures for
  healthy/pending/firing/recovery, missing/frozen/future observations and an old
  configuration generation.
- Live `acceptance-monitoring.yml`: `ok=5 changed=3 failed=0`. NetBox loss became
  visible and critical, then recovered; stopping observation scheduling expired
  cached success to unknown; Prometheus loss returned unknown; both recovered.
  Direct Gateway socket access and registered `/tools/invoke` health calls passed.
- Disposable canary retention acceptance reduced eight completed runs to one
  using a temporary test limit; the configured 12-run/one-hour policy stayed
  unchanged. Unit fixtures also prove that active runs are excluded from cleanup.
- Monitoring rerun: `ok=63 changed=0 failed=0`; OpenClaw installation rerun:
  `ok=22 changed=0 failed=0`. Monitoring/OpenClaw token file identities and
  modification times, and six application container start times, were unchanged.
- Runtime checks passed actual database/Redis TLS and runner network isolation,
  including denial of the new metrics port. The health process is unprivileged
  (`nobody`), has no effective capabilities, enables no-new-privileges after its
  scoped SELinux transition, and runs with SELinux enforcing.
- Browser verification displayed the provisioned dashboard and explicit
  unknown/incomplete coverage during the frozen-observation fault.
- Authorized baseline/reboot/full-verification sequence, using
  `acceptance-reboot.yml` and its included `verify.yml`: cumulative recap
  `ok=87 changed=2 failed=0`, no skips. TPM auto-unseal, preserved CA fingerprint,
  actual TLS connections, certificate Agent authentication, OpenClaw token/MCP/
  scanner contracts and runner isolation passed. NetBox needed several minutes
  after cold boot; its health check retried and recovered normally.
- After reboot, the actual Gateway `/tools/invoke` call returned HTTP 200,
  `healthy`, complete coverage and all 47 checks healthy. Grafana showed
  `Healthy / Complete` with no active alerts; metric panels rendered correctly.

The first two post-reboot stabilization windows returned `inconclusive`, with no
current issues and only two accumulated observations for `openclaw_netbox`.
Historical Prometheus samples and the second verifier report identified transient
MCP timeouts during those windows: the verifier correctly discarded earlier
successful samples. Freshness and required sample counts were not relaxed.
The verifier now also reports observed failures and unstable check IDs.
Separate read-only diagnostics, including four measured concurrent probe rounds
under the normal worker CPU/memory limits, completed the MCP read and client
cleanup in 6–10 seconds. The original timeout was not reproduced in that series;
its cause remains unconfirmed. These early failures are retained as evidence,
not reclassified as passes.

A third window was stopped after reproducing the timeout to install safe command
diagnostics. Subsequent combined core/canary verification completed successfully
at 22:39 UTC on September 12: all 47 affected checks, at least four distinct new
observations, no observed failures, no unstable checks. Evidence:
`monitoring-timeout-combined.json`. That run used the original timeouts.
The worker now retains bounded, credential-free timeout metadata in a private
state file so a recurrence can be diagnosed without collecting raw command output.

The final monitoring application published the matching catalog/rules generation;
its immediate repeat added 63 successful tasks and zero changes (cumulative
recap `ok=130 changed=8 failed=0`, including baseline capture and first apply).
Evidence: `monitoring-final-deploy-verified.log`.

During a later Ansible stabilization run, safe diagnostics captured an MCP
Podman-command timeout at 25 seconds with no structured result and no stderr.
The enclosing host command now allows 40 seconds for process startup/teardown;
the MCP runtime's 20-second timer and NetBox read's 10-second timer are unchanged.
The final deployment and verification of that change are recorded in
`monitoring-completion.log`.

Final result at 22:57 UTC on September 12: **passed**, generation
`f37d63d55856f8a8`, 47 affected checks, minimum four distinct new observations,
no current issues and no unstable checks. A transient `grafana_datasource` failure
was observed and recovered within the window; it established fresh successful
observations before passing. No MCP failure was observed in this final window.
The complete final apply/repeat/stabilization invocation exited successfully:
`ok=131 changed=10 failed=0`; the immediate monitoring repeat itself had zero
changes. Early timeouts and interrupted diagnostic runs remain in their original
logs and do not count as successful acceptance.

Evidence is under `artifacts/infrabox1/`: `monitoring-acceptance.log`,
`monitoring-retention.log`, `monitoring-promtool-final.log`,
`monitoring-idempotence.log`, `monitoring-openclaw-idempotence.log`,
`monitoring-idempotence-before.json`, `monitoring-idempotence-after.json`,
`monitoring-runtime-isolation.log`, `monitoring-unit-final.log`,
`monitoring-node-final.log`, `monitoring-syntax-final.log` and
`monitoring-stale.png`, `monitoring-reboot-final.log`,
`monitoring-post-reboot-tool.json`, `monitoring-post-reboot-health.json`,
`monitoring-reboot-alerts.png`, `monitoring-healthy.png` and
`monitoring-metrics.png`. Earlier unsuccessful diagnostic/deployment logs are
retained separately and are not acceptance evidence.

The pinned OpenClaw release does not expose MCP tools through its HTTP tools
endpoint. The fixed NetBox read therefore uses its real local MCP runtime and
applicable tool policy; this is not full conversational authorization parity.
No inference/provider calls or inventory writes were made by monitoring tests.
Idle providers are shown as not recently verified; future KRG-6/KRG-9 capabilities
are not configured. Whole-host loss still requires an external observer.

The live failure checks above do not claim the plan's entire exploratory matrix
(separate token revocation, every service outage, loaded-runner queueing, or
interrupted generation activation). These were not separately injected. Normal
certificate lifetimes and controller CA/TPM identities were preserved; certificate
expiry and destructive initialization tests were not part of this change.
Operator configuration, implementation decisions and runbooks are in
[docs/monitoring.md](docs/monitoring.md).

## OpenClaw NetBox onboarding — 2026-09-12

Implemented and deployed to the existing development appliance using
`inventories/development/hosts.yml`: `infrabox1`, `almalinux@192.168.32.206`,
AlmaLinux 10.2. Fresh SSH access succeeded; the older SSH blocker below no
longer applies to this deployment. Earlier reboot/expiry acceptance remains
separate and was not rerun.

OpenClaw retains its pinned 2026.9.4 base image and now includes NetBox MCP
0.2.0 with an integrity-locked dependency tree. The five tools run over stdio
inside the Gateway container. The dedicated NetBox identity has exact
view/add/change inventory permissions, no password login, and a non-expiring
v2 token stored in OpenBao and atomically materialized into its protected
runtime file. Existing generic hardware types, starter roles, and tags are
reused. The managed onboarding skill is mounted read-only, is model-visible,
and requires explicit confirmation; the management tag is an automation choice,
not an OpenClaw access restriction.

NetBox 4.7's implicit permissions include self-service API token management.
A scoped authorization backend removes those defaults for the integration
identity and rejects fallback grants, preserving normal human-account behavior.
Early deployment attempts stopped at NetBox schema/default-permission checks;
these were corrected before integration token provisioning completed.

Completed checks:

- Component deployment: `ok=82 changed=14 failed=0`; final explicit MCP CA
  configuration: `ok=76 changed=2 failed=0`.
- Stable component rerun: `ok=75 changed=0 failed=0`. Both credential contents,
  file identities, and modification times were preserved; OpenClaw, NetBox,
  and NetBox worker container start times were unchanged.
- Final full-appliance `verify.yml`: `ok=74 changed=0 failed=0`, including
  public HTTPS routes, application database/Redis TLS, certificates, running
  services, and runner isolation. No checks were skipped.
- Actual stdio MCP session and HTTPS NetBox read succeeded. OpenClaw's own
  MCP probe exposed all five expected tools without diagnostics.
- Effective inventory permissions matched exactly. Authenticated HTTPS reads
  of NetBox users, tokens, and permissions endpoints returned HTTP 403.
- OpenBao/runtime token equality, ownership/mode, Gateway health/readiness,
  managed skill discovery, provider SecretRef audit, private/public CA trust,
  and container isolation passed.
- Local syntax checks, both enabled/disabled JSON renderings, launcher syntax,
  skill validation, and all 21 unit tests passed. Unit tests cover credential
  preservation/interrupted replacement and the scoped authorization boundary.

Evidence: `artifacts/infrabox1/openclaw-netbox-deployment.log`,
`openclaw-netbox-final-config.log`, `openclaw-netbox-idempotence.log`, and
`openclaw-netbox-preservation.log`; full-appliance verification is recorded in
`openclaw-netbox-verify.log`.

Per operator direction, automated conversational acceptance, inference calls,
temporary live inventory fixtures, write/delete probes, expiry tests, and reboot
tests were not performed for this change. Onboarding conversations, confirmation,
corrections, management-tag changes, and deletion refusal remain manual operator
acceptance; structural checks do not establish those model behaviors.

## OpenClaw provider secret repair — 2026-09-12

Diagnosed the live OpenAI provider failure: the KV secret was readable and the
bundled resolver worked directly, but OpenClaw's exec security check rejected
the official image's root-owned `/usr/local/bin/node` while running as UID 1000.
Ansible now builds a local image from the pinned official digest with only Node
ownership corrected to 1000:1000 (0755), retaining the non-root runtime and
capability restrictions. Component verification now includes `secrets audit
--check --allow-exec`, which detects failures masked by Gateway readiness.

Deployed to the existing development VM: `agent.yml` completed with 37 successful
tasks, 5 changes, and zero failures. The SecretRef audit passed; the running
Gateway then reported `Secrets reloaded.` without warnings. No paid inference
request was made. Local syntax validation and all 11 unit tests passed. Deployment
log: `artifacts/infrabox1/openclaw-node-owner-fix.log`. Earlier pending reboot
acceptance remains separate from this repair.

The MVP is implemented and accepted on the development VM as of 2026-09-11.
Target: `almalinux@192.168.32.206`, AlmaLinux 10.2, persistent virtual TPM 2.0.

## Completed acceptance

| Check | Result |
| --- | --- |
| Full final deployment and verification | 312 successful tasks; only public CA export changed |
| Second full deployment and verification | 312 successful tasks; **zero changes**, zero failures |
| Expired certificates and Agent SecretID recovery | 97 successful tasks; zero failures |
| Certificate renewal and Git/CI acceptance | 46 successful tasks; zero failures |
| Host reboot and full verification | 69 successful tasks; only reboot changed; zero failures |
| Local syntax and PIN rendering regression | Passed |

- OpenBao automatically unsealed through PKCS#11 after reboot. The existing
  RootCA identity was preserved, and every appliance service started automatically.
- All four services presented renewed certificates on fresh verified TLS
  connections before the old certificates expired. NetBox was not restarted
  by Redis certificate renewal. Normal leaf lifetime is restored to 14 days.
- Ansible recovered expired leaves through the protected Unix listener without
  changing TCP back to HTTP. It replaced the expired SecretID; the old credential
  was rejected and the replacement authenticated successfully.
- Restricted-token SecretID rotation passed. Ansible also repairs the Agent's
  specific RoleID lockout when needed, retaining normal lockout protection.
- Private Git clone and push passed over HTTPS and SSH port 2222. A real Gitea
  Actions job succeeded on the isolated `infrabox-shell` runner.
- Actual PostgreSQL and task/cache Redis connections validated TLS in both NetBox
  web and worker containers. Gitea, Grafana, and backend TLS checks passed.
- Runner checks confirmed mapped host UID, no runtime sockets, Gitea/NetBox HTTPS
  access, denied Vault/Grafana access, and blocked PostgreSQL/Redis connections.
  Host SSH and OpenBao backend port denial were also tested during deployment.

## Deployed components

Host packages, chrony, enforcing SELinux, firewalld, Podman 5.8.2, TPM PKCS#11,
OpenBao 2.6.2 HSM, RootCA/ServerCA/UserCA, native OpenBao Agent and host trust,
PostgreSQL 17.11, Redis 8.8.2, Gitea 1.26.4, NetBox 4.7.0 and worker, native nginx,
Gitea Runner 3.4.2, Prometheus 3.13.3, and Grafana 13.2.1.

`site.yml` performs established-appliance deployment and repair. `verify.yml`
checks the final state. Initial bootstrap remains explicit; see README.

## Operator choices and MVP limits

- RSA-3072 is the approved development TPM override; the role default is RSA-4096.
- The initial OpenBao root token and recovery shares remain on the controller.
- Gitea, NetBox, and Grafana use local administrator accounts.
- Runner jobs share a container/work area and use shell/Git; Docker execution and
  Node actions are not included. No host runtime socket is exposed.
- Prometheus and Grafana are installed with a datasource and no dashboards.
- Production inventory is empty; production hardware and backup/restore are
  outside this development-VM acceptance.

## Evidence and client trust

The public CA is [artifacts/infrabox1/root-ca.crt](artifacts/infrabox1/root-ca.crt).
Successful test logs are preserved alongside it: `site-first.log`,
`site-second.log`, `acceptance-recovery.log`, `acceptance-renewal-and-git.log`,
and `acceptance-reboot.log`. Generated artifacts are excluded from Git.


## OpenClaw integration — deployed; final verification pending (2026-09-12)

OpenClaw 2026.9.4 is deployed on the authorized `infrabox1` development VM using
the official image pinned by digest. It uses a scoped periodic OpenBao token,
the bundled Vault plugin, native token renewal, persistent storage, container
limits, and nginx HTTPS/WebSockets with narrow proxy attribution.
`certificate-agent.yml` retains the certificate Agent workflow; `agent.yml` now
owns OpenClaw.

### Completed live checks

- Integration acceptance: `ok=9 changed=2 failed=0`. This covered Gateway health,
  private/public Node TLS trust, Vault SecretRef resolution at startup and reload,
  authenticated WebSockets through nginx with an explicitly paired temporary
  client, unauthenticated rejection, OpenBao permission denials, renewal without
  rotation, secret-free logs, and fixture/client cleanup.
- Token lifecycle acceptance: `ok=122 changed=22 failed=0`. Period changes caused
  replacement, Gateway restart, and superseded-token revocation. The seven-day
  period was restored. Revoked-token renewal failed without modifying the file
  or restarting Gateway; Ansible repaired the token and renewal succeeded again.
- Initial real-expiry acceptance: `ok=44 changed=7 failed=0`, using a five-second
  periodic fixture and restoring the configured seven-day period.
- First full-site run: `ok=352 changed=1 failed=0`; the change installed the
  updated management helper. A subsequent component run installed the final
  lookup correction (`ok=30 changed=1 failed=0`).
- Second full-site run: `ok=353 changed=0 failed=0`, including existing service,
  certificate, and runner-isolation checks. Controller-side HTTPS readiness
  also returned success using the exported RootCA.

The later final recovery test exposed an OpenBao-specific response: privileged
lookup of an expired token returns HTTP 403 even when the management credential
is valid. The helper now handles that case, with a regression test. The normal
Ansible repair subsequently passed (`ok=33 changed=6 failed=0`), including actual
Gateway readiness, token properties, TLS, immediate native renewal, and restart
marker finalization. **The appliance was restored to a healthy seven-day token.**

### Remaining checks and current blocker

Fresh SSH authentication stopped working again. The existing authenticated
Ansible connection allowed the repair to finish, then expired. Reboot acceptance
has **not** run. Restore/unlock the controller SSH key before continuing; the
host key still matches, and no VM rebuild is indicated.

After SSH is restored:

1. Finish the lifecycle helper's `verify` action for the repaired token. The
   protected `lifecycle-test.json` fixture record remains because the connection
   closed before that cleanup check could run.
2. Reconcile the idempotence baseline: the two full-site runs succeeded, but
   direct baseline comparison could not connect before the intentional expiry
   test changed the token. The old `idempotence-test.json` and state/workspace
   marker files therefore cannot be used to claim a successful comparison.
   Remove only those test artifacts, capture a fresh baseline, and verify
   preservation across a normal rerun.
3. Rerun final expiry acceptance against the corrected helper, then run
   `acceptance-openclaw-reboot.yml` with working fresh SSH authentication. This
   checks TPM auto-unseal, retained CA/token identity, scheduled boot renewal,
   and Gateway integration after reboot. The latest Control UI HTML assertion
   also remains to be exercised in that integration run.

Local checks: eleven unit tests, Python compilation, and all new playbook syntax
checks pass. These are not substitutes for the remaining live checks.

### Evidence and implementation notes

Logs under `artifacts/infrabox1/` include `openclaw-integration-and-lifecycle.log`,
`openclaw-expiry.log`, `openclaw-site-first.log`, `openclaw-site-second.log`,
`openclaw-helper-update.log`, and `openclaw-expiry-repair.log`.
`openclaw-final-recovery-and-reboot.log` records the interrupted final acceptance
attempt, not a successful reboot.

Podman excludes host-only aliases. nginx overwrites forwarded client IPs, and
OpenClaw trusts only the discovered backend bridge gateway. Direct readiness
probes run inside the container because trusted-proxy ingress rejects forwarded
loopback clients. Configuration stays read-only and Ansible-managed; the
application may log that it cannot write an adjacent last-known-good backup.
Token replacement leaves a persistent restart requirement until Gateway
verification succeeds, so an interrupted run can resume safely. Historical MVP
results above predate this integration.

## OpenClaw subnet scanning — deployed (2026-09-12)

Implemented and deployed on the existing authorized development appliance,
`infrabox1` at `192.168.32.206`, using `inventories/development/hosts.yml` and
its preserved controller inputs. SSH access worked with host-key checking.
This result does not complete the older conversational or reboot acceptance
work described above.

`infrabox_scan_subnet` accepts one IPv4 CIDR from /24 through /32, without an
address allowlist. Its native per-call approval names the subnet, explains
active probes and possible disruption/alerts, and requires confirmation that
this is the user's own local network. It reports responsive IPs, selected open
TCP ports, and explicitly heuristic Nmap OS matches. The managed onboarding
skill retains separate confirmation for NetBox writes.

The Gateway retains UID 1000, no Linux capabilities, and its execution-tool
restrictions. Nmap runs in a separate container with only CAP_NET_RAW, its own
bridge, a private Unix socket, fixed arguments, resource limits, and a hard
three-minute deadline. Source images and added Debian packages are pinned.
See the [scanner contract](InfraBox%20%E2%80%94%20OpenClaw%20Subnet%20Scanning%20Implementation%20Plan.md)
for exact behavior and limits.

Completed checks:

- Local Ansible syntax checks, 27 Python unit tests, two Node tests, and Python
  compilation passed. Tests cover target size/canonical form, injection,
  concurrency, process timeout cleanup, OS parsing, and approval-hook requests.
- The real Nmap command discovered a temporary TCP listener on `127.0.0.1/32`
  and produced heuristic OS matches inside a disposable `--network=none`
  container. Only loopback traffic was used; no LAN address was scanned.
- Native plugin runtime inspection found the optional tool and
  `before_tool_call` approval hook loaded without diagnostics. Component checks
  passed for worker isolation, socket access, rejected invalid targets, Gateway
  readiness, scoped credentials, TLS trust, and actual NetBox MCP reads.
- A worker restart retained the Gateway container identity and health, and
  reconnected through the shared socket with SELinux enforcing.
- Final configuration application: `ok=48 changed=2 failed=0`. Complete
  deployment rerun: `ok=98 changed=0 failed=0`.
- Full appliance read-only verification: `ok=75 changed=0 failed=0`, including
  application health, public HTTPS, credential/TLS contracts, scanner checks,
  and runner isolation.

The first deployment failed during worker restart because systemd could not
manage the Podman-relabeled runtime directory. The owning role now uses the
repository's tmpfiles pattern and orders worker updates before Gateway startup.
The Gateway uses a Wants dependency so worker restarts do not stop it. A stale
startup lock after an interrupted startup expired normally; subsequent readiness
and verification succeeded. Failed runs remain labeled as failed evidence.

Evidence under `artifacts/infrabox1/`: `subnet-scanner-local-tests.log`,
`subnet-scanner-loopback.log`, `subnet-scanner-plugin-isolated.json`,
`subnet-scanner-restart.log`, `subnet-scanner-final-config.log`, and
`subnet-scanner-idempotence.log`; full verification is in
`subnet-scanner-verify.log`. The initial failure and successful repair are
recorded in `subnet-scanner-first.log` and `subnet-scanner-repair.log`.

No LAN scan, model-driven conversation, inventory write/delete fixture, expiry
test, or reboot acceptance was run for this extension. End-to-end conversational
approval and scanning the operator's actual network remain operator-owned.

## OpenAI web search — deployed (2026-09-12)

Enabled OpenAI's native hosted `web_search` on the same authorized development
appliance using `inventories/development/hosts.yml`. It is available for general
questions and onboarding when using the configured direct OpenAI Responses
models. No separate search provider or credential was added. The existing four
model definitions and Vault SecretRefs were preserved from the live configuration
into protected controller inputs so future Ansible runs retain them.

`openclaw_web_search_enabled` controls search independently of NetBox and subnet
scanning. Disabling search preserves an explicitly configured OpenAI chat
provider. The managed onboarding skill now permits vendor/model research,
prefers manufacturer sources with citations, separates published specifications
from actual installed hardware, excludes private inventory details from queries,
and retains confirmation before NetBox writes.

Completed checks:

- Ansible syntax checks and all 28 Python tests passed. The new configuration
  test covers search, NetBox, scanner, and OpenAI-provider combinations. Skill
  validation and JavaScript syntax checks passed.
- The installed OpenClaw native wrapper and effective tool policy produced
  hosted-search payloads for all four configured OpenAI models. Offline checks
  verified explicit opt-in through the tool profile, disabled/denied search,
  proxy exclusion, and preservation of unrelated tools.
- Deployment: `ok=49 changed=3 failed=0`. Complete OpenClaw deployment rerun:
  `ok=99 changed=0 failed=0`, including native search checks, Gateway readiness,
  SecretRef audit, isolation, scanner verification, and real NetBox MCP reads.
- Public Gateway HTTPS health passed using the exported RootCA.

Evidence is in `artifacts/infrabox1/web-search-deploy.log`,
`web-search-idempotence.log`, and `web-search-https-health.json`. Verification
issued no paid model or hosted-search request and performed no conversational
acceptance or NetBox inventory write fixture. A real search and its answer
quality remain operator checks. See [web-search operation](docs/openclaw.md#web-search-through-openai).

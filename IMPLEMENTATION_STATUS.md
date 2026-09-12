# Implementation status

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
quality remain operator checks. See [web-search operation](README.md#web-search-through-openai).

# KRG-15 — Repository assessment and implementation plan

> Implementation design and acceptance contract, retained for development
> reference. Use [monitoring operations](docs/monitoring.md) for current runtime
> details, including later central-identity and MCP transport changes. Historical
> acceptance belongs in [implementation status](IMPLEMENTATION_STATUS.md), not
> in assumptions about a new host. See the [documentation map](docs/README.md).

Date: 2026-09-12. Status: implemented; actual deployment and acceptance evidence
is recorded in `IMPLEMENTATION_STATUS.md`. The assessment below preserves the
initial plan; the final section records changes established by runtime validation.
Inspected Core revision: `3a99437` (`Add web search tool`).

This document grounds the implementation handoff attached to
[KRG-15](https://linear.app/krglv/issue/KRG-15/add-self-monitoring-for-infrabox-with-prometheus)
in the current repository. It incorporates the operator's explicit correction:
**do not install Alertmanager; configure alerts in Prometheus and display them
in Grafana.** Receiver provisioning, notification delivery, inhibition/silence
tests, and notification setup indicators are outside this iteration.

## Assessment and scope

The handoff has the right correctness model: continuous observation independent
of conversations; separate service and integration checks; deterministic rules;
explicit missing/stale evidence; compact agent access; and fresh observations
after deployment. This is a substantial monitoring feature, not an exporter-only
change. The largest risks are integration/auth semantics, missing-data handling,
runner isolation, and deployment observation timing.

Implement the complete monitoring path for currently installed Core capabilities.
Do not implement future Platform/discovery functionality to satisfy hypothetical
checks. Preserve a visible distinction between an unconfigured capability and a
configured capability whose monitoring is missing or broken.

The dashboard and exporters extend the earlier minimal-observability scope in
`InfraBox_plan.md`; existing application versions and security boundaries remain.
The operator's Alertmanager exclusion also agrees with the original Core baseline.

## Repository compatibility matrix

| Area | Observed evidence | Implementation consequence |
| --- | --- | --- |
| Prometheus | `roles/prometheus`: `quay.io/prometheus/prometheus:v3.13.3`, 30s self-scrape only, 15d retention, loopback port 9090, persistent data | Extend this role with scrape jobs, rules, validation and retention size; retain network/data identity |
| Grafana | `roles/grafana`: `docker.io/grafana/grafana:13.2.1`; PostgreSQL with verified TLS; datasource UID `infrabox-prometheus`; no dashboard provisioning | Add dashboard provisioning and Prometheus alert views; preserve datasource UID and database |
| OpenClaw | `2026.9.4`, base digest `sha256:6bc0bf3117e1c5074db8a064084a5f9d41ece1aa2a16369a82f53207b846a5c3`; derived image; UID 1000; execution tools denied | Enable the bundled metrics plugin and one read-only health tool without enabling shell tools |
| OpenClaw native diagnostics | Read upstream `v2026.9.4` plugin entrypoint and exporter source: exact `/api/diagnostics/prometheus` route, Gateway auth, operator-read check, build-info support when runtime identity is supplied | Source compatibility established; actual digest contents, auth and emitted metrics still require runtime verification |
| OpenClaw invocation | Read `v2026.9.4` HTTP/shared invocation code: explicit agent/session selection and scoped tool resolution; token/password auth gives operator semantics | Fix context and tool arguments; test MCP resolution and effective tool exposure; do not claim conversational authorization parity |
| NetBox MCP | `@zenixsolutions/netbox-mcp` 0.2.0 with lockfile; five tools, actual stdio client and protected token-file launcher | Reuse launch/auth path; deepen existing verification into a Gateway-level fixed read |
| NetBox | `docker.io/netboxcommunity/netbox:v4.7.0-5.1.1`; separate worker; DB and two Redis logical databases; scoped integration identity | Monitor web, worker and dependency checks separately; do not grant integration account monitoring admin access |
| Gitea | `docker.gitea.com/gitea:1.26.4-rootless`; local accounts; private repositories; Actions enabled | Add native metrics and dedicated monitoring identity, not runtime admin credentials |
| Existing runner | `docker.gitea.com/runner:3.4.2`; rootful Podman management with mapped job UID; isolated `infrabox-runner` network; capacity 1; metrics/readiness bound to container loopback 9101 | Scrape requires an explicit safe access path; never attach runner to backend network |
| Future integrations | No OpenClaw Gitea tool or trusted Platform runner in inspected Core; local Platform working directory has no checked-out files | Gitea service/current-runner monitoring is in KRG-15; future integration checks attach when those capabilities exist |
| OpenBao | HSM 2.6.2, checksum-pinned archive; AlmaLinux 10.2 image digest in `images/openbao/Containerfile`; Raft/TPM; controller-only management root token | Enable scoped telemetry and a dedicated probe-secret path; keep TPM/CA/management workflow unchanged |
| PostgreSQL / Redis | `postgres:17.11-bookworm`, `redis:8.8.2-trixie`; both TLS; no published database ports | Exporters use backend network and restricted credentials; a generic SELECT/PING is not application-auth proof |
| nginx / host | Native nginx `1.26.3-6.el10_2.6`; native systemd services and rootful Quadlets; SELinux enforcing | Prefer native node_exporter; observe selected units and actual storage mount identity |
| Configuration | Domain/internal suffix and storage roots in inventory; optional OpenClaw NetBox/scanner/search booleans; no general per-service enable flag | Generate checks from actual configuration/playbook membership; do not invent disabled states for installed mandatory services |
| Verification | `verify.yml` calls component checks plus `scripts/verify-runtime.py`; OpenClaw checks include real stdio read and MCP discovery | Keep permission/TLS/isolation tests; ongoing health cannot replace them |
| Local tooling | Pinned Ansible 2.19.7, Python unittest, Node tests, `.venv`, local collections; no checked-in CI/lint workflow found | Add meaningful rule/probe/adapter tests and documented commands; do not assume existing dashboard/Prometheus test infrastructure |

Relevant existing paths: `observability.yml`, `site.yml`, `verify.yml`,
`roles/openclaw/files/verify-netbox-mcp.mjs`, `roles/openclaw/tasks/verify.yml`,
`scripts/test-gitea-workflow.py`, `roles/gitea_runner/templates/firewall.nft.j2`.

## Scope dependencies and corrections

1. **No Alertmanager.** Prometheus owns recording rules, alert rules and pending/
   firing states. Grafana displays these using the existing datasource, including
   `ALERTS` and normalized health series. Do not duplicate thresholds as
   Grafana-managed rules. Rule annotations/runbooks remain useful without delivery.
2. **No circular roadmap dependency.**
   [KRG-6](https://linear.app/krglv/issue/KRG-6/deliver-end-to-end-ansible-facts-discovery-through-local-gitea)
   adds Platform repository, trusted runner and discovery, and explicitly consumes
   KRG-15's monitoring contract. OpenClaw discovery access belongs to
   [KRG-9](https://linear.app/krglv/issue/KRG-9/connect-openclaw-to-the-discovery-pipeline).
   KRG-15 must not require their completion. Show these as not configured; once
   enabled, missing observations must become unknown. Never present direct Gitea
   API availability as an OpenClaw-to-Gitea tool test.
3. **Actual NetBox integration.** The current script starts an MCP client directly;
   `openclaw mcp probe` checks discovery. Neither alone establishes Gateway tool
   invocation/policy. Verify fixed `netbox_read` through the pinned Gateway path,
   using `dcim.site`, `list`, `limit=1`, JSON response. Resolve the actual exposed
   Gateway tool name at the compatibility gate. Test result shape and MCP error
   flags, including valid empty results. If invocation cannot reach the real MCP
   implementation, use a narrow runtime-local adapter and state its limits.
4. **Time semantics.** Reduce the handoff's slow defaults: the OpenBao secret
   read becomes 60s (from 300s), and the runner canary becomes 300s (from 600s).
   After a relevant deployment, the trusted verifier requests up to three fixed
   checks about 60s apart, without exposing dispatch to the model. Long-running
   checks require an explicit workflow timeout or return inconclusive.
5. **Certificate policy.** Actual Core leaf lifetime is 336h. Derive warning/
   critical windows from renewal behavior and lifetime, not the handoff's example
   14d warning. Observe served certificates as well as renewal/authentication.
6. **Prometheus/Grafana outages.** Stale recorded health must not stay green.
   The adapter checks live query/rule status; dashboard queries include fresh
   monitoring evidence and explicit no-data handling. A co-located stack cannot
   establish whole-host availability during host/power failure.

## Proposed implementation boundaries

Reuse `roles/prometheus`, `roles/grafana`, `roles/openclaw` and shared `quadlet`.
Use small component roles for node_exporter, blackbox_exporter and any required
database exporters, plus `roles/integration_checks` for the catalog, fixed probes
and scheduling. Keep metrics/auth configuration in the owning application role.
Do not introduce an umbrella role that also owns application lifecycle.

Suggested new files include:

- `roles/prometheus/templates/prometheus.yml.j2` and rule templates.
- `roles/grafana/templates/` dashboard/provider configuration.
- `roles/integration_checks/files/` fixed probe implementation and health adapter.
- `roles/integration_checks/templates/` catalog and systemd units/timers.
- `roles/openclaw/files/health/` small native tool plugin.
- `schemas/infrabox-health.schema.json`, `scripts/verify-monitoring.py`.
- `tests/monitoring/` or compatible unittest-discoverable modules and rule fixtures.
- `docs/monitoring.md`, `docs/runbooks/`, `acceptance-monitoring.yml`.

Final new binary/image versions must be selected and checksum/digest-pinned before
implementation of installation tasks. No existing application upgrade is needed.

### Collection and privilege boundaries

Run node_exporter as a restricted native systemd service with selected collectors
and a dedicated textfile directory. Restrict its listener to intended local/
monitoring access. Monitor unit state, RAM/CPU, bytes/inodes/read-only filesystems,
time synchronization and expected storage source/mountpoint. This repository does
not provision a separate data mount: do not assume `/srv/infrabox` must be one;
record the selected deployment's actual intended storage identity.

Use backend-connected exporters for database metrics and a restricted blackbox
endpoint for configured appliance URLs only. Neither exporter nor probe containers
receive a host runtime socket. Native fixed host collectors may use narrowly
defined `systemctl`/`podman exec` commands where runtime-local observation is
necessary; those are trusted installed code, never caller-supplied shell strings.
Separate that host privilege from the network probe service and health reader.

The runner's loopback readiness/metrics currently cannot be scraped from
Prometheus. Prefer fixed native collection without changing runner networking;
choose a restricted endpoint only after verifying its firewall/UID implications.
Do not expose backend services to jobs to obtain monitoring access.

Keep OpenClaw's broad Gateway credential local. Prefer a private, exact-path
nginx metrics relay with backend auth hidden from Prometheus; validate the pinned
trusted-proxy behavior and prohibit other paths/methods. Tool probes use a separate
fixed trusted runtime path, not a general invocation endpoint offered to the model.

Health implementation: one deterministic shared adapter with a local CLI for
Ansible and a narrow OpenClaw tool transport. Prefer Python for the host adapter
and a tiny plugin shim. If a Unix-socket service is necessary to share the adapter
without installing Python in Gateway or enabling shell tools, restrict it to
health reads and a configured component filter. It must not start probes. Keep
its lifecycle independent of OpenClaw and monitoring success.

### Concrete initial check coverage

| Capability | Continuous evidence |
| --- | --- |
| Host/runtime | Required service/timer units, mount identity, resource pressure, clock, enforcing SELinux and expected runtime availability |
| OpenBao/PKI | Initialized/unsealed single-node state, authenticated dedicated secret read, telemetry, certificate Agent/credential-renewal health, actual served leaf expiry |
| PostgreSQL | Exporter health, restricted authenticated query, connection/lock/storage pressure; retain application-specific credential tests |
| Redis | Authenticated TLS PING and memory/eviction/error evidence; distinguish absent maxmemory limit from usable headroom |
| NetBox | API/web, worker/queue evidence, application dependencies and separate actual OpenClaw MCP read |
| Gitea | Health/API/native metrics, private fixture repository access with dedicated monitoring identity |
| Existing runner | Unit/readiness/registration evidence as supported, queue age and scheduled bounded execution canary |
| nginx/UI | Verified HTTPS and expected application markers for git, netbox, vault, grafana and configured claw hostname; explicit redirect policy |
| OpenClaw | Liveness/readiness, native diagnostics presence/freshness, runtime/tool-policy check, real NetBox and Vault integration checks |
| Scanner | When enabled: unit/socket worker health only; no automatic LAN scan |
| Model/search providers | Passive native outcomes; no model/search calls from monitoring; no recent inference means not recently verified, not default appliance failure |
| Prometheus/collection | Readiness, expected targets, config/rule generation, reload/evaluation health, required rule presence, worker/catalog/data freshness |
| Grafana | Application/database health plus a bounded query through its configured Prometheus datasource with a restricted monitoring identity |

Runner canary is a fixed appliance smoke workflow with no managed-host credentials,
no production-data writes, no Node/Docker actions, strict timeout and no overlapping
dispatch. It proves execution on the existing isolated runner, not future trusted
Platform execution. Account for capacity 1: a legitimately busy runner must not
be declared dead after a short queue wait. Track scheduled, queued, started and
completed timestamps and enforce a distinct queue-age policy.

Store canary source in version control and provision a dedicated restricted local
repository. Do not reuse the admin-authenticated temporary acceptance script as a
continuous monitor. When KRG-6 adds the trusted runner, add its separately owned
canary/checks through the same catalog contract without touching managed hosts.

### Check intervals and post-change observations

These are proposed implementation defaults following the operator's question
about reducing intervals, not values already deployed:

| Check | Normal interval | Work performed |
| --- | --- | --- |
| Native metrics, units, HTTPS/TLS | 30s | Scrape/observe configured services and make bounded web requests |
| OpenClaw-to-NetBox | 60s | One fixed read through the real tool/MCP path; no inventory mutation |
| OpenBao secret path | 60s | Authenticate through the intended runtime identity and read one dedicated probe secret |
| Runner execution | 300s | Dispatch one tiny fixed workflow and verify its correlated completion |
| Prometheus rule evaluation | 30s | Evaluate collected evidence and health/alert conditions |

After changes, run only affected fixed probes promptly, then repeat at roughly
60s intervals until three distinct successful observations span at least 120s.
Use the same probe implementation, scheduler lock and metrics publication as
normal monitoring. Enforce a bounded request count and coalesce normal scheduled
work to avoid overlap. The health tool itself never requests this execution.

A typical fast success path takes approximately 2–3 minutes including scheduling,
scrape and evaluation. This is not guaranteed: a busy runner or slow check can
require an explicit longer deadline or produce inconclusive. Keep the ordinary
5m verifier deadline; do not lower freshness/stabilization requirements to fit it.
Derive each max-age from its normal cadence plus timeout and scrape/evaluation
margin. Alert hold-down and observation cadence are separate settings.

### Rules, catalog and health contract

Generate expected checks independently of probe results, with stable IDs, cadence,
max age, component/integration, mandatory/optional classification and runbook ID.
Publish the expected catalog separately from each atomic probe snapshot. Catalog,
rules and local health expectations share a configuration generation identity.
Missing enabled checks cannot disappear by removing their scrape targets.

Keep the handoff's bounded metric names and reason vocabulary. Record last attempt,
completion and success separately. Add an observation sequence/identity where
needed to distinguish new work from a repeated sample; prevent concurrent writes,
future timestamps and restored old files from creating fresh success. Use per-check
deadlines and concurrency limits; one hung probe must not freeze other checks.

Prometheus owns thresholds, raw failure conditions and normalized check states.
Use `healthy`, `warning`, `critical`, `unknown`; aggregate as critical > unknown >
warning > healthy, with independent `coverage_complete`. Test all combinations.
Show current raw failures/pending alerts even before severity hold-down expires;
such a failure always blocks the affected deployment verification.

The health schema preserves the handoff's compact contract: schema version,
status, coverage, generated time, check counts, issue count/truncation and bounded
issues. Include observation bounds and configuration generation for verifier use.
At most 20 issues / 8 KiB, deterministic ordering, no arbitrary PromQL or URLs,
no secret values or raw integration results. Component filtering must not hide a
global evaluator/coverage failure that invalidates the selected component.

Use coherent query timestamps and bounded rule/target API checks. Query warnings,
missing rules, generation mismatch, impossible observations and Prometheus failure
produce incomplete coverage. Preserve known critical issues when other data is
missing. The adapter's generated time is never evidence of a new observation.

Grafana's provisioned **InfraBox Health** dashboard shows overall state, coverage,
pending/firing problems, service versus integration rows, resources, certificates
and collection health. Use normalized rules plus `ALERTS` from Prometheus;
absence of alerts alone is not a health query. No-data/query-error views are
explicitly unavailable/unknown. No Alertmanager datasource, contacts or delivery
configuration is required.

## Delivery sequence and exit criteria

### 1. Ground runtime compatibility and freeze contracts

- Confirm actual pinned OpenClaw metrics route, runtime identity/event metrics,
  Gateway NetBox invocation and policy behavior on the designated environment.
- Confirm native metric names, database exporter privileges, Grafana datasource
  query permissions and supported Gitea runner/canary APIs.
- Finalize check catalog/schema, source-to-check mapping, pins and access paths.
- Exit: one real no-model NetBox read through the intended path; valid-empty and
  auth/error fixtures; documented privilege and unsupported-capability boundaries.

### 2. Deploy continuous collection

- Extend application metrics; install exporters and bounded fixed probe workers.
- Add independent expected catalog and atomic observations; preserve credentials
  on normal reruns and read replacement credentials on subsequent executions.
- Include current runner smoke canary; keep monitoring independent of OpenClaw.
- Exit: all currently enabled capabilities have concrete observations and
  freshness limits; worker failures cannot preserve apparent freshness.

### 3. Implement rules, alerts and Grafana

- Add normalized conditions/states, missing-data rules, thresholds and annotations.
- Provision the dashboard and runbooks; validate alert visibility with pending,
  firing, recovery and unknown fixtures.
- Stage complete configuration generations, validate before activation and retain
  the previous valid config. Mount configuration directories where atomic file
  replacement is used; avoid a stale single-file bind mount during reload.
- Exit: rule tests and dashboard produce consistent state; no-data never green;
  removing a required target/rule causes incomplete coverage.

### 4. Add health tool and deployment verifier

- Implement shared adapter/CLI and read-only OpenClaw tool; do not broaden its
  tool policy beyond the specific optional health tool.
- Wrap trusted deployment with baseline capture and post-change verification;
  retain `verify.yml` for explicit full checks. Ordinary subsequent diagnostics
  begin with compact health and drill down only where needed.
- Maintain a static affected-check/dependency map for Core components. Record
  revision, generation and actual deployment completion time in verifier output.
- Require at least three distinct post-completion successful observations spanning
  at least 120s, fresh rule evaluation, and no affected raw/pending/firing failure.
  Native observations must be actual scrapes; textfile observations must be actual
  completed executions, not new scrape timestamps over old values.
- Treat first installation's missing baseline as an explicit bootstrap case;
  subsequent unrelated baseline warnings remain visible without being blamed on
  the change. Relevant baseline failure gives inconclusive, not pass.
- Exit: verifier returns bounded passed/failed/inconclusive and rejects cached
  success; long checks have explicit bounded execution/deadline policy.

### 5. Acceptance, documentation and completion

- Run local syntax, unittest, Node, render, schema and `promtool` config/rule tests.
- On the designated disposable appliance test NetBox-down versus token-only
  failure, removed tool, TLS/default-page failure, worker hang/frozen output,
  removed target/rule, Prometheus outage, OpenClaw outage, runner failure and
  credential rotation. Simulate disk thresholds safely.
- Test canary scheduling under legitimate runner load, generation activation
  interruption, dashboard query errors and deployment pending/freshness gates.
- Repeat Ansible for idempotence; run reboot acceptance when authorized. Restore
  every fixture and check healthy recovery with normal credentials/lifetimes.
- Update README/operator contracts and actual implementation status. Store
  sanitized evidence under the selected appliance's artifacts directory.
- Exit: adjusted KRG-15 scope is proven, with future unconfigured integrations
  clearly identified; no inherited historical acceptance used as new evidence.

## Validation and rollout boundaries

This planning pass used repository files, the Linear handoff/architecture/NFR,
related issue descriptions, and upstream pinned source. It contacted no appliance,
read no protected credentials, executed no model request and changed no runtime
configuration. Runtime compatibility and fault/reboot acceptance remain untested.

Before live work, select and verify the authorized target/inventory and preserved
controller inputs. Historical development results do not authorize a target or
disruptive tests for this new task. Local implementation and tests can proceed
without these deployment details; ask only when dependent live work is ready.

This is best delivered in the five reviewable stages above. The first stage
resolves the largest integration risks before broad exporter/rule work. The full
feature includes failure testing and recovery; installing collectors alone is not
a partial substitute for the health contract.

## Sources

- [KRG-15 and attached implementation handoff](https://linear.app/krglv/issue/KRG-15/add-self-monitoring-for-infrabox-with-prometheus)
- [InfraBox architecture](https://linear.app/krglv/document/infrabox-architecture-63711ea0a978)
- [InfraBox NFR](https://linear.app/krglv/document/infrabox-non-functional-requirements-62ba8aaebb57)
- [Pinned OpenClaw metrics registration](https://github.com/openclaw/openclaw/blob/v2026.9.4/extensions/diagnostics-prometheus/index.ts)
- [Pinned OpenClaw exporter implementation](https://github.com/openclaw/openclaw/blob/v2026.9.4/extensions/diagnostics-prometheus/src/service.ts)
- [Pinned OpenClaw HTTP invocation boundary](https://github.com/openclaw/openclaw/blob/v2026.9.4/src/gateway/tools-invoke-http.ts)
- [Pinned OpenClaw shared tool invocation](https://github.com/openclaw/openclaw/blob/v2026.9.4/src/gateway/tools-invoke-shared.ts)
- [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)
- [Prometheus alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Grafana alert-rule view](https://grafana.com/docs/grafana/latest/alerting/monitor-status/view-alert-rules/)

## Implementation decisions after pinned-runtime validation

- Native fixed HTTPS/dependency collectors and the node_exporter textfile collector
  cover the proposed blackbox/database exporter functions. This avoids additional
  exporter listeners and runtime credentials. PostgreSQL statistics use a NOLOGIN
  pg_monitor role; actual PostgreSQL/Redis TLS and RQ checks use one small process
  inside the existing NetBox runtime, without booting Django.
- Diagnostics is the official separately packaged 2026.9.4 plugin. Its npm integrity
  and install provenance are pinned and verified through the official installer.
- The release's HTTP tools endpoint cannot materialize MCP tools. The NetBox probe
  uses OpenClaw's real bundle MCP runtime, fixed read arguments and applicable tool
  policy. It does not claim full conversational authorization parity. The native
  health plugin separately declares its tool contract and startup activation.
- The read-only native health service uses the container SELinux domain and a
  shared Unix socket. A separate root-owned public catalog avoids exposing private
  `/etc/infrabox` contents. SELinux remains enforcing; no generic host socket rule
  or network health port is introduced.
- The verifier may request at most five rounds in its ordinary five-minute window,
  about 60 seconds apart, to accommodate scheduling jitter while requiring three
  distinct successful observations spanning at least 120 seconds.
- Live acceptance results are tracked in IMPLEMENTATION_STATUS.md and deployment
  logs, rather than inferred from this plan or generated test scripts.

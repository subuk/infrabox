# InfraBox continuous monitoring

KRG-15 adds continuous checks without model calls. Prometheus owns all thresholds,
recording rules and alert states. Grafana provisions **InfraBox / InfraBox Health**
using datasource `infrabox-prometheus`. Alertmanager and notification delivery are
not configured. The dashboard displays pending/firing alerts directly from
Prometheus and distinguishes service, integration and monitoring coverage failures.

`infrabox_health` is the read-only OpenClaw tool. Its only optional input is a
component name. It reads the same rules via the local adapter; it cannot run a
probe, query arbitrary PromQL, dispatch a job or change infrastructure. The host
CLI is `python3 /usr/local/libexec/infrabox-monitoring/health.py`. The JSON contract
is in `schemas/infrabox-health.schema.json`; responses are bounded to 8 KiB and
20 issues. Truncation never changes the overall state.

States are healthy, warning, critical and unknown. Overall precedence is critical,
unknown, warning, healthy. Coverage is returned independently. Pending failure
conditions are visible immediately and block post-change verification. A fresh
scrape of an old observation does not establish health. Missing rules, queries,
catalogs, expected checks or observations never imply success.

## Cadence and retention

- Scrape/evaluate and basic service/HTTPS checks: 30 seconds.
- Integration/authentication checks: 60 seconds.
- Runner execution and canary history cleanup: 300 seconds, independent timer.
- Prometheus retains 15 days with a default 2 GB size cap. Leave additional disk
  headroom for WAL, active data and other appliance services.

The dedicated private Gitea repository is `infrabox-monitor/canary`. The workflow
has a one-minute job limit, no checkout, no generated artifact and no managed-host
credentials. Completed run history is automatically deleted after one hour, with
at most 12 completed runs retained. Active runs are never deleted by retention.
Only this repository is cleaned; user repositories and job histories are untouched.
The settings are `integration_checks_canary_keep` and
`integration_checks_canary_max_age`. Cleanup failure is itself a monitored check.

A busy capacity-one runner may queue a canary. Its first pending run has unknown
execution coverage until it completes; an existing successful observation retains
its original age. The monitor keeps a correlated run
ID and refuses overlap. Queue timeout is distinct from job execution timeout;
normal user inactivity alone never means runner failure.

## Deployment and tests

Use the selected inventory and protected inputs explicitly. For example:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml monitoring-deploy.yml -e @.secrets/infrabox1/inputs.json
```

For existing monitoring, the wrapper captures a baseline, applies native OpenBao/Gitea telemetry, OpenClaw and
observability, then runs a trusted verifier. The verifier requires three distinct
successful observations completed after the change and spanning at least 120
seconds. It can request fixed affected probes more frequently during that window.
Its result is passed, failed or inconclusive, with revision/generation and baseline
issues. It does not replace permission, TLS/isolation or feature acceptance tests.

First deployment may have unknown coverage until probes and rules have fresh data.
Never shorten freshness requirements or disable checks just to obtain green.
`site.yml` captures the same baseline and runs the stabilization gate after component
verification. `verify.yml` remains the explicit full appliance verification entry point.

Local validation includes Python tests, Ansible syntax, schema/config rendering, Node adapter tests
and generated promtool fixtures:

```sh
.venv/bin/python -m unittest discover -s tests
node --test tests/*.mjs
.venv/bin/ansible-playbook -i inventories/local/hosts.yml site.yml --syntax-check
.venv/bin/python scripts/test-monitoring-rules.py /tmp/infrabox-rule-tests
# Run pinned Prometheus promtool in that directory:
# promtool test rules test.json
```

## Trust and compatibility

PostgreSQL uses a `NOLOGIN` role with `pg_monitor` for native statistics; the host
worker selects it through local peer authentication. Actual application PostgreSQL
and Redis TLS connections and RQ queues are read in one short NetBox-runtime
process using its current configuration. RQ worker liveness follows its expiring
registration, including all configured high/default/low queues.

The fixed native host worker has deliberate host access for selected unit checks
and runtime-local commands. App/probe containers have no host runtime sockets.
The health adapter runs as `nobody` in the SELinux container domain; its socket
gives OpenClaw only bounded health reads. Only the nonsensitive generated catalog
is published under `/var/lib/infrabox-monitoring-public`, owned by root and read
only by the adapter. `/etc/infrabox` remains private. Persistent SELinux file-context
rules cover only that public directory and `/run/infrabox-health`. Node exporter listens on the private backend bridge, with a matching
firewall rule. The isolated runner remains on its own network and UID mapping.

Monitoring credentials are materialized into mode-0600 files in a private
monitoring directory. Gitea's monitor can access its own private canary repository;
Grafana uses a Viewer service account. OpenBao health also validates the certificate Agent’s current token through its
configured verified HTTPS endpoint. OpenBao metrics use a separate periodic
read-only telemetry token which can renew only itself. Root credentials arrive
only during Ansible provisioning, over stdin, and are never retained by monitors.

OpenClaw 2026.9.4 diagnostics is an official separately packaged plugin, pinned
with an npm integrity lockfile and installed through the official CLI into persistent
state. Its recorded version, integrity and provenance are verified before startup. The release's HTTP tools
endpoint does not expose the configured NetBox MCP tool. Its integration probe
therefore uses OpenClaw's actual MCP runtime/materialization and token-file launcher,
with fixed read arguments, validated result shape and an explicit tool-exposure
check. This is runtime integration evidence, not full conversational authorization
parity. No NetBox inventory is written by monitoring.
The fixed MCP runtime has a 20-second deadline and its NetBox read has a
10-second deadline. The host allows 40 seconds for the enclosing Podman command,
including process startup/teardown; this does not extend either inner deadline.

The future trusted Platform runner and OpenClaw-to-Gitea discovery tools are not
installed by KRG-15. KRG-6/KRG-9 must add checks when they provision these features.
Model/search availability is based only on observed native events. No paid model
canary is scheduled; an idle provider is not recently verified, not proven healthy.

An appliance-local HTTPS probe does not establish reachability from a user's LAN.
Whole-host/power/network loss also needs an observer on another machine. An
optional self-hosted observer can query configured public HTTPS endpoints using
InfraBox RootCA and require the expected application response; no SaaS is needed.
Grafana itself is unavailable during a Grafana/PostgreSQL/host outage, so the host
health CLI and external observer are complementary access paths.

On an explicitly authorized development appliance, run `acceptance-monitoring.yml`
for service loss, pending/firing, recovery and frozen/absent observation tests.
It temporarily stops NetBox, the probe scheduler and Prometheus and restores each
service. Capture a healthy baseline with `monitoring-baseline.yml`, then run
`acceptance-reboot.yml` and `monitoring-verify.yml` sequentially to verify restart,
TPM auto-unseal, preserved CA identity,
service isolation and post-boot monitoring. Do not run disruptive tests implicitly
against an unspecified inventory.

After at least two disposable canaries have completed, the optional host-side
`scripts/test-monitoring-retention.py` exercises cleanup with a one-run test limit.
It takes the normal canary lock and leaves the configured 12-run / one-hour policy
unchanged. It deletes only completed history in `infrabox-monitor/canary`.

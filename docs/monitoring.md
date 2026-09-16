# InfraBox continuous monitoring

[Documentation index](README.md)

InfraBox runs continuous checks without model calls. Prometheus owns all thresholds,
recording rules and alert states. Grafana provisions **InfraBox / InfraBox Health**
using datasource `infrabox-prometheus`. Alertmanager and notification delivery are
not configured. The dashboard displays pending/firing alerts directly from
Prometheus and distinguishes service, integration and monitoring coverage failures.

`infrabox_health` is the read-only OpenClaw tool. Its only optional input is a
component name. It reads the same rules via the local adapter; it cannot run a
probe, query arbitrary PromQL, dispatch a job or change infrastructure. The host
CLI is `python3 /usr/local/libexec/infrabox-monitoring/health.py`. The JSON contract
is in [the health schema](../schemas/infrabox-health.schema.json); responses are bounded to 8 KiB and
20 issues. Truncation never changes the overall state.

States are healthy, warning, critical and unknown. Overall precedence is critical,
unknown, warning, healthy. Coverage is returned independently. Pending failure
conditions are visible immediately and block post-change verification. A fresh
scrape of an old observation does not establish health. Missing rules, queries,
catalogs, expected checks or observations never imply success.

## Cadence and retention

- Scrape/evaluate and basic service/HTTPS checks: 30 seconds.
- Integration/authentication checks: 60 seconds. Native MCP has its own timer
  and lock, so runtime materialization cannot block basic service observations.
- Runner execution and canary history cleanup: 300 seconds, independent timer.
- Prometheus retains 15 days with a default 2 GB size cap. Leave additional disk
  headroom for WAL, active data and other appliance services.

The dedicated private Gitea repository is `svc-monitor/canary`. The workflow
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
provisioning verifies its exact PAT scopes, token identity, absence of unrelated
teams/repositories and the canary's privacy. A verified replacement is published
before retiring older tokens with the managed monitoring prefix.
Grafana uses a Viewer service account. OpenBao health also validates the certificate Agent’s current token through its
configured verified HTTPS endpoint. OpenBao metrics use `svc-monitor` on the service LDAP mount, with only the
metrics policy and self-token operations. Each probe revokes its short-lived
token after reading metrics; this also exercises the real OpenBao-to-LLDAP
dependency. The monitoring LDAP password is protected in `secrets/ldap.json`. Root credentials arrive
only during Ansible provisioning, over stdin, and are never retained by monitors.

OpenClaw 2026.9.4 diagnostics is an official separately packaged plugin, pinned
with an npm integrity lockfile and installed through the official CLI into persistent
state. Its recorded version, integrity and provenance are verified before startup. The release's HTTP tools
endpoint does not expose the configured NetBox MCP tool. Its integration probe
therefore uses OpenClaw's actual MCP runtime/materialization and token-file launcher,
with fixed read arguments, validated result shape and an explicit tool-exposure
check. This is runtime integration evidence, not full conversational authorization
parity. No NetBox inventory is written by monitoring.
The host supervises `infrabox-mcp-runtime.service`, a dedicated process inside
OpenClaw's existing container and resource limits. It loads the pinned native
modules once and retains the native MCP connection between observations. Each
observation rereads current configuration, evaluates current policy and performs
a new fixed NetBox read. No authorization result or API response is cached.
A digest of the complete configuration and mounted NetBox token invalidates the
connection before the next request when either changes. The native launcher
continues to own credential delivery. Any failed observation closes the
connection; the next observation can create a new one, without retrying or hiding
the failed observation. Shutdown disposes the connection and its child process.
Its private container-only Unix socket accepts exactly `probe\n`, permits one
in-flight operation and returns only success or a fixed failure reason. The socket
has mode 0600 in a 0700 directory; it publishes no network listener or host mount.
The process follows OpenClaw stop/restart and boot. A bounded stop command checks
the exact process identity before signalling it, preventing an orphaned probe
server when only the helper restarts. A stuck operation terminates this helper
and systemd restarts it; the Gateway is unaffected.
Each fixed operation retains its 60-second overall deadline and 10-second actual
NetBox read deadline. The host allows 75 seconds for its short-lived Podman
client. A cold or unavailable helper fails the probe; it never returns cached
success. Freshness and stabilization requirements remain unchanged.
The helper also enables Node's native compile cache in the container's disposable
`/tmp/infrabox-monitoring-compile-cache` directory to reduce startup cost. See the
[Node.js compile-cache contract](https://nodejs.org/download/release/v24.18.0/docs/api/module.html#module-compile-cache).
The worker drains stdout and stderr concurrently through pipes, with a 1 MiB
limit per stream and the same overall command deadline. A JSON success response
does not pass the check until the process actually exits successfully. Output
overflow or a hung process fails the observation and triggers bounded cleanup.
Fixed host probes use the pinned Podman's attached `exec --no-session` mode to
avoid database session tracking and lock contention from frequent concurrent
commands. They retain their existing container users, stdin, exit-status checks
and isolation. These short-lived exec sessions are not listed by the Podman
session API; probe results remain in the normal monitoring observations. See
[the Podman option contract](https://docs.podman.io/en/v5.8.2/markdown/podman-exec.1.html#no-session).

The optional [Platform runner](platform.md) and [OpenClaw discovery tools](openclaw-discovery.md)
have separate provisioning and acceptance checks. Continuous monitoring does
not schedule managed-host discovery or prove that a discovery run succeeds.
Model/search availability is based only on observed native events. No paid model
canary is scheduled; an idle provider is not recently verified, not proven healthy.

An appliance-local HTTPS probe does not establish reachability from a user's LAN.
Whole-host/power/network loss also needs an observer on another machine. An
optional self-hosted observer can query configured public HTTPS endpoints using
InfraBox RootCA and require the expected application response; no SaaS is needed.
Grafana itself is unavailable during a Grafana/PostgreSQL/host outage, so the host
health CLI and external observer are complementary access paths.

Run `acceptance-monitoring-mcp.yml` to test the fixed private transport, helper
restart without an orphan, and policy changes in a disposable configuration within
one native process. It restarts only the helper and never edits production policy.

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
unchanged. It deletes only completed history in `svc-monitor/canary`.


Central identity monitoring covers LLDAP unit/health, database TLS and verified LDAPS checks, OIDC issuer
and signing-key availability, native application login links, and protected
runtime-token file checks. Probes emit fixed reason codes, never credentials.
Grafana's Viewer monitoring service account and token use the native
[service-account API](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/api-legacy/serviceaccount/).
The one-shot controller operation authenticates the existing central technical
administrator through verified LDAP; the runtime monitor receives only its
Viewer token. The helper checks native identity and datasource access before
KV/file publication and retirement of old tokens. It refuses conflicting roles.
No application user or token is created by writing Grafana database tables.

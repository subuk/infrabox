# Monitoring coverage failure

Affected capability: health cannot be established reliably. Unknown is not a
confirmed application outage, and absence of firing alerts is not success.

Check `systemctl status infrabox-checks.timer infrabox-mcp-check.timer infrabox-mcp-runtime.service infrabox-canary.timer
infrabox-node-exporter infrabox-health prometheus`, then Prometheus readiness,
Targets and Rules. Inspect only bounded unit status and rule errors; never print
monitoring token files, application environments or full container metadata.
Compare catalog generation, rule generation, observation timestamps and the
worker heartbeat. A clock jump, dead worker, partial installation or removed
scrape/rule can explain stale evidence.

For a fixed command timeout, the private host file
`/var/lib/infrabox-monitoring/last-command-timeout.json` records the operation
category, deadline and whether a structured success had already been returned.
It contains no arguments, credentials or raw subprocess output. The deployment
verifier reports observed failures and unstable check IDs even after recovery.

Correct the owning Ansible configuration, validate it and apply it again. Preserve
working config if validation fails. Recheck actual post-recovery observations;
repeatedly reading an old sample does not verify recovery. Warmup after first
installation/reboot stays unknown until required evidence is present.

Stopping services, fault injection and reboot require an authorized test context.
Do not disable SELinux/TLS or drop checks to hide coverage failures.

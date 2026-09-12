# Implementation status

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

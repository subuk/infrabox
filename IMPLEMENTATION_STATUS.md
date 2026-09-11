# Implementation status

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

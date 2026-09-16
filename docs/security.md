# Secrets, certificates and recovery boundaries

[Documentation index](README.md) · [Identity](identity.md)

## Controller ownership and client trust

Keep `.secrets/` directories private (0700) and secret files mode 0600.
The per-appliance `inputs.json` contains protected bootstrap inputs;
`openbao-init.json` contains the initial root token and recovery shares. Preserve
both for the correct inventory alias. Do not print, commit, or include their
contents in reports. Pass inputs as a protected file, never secret argument values.

The retained initial root token belongs only on the controller and is required
for Ansible repair. Do not revoke it under the current design or persist it on
the appliance. Applications, jobs and both Agents must never receive it.
Human KV administration uses a central role; see [identity](identity.md).

PKI has a RootCA, ServerCA and UserCA. The UserCA does not provide application
user-certificate login. The public RootCA is exported to
`artifacts/<inventory_hostname>/root-ca.crt` and installed on the appliance at
`/etc/infrabox/pki/root-ca.crt`. Import it into clients before HTTPS use.
It contains no private key. Preserve CA identity across reruns and recovery.

## Certificate and credential lifecycle

[Agent leased templates](https://openbao.org/docs/agent-and-proxy/agent/template/)
own routine certificate issuance and renewal. Each response produces one
certificate/key/chain generation, validated and published atomically before
reload. nginx, PostgreSQL and OpenBao reload certificates; Redis uses a
controlled restart. Redis renewal must not restart NetBox.
Default leaf lifetime is 14 days. A repeat Ansible run does not restart an
unchanged Agent. Explicit Agent restarts can issue replacement certificates.

Agent SecretIDs have a seven-day lifetime. A native hourly timer checks for daily
rotation using the existing Agent token. The policy permits replacement and
accessor destruction for its own AppRole only, in addition to server certificate
issuance. The replacement login is tested before publication. This timer handles
credentials, not leaf certificate renewal. Development acceptance exercises
rotation and checks that the old SecretID is rejected.

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

## Component credentials

The certificate Agent uses its restricted AppRole. [OpenClaw](openclaw.md#openbao-credentials-and-recovery)
uses an independent periodic orphan token and token-file authentication;
[Platform](platform.md#target-credentials-and-trust) has its own namespace and
periodic token. Their native renewal services can renew only their own tokens.
Healthy reruns preserve credentials; replacement must be verified before the
superseded credential is retired. A stolen periodic token can remain usable if
its holder keeps renewing it, so expiry is not a substitute for revocation.

[Monitoring](monitoring.md#trust-and-compatibility) uses scoped identities and
protected runtime files. NetBox and Gitea integration credentials are separate
from the Gateway login token and from controller/provisioner credentials.
Service-password changes must also update the protected controller input.

## Recovery scope

Supported repair covers expired leaf certificates, certificate Agent credentials
and component tokens through their owning playbooks. Use the
[established-appliance procedure](operations.md#apply-or-repair-configuration),
then the appropriate [runbook](README.md#troubleshooting). Never treat a fresh
bootstrap or missing initialization record as an ordinary repair path.

There is no implemented full-appliance backup/restore, TPM-loss recovery or HA
procedure. Retaining controller recovery material is necessary but is not a
complete backup or proof of recovery after loss of TPM/storage. Do not clear the
TPM, discard Raft data, recreate seal material or replace CA identities to fix
an authentication or certificate failure.

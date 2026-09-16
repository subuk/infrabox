# Service or dependency failure

Affected capability is named in the check summary. A unit, HTTPS interface,
application dependency and OpenClaw integration are separate observations.

Start with the relevant unit state, its bounded error log and configured HTTPS
endpoint using InfraBox CA. If only integration authentication fails, inspect the
owning identity/permission verification, not the application's data directory.
An HTTP 200/default nginx page does not prove the expected application is ready.
Use the existing component `verify` tasks for actual authenticated DB/Redis TLS,
NetBox permissions and PKI checks. Do not print credentials or raw inventory.

For certificates inspect the actual served chain and certificate Agent/renewal
unit state. Leaves normally live 14 days; configured warnings are within their
renewal window. Repair established PKI through `pki.yml`, retaining verified
HTTPS and the authenticated management socket. Never reinitialize OpenBao,
replace CA/TPM identities or enable network HTTP to bypass an expired certificate.

After a fix, require successful new observations and targeted component tests.
Use temporary credentials and disposable fixtures for authorized failure tests;
restore normal credentials and check recovery before completion.


## Central identity

First inspect `lldap`, its PostgreSQL TLS connection, `openbao`, the native OIDC
issuer endpoint and each application's `/login` endpoint. The `identity_ldap`,
`identity_oidc`, `identity_clients`, `identity_materialization` and
`openbao_metrics` observations isolate these dependencies. The last one performs
real service LDAP authentication and reads only OpenBao metrics. It does not
run a model or obtain human OIDC access.

LLDAP is authoritative for passwords, identity type and membership. Humans use
LDAP-password login to OpenBao and native application OIDC; service LDAP filters
reject humans. Mandatory MFA and the enrollment login path are disabled. Existing
TOTP secrets are retained and are not used for the current login flow.
NetBox rejects local-password fallback. Gitea disables `manage_credentials` for
external identities, disables mail-based recovery, and rejects password-reset
routes at nginx. Personal PAT and SSH-key management remain available. Only
global administrators can create organizations. Grafana disables its built-in password backend and login
form; Basic authentication reaches only native LDAP, whose filter admits the
single technical `svc-identity-admin` with `infrabox:grafana:admin`. Ansible preserves
existing passwords, membership and healthy runtime tokens. A removed central
service role causes provisioning to fail rather than restoring the membership.
After changing a service password, update its private controller input before
running its owning role. New human identities are created by OpenBao on first LDAP login; do not run
`identity.yml` for user additions. The login page at `https://vault.<domain>/login/`
collects a missing email/display name and permits later profile edits. These are
user-owned OpenBao metadata, separate from LLDAP. LDAP alias metadata supplies the
login and native external groups supply roles; editable profile keys never grant
permissions. The self-profile policy permits only read/update of the caller's own
entity metadata. It cannot list other identities, edit aliases/policies, rename
entities, or change disabled status. Self-declared email is not marked verified,
and Gitea automatic account linking stays disabled. Ansible preserves existing
entities and profiles; LDAP deletion/type changes reject new logins, while existing
tokens and application sessions must be revoked separately when required.

| Central role | Native permission | Grant/removal takes effect |
| --- | --- | --- |
| `infrabox:gitea:admin` | Gitea site admin and organization creation | Next login |
| `infrabox:gitea:<org>:admin/developer/reader` | Owners / Developers Code Write / Readers Code Read | Native team synchronization at next login |
| `infrabox:gitea:<org>:operator/discovery` | Execution repository Code Read / Actions Write | Native team synchronization at next login |
| `infrabox:netbox:admin/editor/reader` | Native superuser / 18-model CRUD / Platform 21-model read | Native OIDC group sync or service LDAP authentication |
| `infrabox:grafana:admin/editor/reader` | GrafanaAdmin / Editor / Viewer | Next OIDC login |
| `infrabox:openbao:admin` | All KV, no PKI/auth administration | New human LDAP-password login |
| `infrabox:openbao:monitor` | Metrics only on service LDAP | Each monitoring probe obtains and revokes its own token |

Grafana refuses to remove its last server administrator. Keep the same central
technical administrator as its bootstrap administrator; no extra local account
or password is created. This permits normal promotion/demotion of personal OIDC
users. Removing the technical LDAP role prevents new technical authentication;
it does not itself erase an existing Grafana mirror or native tokens. Restore
access through an explicitly authorized central role assignment during recovery,
not a recurring Ansible membership repair.
The pinned OAuth connector logs opaque access-token parse failures at warning
level. Its logger is restricted to errors to prevent credential-bearing logs.

Existing sessions can retain claims until their own expiry. Revoke Gitea PATs
through the native access-token management endpoint and SSH keys through native
user-key management; revoke active web sessions separately. In NetBox disable
or delete the exact native Token record and invalidate the user's application
sessions for immediate revocation. Remove/demote the central role as well, so a
new authentication cannot recreate the grant. Avoid treating an LLDAP filter miss
as proof that an already-issued NetBox token stopped working. Grafana requires
revoking its own session/service token separately from an OpenBao token.
For OpenBao, revoke the exact token/accessor or the selected LDAP login lease
prefix through protected controller management; never expose the retained root
token in shell arguments or runtime configuration.

A lost TOTP device does not block the current password-only login. For explicit
cleanup of a retained legacy TOTP secret, verify the person's identity and reset
exactly that human:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml identity-reset-totp.yml -e @.secrets/infrabox1/inputs.json -e identity_reset_username=personal-user
```

Use the selected inventory alias in the protected input path. This explicit
playbook refreshes the normal identity configuration, resolves the canonical
human by its directory UUID, invokes native TOTP admin-destroy and revokes that
human/enrollment login lease prefix. It refuses service or missing users and
never runs from `site.yml`. This does not enable MFA or require enrollment at the next login.
Application sessions/native credentials still require separate revocation.
Browser/UX acceptance is separate from the native API acceptance playbooks.

`acceptance-identity-recovery.yml` requires explicit outage authorization. It
stops LLDAP, waits for critical LDAP/authentication alerts, and restores it;
then stops OpenBao, verifies the OIDC outage and alerts, and restores it through
the host. Fresh LDAP password authentication fails during the LLDAP outage;
the OpenBao outage also prevents OIDC code exchange. Each outage can last
several minutes while alerts become critical. Existing central/application
sessions have their own lifetimes and are not revoked by this test.
The helper uses only the monitor's own LDAP identity, revokes its
temporary tokens, and uses no OpenBao root token. Both units are restored in
`always` tasks if a check fails. Final checks verify central configuration,
appliance health, TLS and preserved OpenBao cluster/trust identity. Certificate
expiry and whole-appliance reboot remain separate acceptance playbooks.

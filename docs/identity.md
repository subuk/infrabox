# Identity and access

[Documentation index](README.md) · [Installation](installation.md)

## First login and personal accounts

The directory stage uses `lldap.yml` after PKI/certificate Agent and
PostgreSQL. `identity-directory.yml` applies the role catalog and technical
identities once. There is one technical superadministrator, `svc-identity-admin`:
Ansible uses its protected `lldap_admin_password`, and an operator can use the
same account in LLDAP to create a personal account. Set that personal account's
`infraboxIdentityType` to `human` and assign the required `infrabox:*` role groups.
The shared administrator is typed `service`; it has no MFA and cannot enter human
SSO. Dedicated reader, OpenClaw, Platform and monitoring identities retain limited roles.
Grafana also authenticates this same technical administrator through a narrowly
filtered native LDAP path. Its built-in local-password backend stays disabled.
Keeping that central technical administrator satisfies Grafana's native
last-administrator safeguard and permits personal OIDC administrator demotion.
No initial human name, email or password is required in inventory.

`identity.yml` configures the authentication infrastructure; it is not needed
when adding a human or editing their profile. Human LDAP login creates the OpenBao
identity automatically, keyed by the immutable LDAP `entryUUID`. Logins and role
groups come from LDAP. Mandatory MFA is disabled by operator choice; existing
TOTP secrets are retained but enrollment is no longer part of login.

Open `https://vault.<domain>/login/` or begin OIDC login from an application.
On first login, provide your email and display name in the profile form. These
values belong to your OpenBao profile, independently of LLDAP's profile. Use
the edit-profile action on the login page to update them later. Users may read/update
only their own entity metadata; policies, aliases, entity names, disabled state
and other users are inaccessible. Username and role claims never use writable
profile fields. Email is self-declared (`email_verified=false`); automatic Gitea
account linking remains disabled. Ansible does not overwrite user-owned profiles.

The retained OpenBao root token remains on the controller for infrastructure
management. Normal sign-in and profile changes use the user's own finite token;
no root token or additional identity service is deployed. LLDAP is exposed at
`https://ldap.<domain>/`. Trust the public CA exported to
`artifacts/<inventory alias>/root-ca.crt` before browser testing. The login page
keeps the finite human token in the current browser tab's session storage;
passwords are cleared after the login request. Signing out revokes the OpenBao
session; application sessions retain their own finite lifetime.
Role grants/removals are applied at the next native login. Existing application
sessions, PATs, SSH keys and NetBox tokens have separate lifetimes; group removal
is not token revocation. See the [identity recovery runbook](runbooks/services.md#central-identity).
`identity_gitea_organizations` optionally lists managed Gitea organizations; its
default is the configured Platform organization. The shared role catalog, OIDC
claims, service LDAP maps and native Developers/Readers teams use this list.
Operators and OpenClawDiscovery remain restricted to the Platform execution repository.

After rotating a service bootstrap or bind-reader password, update its protected
controller input; Ansible does not repair access by resetting an existing LDAP
password. Personal passwords are managed in LLDAP.

## Roles and revocation

The [central identity runbook](runbooks/services.md#central-identity) is the
authoritative role-to-application mapping and recovery procedure. It describes
role propagation, native session/token revocation and legacy TOTP cleanup.

The original [KRG-17 design](https://linear.app/krglv/document/krg-17-lldap-openbao-identity-implementation-plan-for-codex-db5d9d3c2c28)
is implementation background. Its mandatory MFA/enrollment flow was superseded
by the first-login and self-profile behavior described here. Historical
acceptance remains in [implementation status](../IMPLEMENTATION_STATUS.md).

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

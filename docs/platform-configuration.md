# Managed server configuration

[Documentation index](README.md) · [Platform deployment](platform.md)

Platform's **Configure managed hosts** workflow consumes desired state from NetBox
Config Context through the existing flattened dynamic inventory. `discover` remains
responsible for observations and reconciliation; configure does not reconcile facts.
The initial role catalog is `packages`, `chrony`, `sshd`, supporting AlmaLinux 10.

When upgrading an existing appliance, run the controller secret generator with its
inventory alias before `automation.yml`. It adds only missing inputs, including
`identity_netbox_source_password`, preserving existing credentials:

```sh
.venv/bin/python scripts/create-controller-secrets.py --inventory-hostname infrabox1
.venv/bin/ansible-playbook -i inventories/local/hosts.yml automation.yml -e @.secrets/infrabox1/inputs.json
```

Substitute the explicitly selected inventory and appliance alias. Core uses native
central-directory bootstrap for `svc-netbox-source`; later membership remains
owned by the central directory. A missing/changed assignment fails verification.

Use the **InfraBox Platform** Config Context Profile for shared configuration
contexts. NetBox's native Git Data Source clones the approved execution branch
from the local Gitea Platform repository over verified HTTPS. A separate central
`svc-netbox-source` identity has Code Read only for that repository, no Actions
access and no code-write or administrative rights. Its dedicated credential is
provisioned from protected controller inputs into the native Data Source password
field. No Platform repository is mounted into either NetBox container.
The Data Source retains only `schemas/config-context.schema.json`. PR schemas are validated in the PR job and do
not update the active profile. NetBox's local Device/VM context has no profile field
in the pinned release: configure validates the merged effective data independently.

Assign roles with `infrabox_roles: {chrony: {enabled: true}}`. Each role's prefixed
inputs and defaults live in the Platform repository. Partial contexts are allowed.
Unknown roles/types and misspelled role-owned keys fail; native Ansible connection
variables retain their normal semantics. Disabled roles are skipped and never
implicitly uninstalled. Keep production secrets in OpenBao, not Config Context.

Configuration execution goes only through one `configure.yml` workflow:

- Manual: select the native inventory pattern in `limit`; `check=true` and
  `diff=true` are the safe defaults. Explicit `check=false` applies changes.
- PR: exact reviewed head checkout; check and diff are forced. Role-only changes
  select hosts enabling at least one changed role. Shared/unknown paths use all.
  Every changed role must have at least one real managed target or the job fails
  before Ansible. Local fixture tests are not a substitute for that coverage.

The job snapshots its NetBox inventory privately and uses the same selected hosts
and data for validation and execution. Role semantic assertions run across the
whole selected set before any configuration operations. A failed apply may have
changed earlier tasks; there is no automatic rollback. Inspect the result, correct
the owning role or desired state, and rerun the controlled workflow.

PR authors in the local Platform repository must be trusted maintainers. Check mode
is not a sandbox. Fork PRs are excluded from the credential-bearing runner. Operators
retain Actions Write/Code Read, Developers Code Write/Actions Read with PR access,
and Readers read access. The protected execution branch stays provisioner-owned.
Promotion remains the existing Core source/ref synchronization: preserve the
reviewed commit in the canonical source, then deploy it with `automation.yml` and
the explicitly selected inventory. Direct merging into the mirrored execution
branch does not change Core's canonical source.

Configure compares runtime dependencies and policy-helper fingerprints separately
from source SHA. Role-only PRs can use a compatible existing runtime. Runtime or
policy changes require provisioning the candidate runtime before rerunning PR
validation; mismatches fail explicitly. Manual runs require the deployed approved
SHA. Discovery retains its stricter existing exact-SHA runtime check.

Artifacts `configure-<run>-<attempt>` contain revision, runtime fingerprint, mode,
scope, host recap and bounded sanitized task/diff output. Raw inventory and temporary
credentials are never artifacts. Failures remain failures, including artifact upload.
Seven-day retention is requested; actual expiry is controlled by Gitea. Configure
does not overwrite discovery health observations.

For acceptance, select an authorized managed host and approve its exact Config
Context. Use a real PR for check-mode/scoping acceptance, then manual apply,
second apply with `changed=0`, and final check. Do not run direct Ansible on managed
hosts to bypass pipeline policy. `scripts/acceptance-configure.py` supports recorded
manual/PR dispatch and read-only polling/download; it preserves uncertain dispatches
instead of automatically starting another job. The included KRG-10 acceptance
scope is explicitly limited to `testbox.net.krglv.com`; this is development evidence,
not a default target for another operator.

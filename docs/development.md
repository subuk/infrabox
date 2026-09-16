# Development and acceptance

[Documentation index](README.md)

Read [AGENTS.md](../AGENTS.md) for repository workflow and the
[design/status map](README.md#design-and-implementation-history) for implementation
contracts. This guide describes code-change validation; it does not authorize
access to a host. Documentation-only KRG-19 work intentionally runs no executable
validation, playbooks, workflows or remote operations. Review Markdown by inspection.

Use the pinned [controller environment](installation.md#controller-setup).
All example commands use `inventories/local/hosts.yml` and the `infrabox1` alias;
substitute the selected inventory and protected input directory consistently.

## Local checks

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml site.yml --syntax-check
.venv/bin/ansible-playbook -i inventories/local/hosts.yml foundation.yml --syntax-check
.venv/bin/ansible-playbook -i inventories/local/hosts.yml openbao-runtime.yml --syntax-check
.venv/bin/ansible-playbook -i inventories/local/hosts.yml pki-bootstrap.yml --syntax-check
.venv/bin/ansible-playbook -i inventories/local/hosts.yml certificate-agent.yml --syntax-check
.venv/bin/ansible-playbook -i inventories/local/hosts.yml services.yml --syntax-check
.venv/bin/python -m unittest discover -s tests
```

## Development acceptance

`acceptance-identity-applications.yml` exercises native first login, self-profile
permissions, HTTP/OIDC, service credentials and role demotion without a browser.
`acceptance-identity-projects.yml`
adds three disposable Gitea organizations, scoped human PAT/SSH access and role
removal across a configuration rerun. Both remove their disposable identities;
run them sequentially with the selected inventory and protected inputs.

These tests change the development appliance temporarily. Run them sequentially,
with the controller inputs and verified SSH host-key options described in the [installation guide](installation.md):

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-applications.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-renewal.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-recovery.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-reboot.yml -e @.secrets/infrabox1/inputs.json
```

Application acceptance creates and removes a temporary private repository and
SSH key, testing cloning/pushing over both Git transports and an actual Actions job. Renewal testing
uses three-minute certificates and restores 14-day issuance. Recovery testing
briefly stops Agent, lets one-minute leaves and an Agent SecretID expire, and
runs normal Ansible recovery. Expect a short HTTPS outage during that test.
Reboot acceptance verifies TPM auto-unseal, preserved CA identity, and the full
appliance after restart. Completed results and test logs are recorded in
[IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) and `artifacts/infrabox1/`.

## Component checks

Use the relevant component guide for its acceptance requirements:
[OpenClaw](openclaw.md#operations-and-validation),
[Platform](platform.md#verification),
[discovery](openclaw-discovery.md#verification-and-acceptance), and
[monitoring](monitoring.md#deployment-and-tests).
Node tests live in `tests/*.mjs`; scanner tests use
`node --test tests/test_subnet_plugin.mjs` and monitoring transport tests use
`node --test tests/monitoring.test.mjs tests/mcp-probe-runtime.test.mjs`.
Transport tests require local Unix socket access.

Never run configuration-changing playbooks concurrently against one appliance.
Obtain authorization for disruptive expiry, outage and reboot acceptance.
Restore normal lifetimes and healthy authentication even after a failed test.
Preserve sanitized results under `artifacts/<inventory_hostname>/` and report
passed, failed and not-run checks separately. Local tests and existing acceptance
scripts do not establish live acceptance; a prior host's evidence does not
validate a replacement appliance.

# Installation and bootstrap

[Documentation index](README.md) · [Architecture](architecture.md)

Run these instructions from the repository root on your controller. They are for
a fresh, uninitialized AlmaLinux 10 appliance. Use [operations](operations.md)
for an established installation. Do not begin a fresh install with `site.yml`.

## Prerequisites

Use an AlmaLinux 10 host with working SSH key authentication, sudo, SELinux
support and a persistent TPM 2.0 device at `/dev/tpmrm0`; a persistent virtual
TPM is supported. The scanner package build targets x86_64. The controller needs
Python with venv/pip and network access to install the pinned requirements and
collections. Appliance provisioning needs access to the configured package and
container registries. Review available storage and capacity for the enabled
services; this repository does not publish a measured minimum hardware profile.

Before deployment, establish the target, SSH user/key, verified host key, DNS,
AlmaLinux version, sudo access, TPM support/key size and network compatibility.
Use your own values; the development inventory is not a deployment default.
Keep SELinux enforcing and host-key checking enabled.

## Configuration for a local setup

Create a separate inventory for your appliance. The checked-in development
inventory contains deployment-specific values; replace them before use. If local
files already exist, edit them in place instead of running these copy commands.

```sh
mkdir -p inventories/local/group_vars
cp inventories/development/hosts.yml inventories/local/hosts.yml
cp inventories/development/group_vars/all.yml inventories/local/group_vars/all.yml
```

All commands below select the local inventory explicitly. Do not rely on
`ansible.cfg`, which defaults to the checked-in development host. Use `--limit` when the selected inventory contains other appliances.

Edit `inventories/local/hosts.yml` to set the target address and SSH user. Keep
the `infrabox` group, which the playbooks target. For example:

```yaml
all:
  children:
    infrabox:
      hosts:
        infrabox1:
          ansible_host: 192.0.2.10  # Replace with your appliance address.
          ansible_user: almalinux  # Replace with your SSH login.
          # ansible_ssh_private_key_file: ~/.ssh/id_ed25519
```

`infrabox1` is an example inventory alias, not a DNS name. Keeping that alias
matches the supplied secret generator and command examples. If you rename it,
pass `--inventory-hostname <alias>` to the generator and update the `-e @.secrets/.../inputs.json`
paths below. Initialization records and exported artifacts are stored under
`.secrets/<inventory_hostname>/` and `artifacts/<inventory_hostname>/`.

Review these settings in `inventories/local/group_vars/all.yml`:

| Setting | What to configure |
| --- | --- |
| `infrabox_domain` | Your service base domain, such as `infrabox.example.com`. Point this name to the appliance for the home page, plus wildcard DNS for `*.infrabox.example.com`, or individual `git`, `netbox`, `grafana`, `vault`, `ldap`, and `claw` records for services. The subdomain wildcard does not replace the main-domain record. |
| `infrabox_internal_domain` | The private container DNS suffix. The supplied `infrabox.internal` can normally remain; it does not need public DNS records. |
| `openbao_agent_openbao_address` | Match the internal suffix: `https://openbao.<infrabox_internal_domain>:8200`. This is the Agent's internal endpoint, not the public `vault` URL. |
| `openbao_tls_enabled` | Keep `true` for the final configuration. Use the explicit temporary overrides in the bootstrap procedure for a new appliance. |
| `platform_enabled` | The copied development inventory sets this to `true` and references a local source checkout and private known-hosts path. Set it to `false` for installation without Platform, or replace all `platform_*` deployment values using the [Platform guide](platform.md). |
| `tpm2_pkcs11_device` | The host TPM resource-manager device, normally `/dev/tpmrm0`. |
| `tpm2_pkcs11_key_bits` | Set the seal-key size supported by your TPM before initialization. The role default is `4096`; the copied development inventory overrides it to `3072`, so review that value explicitly. |

Keep the supplied storage/configuration paths, TPM token/key labels, and runtime
UID/GID values for a standard installation. Some helper scripts and systemd units
also use fixed paths, so changing a path variable alone is not a supported
relocation procedure. Once initialized, preserve the TPM store, seal-key identity,
and corresponding OpenBao data.

Check that the runner subnet `10.90.0.0/24` does not overlap your LAN or VPN.
If it must change, coordinate `gitea_runner_subnet`, `gitea_runner_gateway`,
and the runner source-range rule in `roles/nginx/templates/nginx.conf.j2`.
If enabling Platform, also review its `10.91.0.0/24` and `fd90:91::/64` networks.
The backend and scanner bridges use Podman's automatic subnet allocation;
check those allocated networks against your LAN/VPN and scan targets too. The standard
public ports are TCP 22, 80, 443, and 2222; allow them through any upstream
firewall as needed.

Generate controller secrets for your own appliance using the next section.
The generator preserves an existing inputs file; it does not generate a fresh
identity over another appliance's saved credentials. Keep passwords and TPM PINs
in the protected controller inputs rather than inventory files.

## Controller setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/ansible-galaxy collection install -r requirements.yml -p .ansible/collections
.venv/bin/python scripts/create-controller-secrets.py
```

The secret generator creates `.secrets/infrabox1/inputs.json` once with mode 0600
inside private directories. Existing values are preserved. `.secrets/` is ignored
by Git. Protect these files and never print their contents in logs. Initialization
later writes `.secrets/infrabox1/openbao-init.json`, including the retained root
token and recovery shares. OpenBao Agent receives only its dedicated AppRole.

For a separate fresh deployment, pass `--inventory-hostname <inventory alias>`
to the generator. New files contain infrastructure and central-directory
bootstrap inputs, without application-local administrator passwords. Existing
passwords are preserved; only missing inputs are added. Preserve inputs belonging
to an established appliance; never reuse another appliance's initialization record.

For account creation and first login, follow [Identity and access](identity.md)
after the full bootstrap below.

Verify the VM's SSH host key before deployment. Host key checking remains enabled.
Commands below assume your normal known-hosts file contains the correct key.
If you use a separate known-hosts file, pass its path explicitly, for example:

```sh
--ssh-common-args='-o UserKnownHostsFile=/path/to/known_hosts'
```

## Bootstrap stages

Your local inventory should describe the final TLS state.
For a **new, uninitialized VM only**, use explicit localhost HTTP overrides during
bootstrap. Run each stage and resolve failures before proceeding.

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml verify-foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml openbao-runtime.yml -e @.secrets/infrabox1/inputs.json -e openbao_tls_enabled=false
.venv/bin/ansible-playbook -i inventories/local/hosts.yml pki-bootstrap.yml -e @.secrets/infrabox1/inputs.json -e openbao_bootstrap_initialize=true
.venv/bin/ansible-playbook -i inventories/local/hosts.yml pki-bootstrap.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml certificate-agent.yml -e @.secrets/infrabox1/inputs.json -e openbao_agent_openbao_address=http://127.0.0.1:8200
.venv/bin/ansible-playbook -i inventories/local/hosts.yml host-trust.yml -e @.secrets/infrabox1/inputs.json
```

Repeated provisioning must preserve TPM objects, OpenBao initialization, and CA
keys. The TPM role refuses to create missing seal material over existing OpenBao
data. Select the TPM key size in your local inventory before initialization;
the role default is RSA-4096. There is no automatic key-size or software-unseal
fallback.

**OpenBao HTTP is temporary and localhost-only.** After `certificate-agent.yml`
has verified real Agent authentication, leaf validity, chains and hostnames,
explicitly select the final inventory values, using your internal DNS suffix:

```yaml
openbao_tls_enabled: true
openbao_agent_openbao_address: "https://openbao.{{ infrabox_internal_domain }}:8200"
```

Then apply runtime and Agent configuration:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml openbao-runtime.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml certificate-agent.yml -e @.secrets/infrabox1/inputs.json
```

Do not leave the appliance permanently in bootstrap HTTP mode. No automatic
transport transition or fallback is implemented. The [OpenBao Unix listener](https://openbao.org/docs/configuration/listener/unix/)
is restricted to a private directory and mode 0600 for authenticated local
administration without exposing another TCP endpoint.

## Complete the stack

After the explicit HTTPS transition, deploy the remaining stack, repeat it for
stability, then verify the appliance:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml site.yml -T 60 -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml site.yml -T 60 -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook -i inventories/local/hosts.yml verify.yml -T 60 -e @.secrets/infrabox1/inputs.json
```

`site.yml` applies foundation, PKI recovery, databases, LLDAP, central identity,
the initial application HTTPS routes, applications, optional Platform, OpenClaw,
monitoring and CI, then verifies services and monitoring stabilization. It does
not initialize an empty appliance. A stable repeat should have no unexpected
changes. Stop at a failed stage and diagnose it before proceeding.

Platform is optional and disabled by role default. If enabling it, prepare its
source revision, target trust and configuration through [Platform](platform.md).
Model provider keys are not generated; see [OpenClaw providers](openclaw-providers.md).
Disruptive development acceptance is separate from installation and requires an
authorized test context; see [development](development.md).

## First use

Import `artifacts/<inventory_hostname>/root-ca.crt` into client trust stores,
then open `https://<infrabox_domain>/`. Follow [Identity and access](identity.md)
to create a personal human account in LLDAP and sign into applications. OpenClaw
uses its separate Gateway token and device pairing; see [Gateway setup](openclaw.md).
Check the **InfraBox / InfraBox Health** dashboard in Grafana after monitoring
has collected fresh observations. Preserve controller inputs and recovery material.

For later changes or repair, use [operations](operations.md), not first initialization.

# InfraBox Ansible

InfraBox deploys a single-node AlmaLinux 10 appliance through Ansible and Podman
Quadlet. The implementation contract is [InfraBox_plan.md](InfraBox_plan.md);
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) records the completed
development-VM acceptance checks. The MVP is implemented and verified on the
development host.

For AI-assisted bootstrap and maintenance, see [AGENTS.md](AGENTS.md) for
repository instructions, deployment workflow, and required validation.

SSH key authentication, sudo, SELinux support, and a persistent TPM 2.0
device at `/dev/tpmrm0` are required. Virtual TPM is supported. This README
uses `infrabox.example.com` as an example domain. Production inventory is
intentionally empty.

## Configuration for a local setup

Create a separate inventory for your appliance. The checked-in development
inventory contains deployment-specific values; replace them before use.

```sh
mkdir -p inventories/local/group_vars
cp inventories/development/hosts.yml inventories/local/hosts.yml
cp inventories/development/group_vars/all.yml inventories/local/group_vars/all.yml
export ANSIBLE_INVENTORY="$PWD/inventories/local/hosts.yml"
```

`ANSIBLE_INVENTORY` makes the commands below use your local inventory instead
of the default in `ansible.cfg`. Export it again in a new shell, or pass
`-i inventories/local/hosts.yml` to each Ansible command.

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
update the generator's output directory and the `-e @.secrets/.../inputs.json`
paths below. Initialization records and exported artifacts are stored under
`.secrets/<inventory_hostname>/` and `artifacts/<inventory_hostname>/`.

Review these settings in `inventories/local/group_vars/all.yml`:

| Setting | What to configure |
| --- | --- |
| `infrabox_domain` | Your service base domain, such as `infrabox.example.com`. Configure wildcard DNS for `*.infrabox.example.com`, or individual `git`, `netbox`, `grafana`, and `vault` records, pointing to the appliance. |
| `infrabox_internal_domain` | The private container DNS suffix. The supplied `infrabox.internal` can normally remain; it does not need public DNS records. |
| `openbao_agent_openbao_address` | Match the internal suffix: `https://openbao.<infrabox_internal_domain>:8200`. This is the Agent's internal endpoint, not the public `vault` URL. |
| `openbao_tls_enabled` | Keep `true` for the final configuration. Use the explicit temporary overrides in the bootstrap procedure for a new appliance. |
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
The backend network uses Podman's automatic subnet allocation. The standard
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
python3 scripts/create-controller-secrets.py
```

The secret generator creates `.secrets/infrabox1/inputs.json` once with mode 0600
inside private directories. Existing values are preserved. `.secrets/` is ignored
by Git. Protect these files and never print their contents in logs. Initialization
later writes `.secrets/infrabox1/openbao-init.json`, including the retained root
token and recovery shares. OpenBao Agent receives only its dedicated AppRole.

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
.venv/bin/ansible-playbook foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook verify-foundation.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook openbao-runtime.yml -e @.secrets/infrabox1/inputs.json -e openbao_tls_enabled=false
.venv/bin/ansible-playbook pki-bootstrap.yml -e openbao_bootstrap_initialize=true
.venv/bin/ansible-playbook pki-bootstrap.yml
.venv/bin/ansible-playbook agent.yml -e openbao_agent_openbao_address=http://127.0.0.1:8200
.venv/bin/ansible-playbook host-trust.yml
```

Repeated provisioning must preserve TPM objects, OpenBao initialization, and CA
keys. The TPM role refuses to create missing seal material over existing OpenBao
data. Select the TPM key size in your local inventory before initialization;
the role default is RSA-4096. There is no automatic key-size or software-unseal
fallback.

**OpenBao HTTP is temporary and localhost-only.** After certificate verification,
explicitly select the final inventory values, using your internal DNS suffix:

```yaml
openbao_tls_enabled: true
openbao_agent_openbao_address: "https://openbao.{{ infrabox_internal_domain }}:8200"
```

Then apply runtime and Agent configuration:

```sh
.venv/bin/ansible-playbook openbao-runtime.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook agent.yml
```

Do not leave the appliance permanently in bootstrap HTTP mode. No automatic
transport transition or fallback is implemented. The [OpenBao Unix listener](https://openbao.org/docs/configuration/listener/unix/)
is restricted to a private directory and mode 0600 for authenticated local
administration without exposing another TCP endpoint.

For an established appliance, deploy or repair the full stack with:

```sh
.venv/bin/ansible-playbook site.yml -T 60 -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook verify.yml -T 60 -e @.secrets/infrabox1/inputs.json
```

`site.yml` applies foundation, expiry recovery, PKI, databases, applications,
HTTPS proxy, monitoring, and runner, then verifies the final state. Component
playbooks remain available for targeted changes. No initialization is automatic.

## Services

| Service | Address | Local administrator |
| --- | --- | --- |
| Gitea | https://git.infrabox.example.com | `admin` |
| NetBox | https://netbox.infrabox.example.com | `admin` |
| Grafana | https://grafana.infrabox.example.com | `admin` |
| OpenBao | https://vault.infrabox.example.com | retained controller root token |

Passwords are the corresponding `*_admin_password` entries in the protected
controller inputs. Trust the appliance's public RootCA in clients before using
HTTPS. The CA is `/etc/infrabox/pki/root-ca.crt` on the VM and is exported by
PKI configuration to `artifacts/infrabox1/root-ca.crt` on the controller. It
contains no private key. Gitea SSH uses port 2222. Prometheus is available to Grafana internally;
no dashboards are installed.

The runner label is `infrabox-shell`. Jobs execute in its container with shell
and Git available. This MVP does not provide Node actions or Docker execution.
The runner has its own network and mapped host UID, no runtime socket, and access
to Gitea/NetBox HTTPS. Backend databases, Redis, host management ports, Vault,
and Grafana are blocked. Jobs share this runner's container and persistent work
area; stronger isolation between jobs requires a later execution design.

## Certificate and credential lifecycle

[Agent leased templates](https://openbao.org/docs/agent-and-proxy/agent/template/)
own routine certificate issuance and renewal. Each response produces one
certificate/key/chain generation, validated before publication and reload.
Default leaf lifetime is 14 days. A repeat Ansible run does not restart an
unchanged Agent. Explicit Agent restarts can issue replacement certificates.

Agent SecretIDs have a seven-day lifetime. A native hourly timer checks for daily
rotation using the existing Agent token. The policy permits replacement and
accessor destruction for its own AppRole only, in addition to server certificate
issuance. The replacement login is tested before publication. This timer handles
credentials, not leaf certificate renewal. The development acceptance playbook exercises this rotation and checks that
the old SecretID is rejected.

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

## Local checks

```sh
.venv/bin/ansible-playbook foundation.yml --syntax-check
.venv/bin/ansible-playbook openbao-runtime.yml --syntax-check
.venv/bin/ansible-playbook pki-bootstrap.yml --syntax-check
.venv/bin/ansible-playbook agent.yml --syntax-check
.venv/bin/ansible-playbook services.yml --syntax-check
.venv/bin/python -m unittest discover -s tests
```

## Development acceptance

These tests change the development appliance temporarily. Run them sequentially,
with the controller inputs and verified SSH host-key options used above:

```sh
.venv/bin/ansible-playbook acceptance-applications.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook acceptance-renewal.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook acceptance-recovery.yml -e @.secrets/infrabox1/inputs.json
.venv/bin/ansible-playbook acceptance-reboot.yml -e @.secrets/infrabox1/inputs.json
```

Application acceptance creates and removes a temporary private repository and
SSH key, testing cloning/pushing over both Git transports and an actual Actions job. Renewal testing
uses three-minute certificates and restores 14-day issuance. Recovery testing
briefly stops Agent, lets one-minute leaves and an Agent SecretID expire, and
runs normal Ansible recovery. Expect a short HTTPS outage during that test.
Reboot acceptance verifies TPM auto-unseal, preserved CA identity, and the full
appliance after restart. Completed results and test logs are recorded in
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) and `artifacts/infrabox1/`.

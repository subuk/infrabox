# Deterministic discovery reconciliation (KRG-21)

Platform collects native Ansible facts, optionally observes physical Linux CPU/DIMM
SMBIOS records with `dmidecode --type 4,17` under become, then runs
`scripts/reconcile_netbox.py` on the trusted controller. Collection and reconciliation
have separate per-host outcomes. Optional DMI failure (including unavailable sudo,
missing utility or unsupported target) does not fail ordinary discovery. No utility
is installed on managed hosts. Virtual guests never supply physical module inventory.

## Ownership

| Data | Target and policy |
| --- | --- |
| OS and version | Device/VM Platform, e.g. `AlmaLinux 10.2`; reuse an unambiguous manufacturer-neutral Platform or create one |
| Architecture | `discovery_architecture` custom field on Device/VM |
| System serial | Device/VM `serial`, when a non-placeholder value is observed |
| VM CPU/RAM | Native `vcpus` and `memory`; RAM is OS-visible MiB, not guaranteed hypervisor allocation |
| VM disks | Native VirtualDisk by exact observed block-device name; update size only, preserving owner/tags/description |
| Interfaces | Match exact name within the selected Device/VM; create missing interface; no inferred purpose, speed, physical connector or administrative state |
| MAC | Create an unambiguous MAC association and set primary MAC; conflicting ownership is a warning |
| IP | Use observed address/prefix and explicit interface VRF; an existing global IP establishes global scope; otherwise warn rather than infer VRF. Never transfer another object's address or set primary IP |
| Physical CPU/DIMM | ModuleBay by observed socket/locator; ModuleType by manufacturer/model with fixed CPU/RAM profiles; Module instance with observed serial |
| Physical disks | Module with `Discovery Disk` profile, exact capacity in bytes and observed rotational flag; model and stable WWN/serial required |
| Provenance | `discovery_last_success`, `discovery_source`, `discovery_run`, `discovery_revision` |

Discovery can replace previously manually entered values of its owned fields.
It preserves site/location, tenant, role, owner, user tags, intent, Config Context,
primary/management IP, device type, cluster and other fields outside this table.
Missing observations do not clear values or delete objects. A different installed
module type/serial is reported as a replacement proposal, without silently retiring
an existing asset. Shared module type conflicts are warnings; the reconciler does
not rewrite a catalog type used by other devices. Unknown optional attributes stay
unknown. CPU count alone does not manufacture per-socket components.

Interface names matching `cilium_*` or `lxc*` are excluded from reconciliation,
including their MAC/IP observations; raw facts retain them for debugging. Override
`PLATFORM_INTERFACE_EXCLUDE_PATTERNS` in Gitea repository variables with comma-separated,
case-sensitive shell globs. An empty repository value uses the defaults; `,` disables
exclusions. Other virtual interfaces are retained. The filter never deletes existing
NetBox objects; any initial cleanup remains an explicitly authorized operation.

Disks use existing Linux `ansible_devices` facts. Whole sd/hd/vd/xvd, NVMe and MMC
devices are supported. Nested partitions, loop/zram, device-mapper/LVM, software RAID
and optical devices are not separate assets. Equal WWN/serial observations are
deduplicated; conflicting identities warn and are skipped. NVMe requires a namespace
WWN/EUI/UUID because controller serial alone cannot distinguish namespaces.
Unidentified physical devices are skipped. An absent vendor uses the explicitly
generic manufacturer with a warning, without guessing from the model string.

Disk module bays use stable identity-derived names, not inferred chassis slots.
`discovery_disk_identity` stores the WWN or serial identity on the module. A serial
field is filled only from an observed serial. VirtualDisk size uses decimal MB,
rounded up by less than 1 MB, matching the current `DISK_BASE_UNIT=1000` NetBox
configuration; a change to that setting requires a matching conversion change.
VM disk names are OS observations, not hypervisor backing-file identities.

PCI passthrough does not move or delete physical inventory automatically. A VM gets
the disks visible to its OS, even when backed by passed-through hardware; discovery
does not infer the physical host, slot or host/guest link. A disk no longer visible
to the host leaves its previous module untouched. PCI-controller inventory and
hypervisor-assisted correlation are outside this disk extension.

The reconciler checks current ID, exact name, managed tag and name uniqueness
across Device/VM before writing. Every update contains only an explicit diff.
A failed API request can leave earlier operations applied: the report retains
those changes, other hosts continue, and the failed host gets no new success
provenance. A retry converges without deletion/rollback. The runner executes one
job at a time; this is not a cross-client transaction or distributed lock.

A fresh successful collection refreshes provenance even if infrastructure is
unchanged. Such refreshes do not count as `changed`. Reprocessing the same run
and facts produces no writes when the stored data already matches.

## Credentials and authorization

The existing independent `svc-platform` service identity keeps its native LDAP
reader membership. Its dedicated authorization envelope adds only required
model-level add/change permissions, without delete or semantic catalog writes.
The token becomes write-enabled through native provisioning and stays in
`kv/platform/netbox`, delivered through the existing trusted OpenBao path.
The old token is retired only after replacement verification. Healthy reruns
preserve the token. TLS and RootCA validation remain required.

NetBox model permissions do not enforce individual writable fields. Field ownership
is enforced in the trusted Python reconciler; a compromised trusted runner with
Device change authority could modify other Device fields. No administrator token,
credential in artifacts, host runtime socket or generic model-controlled execution
is introduced. Provisioning owns custom-field and module-profile schemas; the
runner cannot edit these schemas. Human readers and OpenClaw can read module data.

## Results, retention and monitoring

`reconciliation-<run>-<attempt>` contains only `reconciliation-summary.json`, schema
version 2. It records collection/reconciliation outcomes, changed objects/fields,
provenance-only changes, warnings/errors and selected/collected/reconciled/changed/
unchanged/warning/failed/unreachable counts. Counts overlap: an API failure after
some successful writes can count the host as both changed and failed.

Per operator decision, `discovery-<run>-<attempt>` remains a separate debugging
artifact containing the native collection manifest, Markdown summary, filtered
Ansible facts and optional DMI records. Both artifacts retain the current seven-day
Gitea retention setting and repository access controls. Consult the artifact's
published expiry time: live validation observed a six-day timestamp interval despite
the seven-day workflow setting. Environment/local/facter/ohai fact
families remain excluded. Job-local files are removed after publication.
This deliberately supersedes the issue's original debug-only publication proposal.

OpenClaw's fixed result tool reads only the compact artifact and exposes paginated
host statuses or per-host changes/warnings/errors. It cannot fetch native facts or
JSON pointers. Read current state through NetBox after a run. Existing saved request
IDs retain dispatch deduplication; old runs lacking the new artifact are unavailable
through this result interface and must be inspected by an operator in Gitea.

Runner-local `/data/discovery-health.json` survives recreation and records run start,
completion/publication outcome, last successful reconciliation, failed/unreachable
hosts and reconciliation/API/auth failures. Monitoring reads this bounded state
without dispatching discovery or invoking models and exports `infrabox_discovery_*`
metrics into the existing health catalog. No completed run yet means unavailable
observations, not a proven healthy discovery. A running job exceeding 25 minutes
is unhealthy; no scheduled-discovery freshness threshold is introduced.

## Validation

Use the focused Platform reconciliation tests and directly relevant Gateway,
credential/configuration and syntax checks. Do not run broad regression or rebuild
an appliance for this feature. Authorized live validation uses only existing
NetBox managed hosts `testbox` (virtual guest) and `slava` (physical) on the development
appliance. Both currently have Device records; discovery reports the guest/type
mismatch and does not migrate it. Testing native VM CPU/RAM live requires a
separately approved Device-to-VM migration; normalization and updates have unit coverage.
Check initial enrichment, repeated facts/no-op writes, retained operator metadata,
compact result consumption, raw artifact retention and optional DMI behavior.
Record actual results in IMPLEMENTATION_STATUS; schema/unit checks alone do not
establish live success or conversational model behavior.

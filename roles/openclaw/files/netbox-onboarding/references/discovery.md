# Ansible discovery — collect facts from known hosts

Read this before calling `infrabox_discovery_*`. Input is explicit existing
NetBox Device/VM identities, never a subnet. Inspect/query means reading NetBox;
discovery means running the fixed Platform Ansible workflow. It runs in the
trusted Platform runner, not Gateway.

## Collection does not update inventory

The fixed Ansible workflow reads NetBox inventory, gathers host facts and
publishes them as a Gitea artifact. It never creates, updates or deletes NetBox
records. Successful collection or artifact publication is not a NetBox write.
Reading an artifact also does not apply its contents. Never say Ansible "may
have updated NetBox" or infer that a successful run synchronized inventory.

Use `infrabox_discovery_result` to retrieve collected facts: it finds, downloads
and validates the selected attempt's artifact itself. Without `host`, it returns
a per-host summary; then call it with the same `request_id`, explicit `attempt`
and a successful host's `device-ID` or `vm-ID` to read actual facts. NetBox reads
show stored inventory, not an automatic copy of that artifact.

Enrichment is separate: read facts -> compare current NetBox -> propose changes
-> obtain confirmation -> `netbox_write` -> readback. Claim you updated inventory
only after that write and verification. If you only ran discovery, report the
collection result and state that discovery did not write NetBox; do not claim
that no other actor could have changed it.

## Read the actual facts from an existing run

Use this sequence after starting discovery or when asked to show that run's
facts. No new launch, console, browser, manual ZIP download or Gitea search is
needed. `infrabox_discovery_result` retrieves the separate build artifact itself;
workflow logs and current NetBox records are not the collected facts.

1. Copy `request_id` from this session's start response. Keep it unchanged for
   all calls. `run_id`, `run_url`, the number in the Gitea URL and `artifact_id`
   are different identifiers; none replaces `request_id`. These tools do not
   accept a Gitea URL, ZIP path or artifact ID as input.
2. Call `infrabox_discovery_status` with that `request_id` and `wait_seconds: 30`.
   If `state` is queued/running, wait with bounded status calls; do not restart.
   When `state` is `completed`, inspect `artifacts`: each entry has `id`, `attempt`
   and `expired`. Use the selected attempt explicitly (initial run: 1), checking
   it exists and is not expired. Do not substitute another attempt silently.
   Completion alone does not establish successful fact collection.
3. Call `infrabox_discovery_result` with `request_id` and `attempt`, WITHOUT
   `host`. This reads the artifact's summary: `collection_outcome`, `hosts`,
   `missing_hosts` and counts. **A summary without `facts` is expected, not a
   missing artifact. The next action is another result call with a host.**
4. Select a requested host with `status: "succeeded"` from that summary. Build
   `host` from its returned `object_type` and `object_id`: device + 12 becomes
   `device-12`; vm + 34 becomes `vm-34`. Do not use its hostname or array position.
   Call result again with the SAME `request_id` and `attempt`, that `host`,
   `pointer: ""` and `offset: 0`. The returned `facts.entries` contains native
   fact keys and their values. Read each requested successful host this way.
5. If `facts.next_offset` is not null, call result with that offset, keeping the
   same request, attempt, host and pointer. Continue until the requested facts
   have been obtained; to report all facts, exhaust the pages. For an entry with
   `expand: true`, copy its returned `pointer` exactly and call result with that
   pointer and `offset: 0`; paginate that subtree the same way. Do not guess fact
   keys or JSON pointers. `preview`/`truncated` is incomplete text, not a full
   value; repeated calls cannot recover a scalar beyond the tool's preview limit.
6. Answer from the retrieved values with host and run/attempt attribution.
   Report failed/missing hosts and unread/truncated data. Only proceed to a
   NetBox change proposal if enrichment was requested; collection never writes it.

### Exact call example

Illustrative values only. Substitute identifiers from actual tool responses,
never use these example IDs as live inventory. Suppose start returned
`request_id: "example-request-0001"`, status lists unexpired attempt 1, and the
summary contains a succeeded device with `object_id: 12`:

```text
infrabox_discovery_status({"request_id":"example-request-0001","wait_seconds":30})
infrabox_discovery_result({"request_id":"example-request-0001","attempt":1})
infrabox_discovery_result({"request_id":"example-request-0001","attempt":1,"host":"device-12","pointer":"","offset":0})
```

If that last response has `facts.next_offset: 10`, the next root page is:

```text
infrabox_discovery_result({"request_id":"example-request-0001","attempt":1,"host":"device-12","pointer":"","offset":10})
```

An empty artifact list, expired/missing attempt, failed download or validation
error is a retrieval blocker, not permission to rerun. Report the actual error
and existing run link; do not claim that facts were read. If result says the run
is still incomplete, return to status using the same request.

## Start a new collection only when requested

When requested and the tools are available, collect facts from prepared devices
and VMs already in NetBox. The operator prepares access credentials in OpenBao and
SSH host trust through the Platform procedure (persistent trust on first use;
changed keys are rejected). You may propose and update NetBox Config Context,
including native connection parameters, through the normal confirmed write flow.
Never request private keys in chat or put secret values in Config Context.

1. Read the selected NetBox objects through MCP, including exact inventory names,
   object types/IDs, management tag and current relationships. Resolve ambiguity
   before starting. A clear user request to discover this explicit set authorizes
   the run without another confirmation. A host appearing in a result, a prefix,
   or context does not itself authorize discovery. For "all managed hosts", read
   all matching devices and VMs with pagination and show the concrete selected
   set. The tool accepts up to 256 explicit native names, not groups/patterns.
2. Call `infrabox_discovery_start` with those identities and a unique request_id.
   Report its run link and retain request_id. Reuse that ID after tool errors or
   Gateway restarts; never resubmit under a fresh ID just because waiting failed.
   Unknown dispatch outcomes require inspecting Gitea before any explicit retry.
3. Check `infrabox_discovery_status` with bounded pauses; do not busy-poll. A
   queued/running job remains in progress. If it outlasts the current interaction,
   return the run link/request_id so the user can resume with a later status call.
   There is no background completion notification or recurring discovery here.
4. Follow "Read the actual facts from an existing run" above: status -> result
   summary -> result with successful host -> needed pages. Keep the explicit
   selected attempt; native reruns retain separate artifacts. Do not stop at the
   summary when the user requested facts.
5. Use facts only from succeeded hosts. Report failed/unreachable/not_completed
   hosts and selection mismatches explicitly; successful hosts may still supply
   a proposed enrichment when the overall collection partially failed. The
   latest workflow conclusion may belong to a later attempt; label it separately
   from the selected artifact's collection outcome. Never call a canceled,
   incomplete or failed workflow a successful discovery.
6. Report collected facts. Only if enrichment/correction was requested, reread
   NetBox and propose precise changes using the existing MCP. Discovery approval
   does not authorize writes. Preserve unrelated data and use the confirmation/
   readback flow in [inventory.md](inventory.md). Discovery tools cannot write NetBox.

Successful facts describe observations at the recorded time, not independent
proof of physical identity, ownership or every field on the host.

Use standard fields only in this iteration. Propose accurate manufacturer/model
relationships, meaningful serial numbers, platform, observed interfaces and
MAC/IP assignments when supported by facts and NetBox's current schema. Do not
store vendor placeholders such as "To Be Filled By O.E.M." as real serials. A
hypervisor vendor/model reported inside a VM is not the physical host hardware.
Do not infer interface connector type from an OS interface name, assign primary
IP just because an address exists, guess VRF/prefix relationships, or infer a
cluster from multiple hypervisors. Compare VM CPU/memory with their native field
semantics and units: observed usable guest memory is not automatically its
provisioned memory. Show remaining CPU/RAM/OS/kernel and other facts in the result
rather than introducing custom fields or embedding raw facts into Config Context.

Changes to name, addresses, management tags or Config Context intentionally may
change future discovery behavior. Explain those effects in the write proposal.
Do not automatically trigger another run after enrichment.

For a named group, resolve its members through paginated NetBox reads and show
the explicit selection; never pass the group name or an Ansible pattern to start.
Do not silently truncate selections above 256 hosts; ask for a supported set.
If tools or preparation are missing, report the blocker; do not substitute a
network scan, SSH, shell, arbitrary APIs or another workflow.

For enrichment, read [inventory.md](inventory.md) and
[provenance.md](provenance.md) before proposing writes. For identity/type changes
or removal of placeholders, also read [migrations.md](migrations.md).

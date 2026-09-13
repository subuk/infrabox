# OpenClaw discovery and NetBox enrichment (KRG-9)

OpenClaw can run the fixed Platform discovery workflow, read native Ansible facts
and propose corrections to NetBox. The Platform playbook, Ansible pattern input,
runner, credentials and fact schema are unchanged. NetBox remains the source of
inventory; Gitea retains the source run and native result artifacts.

## Operator workflow

1. Prepare the managed Device/VM in NetBox with its connection parameters and
   `infrabox-managed` tag. The operator supplies SSH credentials in OpenBao and
   verified host keys through the existing [Platform procedure](platform.md).
   OpenClaw can propose confirmed Config Context edits, including local context.
2. Ask OpenClaw to discover the selected hosts. An explicit request for an
   unambiguous set is enough; there is no second launch confirmation.
3. OpenClaw reads NetBox and sends exact names and Device/VM IDs to
   `infrabox_discovery_start`. The plugin verifies their current names and tag,
   and passes a comma-separated name list as the existing workflow's `targets`.
   Neither workflow/ref/URL nor arbitrary Ansible options are tool inputs.
4. The response contains `request_id`, Gitea run ID and run URL. Use
   `infrabox_discovery_status` to wait up to 30 seconds per call or to resume after
   Gateway restart. A completed run is read with `infrabox_discovery_result`.
5. Review the proposed NetBox changes and source attribution. All writes,
   including deletion and Device-to-VM migration, require a separate concrete
   confirmed proposal and use the existing NetBox MCP integration.

The tool accepts 1–256 prepared hosts with ordinary native inventory names
(letters, numbers, underscores, dots and hyphens; no pattern metacharacters).
For "all managed hosts", OpenClaw reads the complete eligible list with NetBox
pagination and submits the explicit names. Empty input never selects all. The
underlying Gitea UI continues to accept ordinary Ansible patterns. Ambiguous
names across sites or devices/VMs are rejected before dispatch. The fixed
inventory group namespaces (`site_`, `platform_`, `role_`, `tag_`, `is_virtual`,
`all`, `ungrouped`) are not accepted as hostnames to avoid group/host collisions.

`infrabox_discovery_result` first returns a per-host summary. Select `device-ID`
or `vm-ID` to read native facts; follow JSON pointers and `next_offset` for
bounded pages. Large fields are marked as previews or expandable values rather
than silently passed off as complete. Each result carries run/attempt, SHA and
timestamp. No normalized facts schema or automatic NetBox writeback is added.

Ansible observations do not prove every aspect of host identity or configuration.
Only successful hosts provide enrichment. Failed/unreachable/unfinished hosts,
missing selections and publication failures remain visible. A successful host's
facts may still be proposed when another host failed. OS guesses from Nmap,
public vendor specifications, user statements and actual Ansible observations
retain separate provenance.

Use supported standard NetBox fields, with schema/relationship checks. Other
facts remain visible as results, without new custom fields. CPU/memory facts
need semantic and unit checks before proposing VM allocations. Placeholder
interfaces and incorrectly classified Device/VM records may be corrected,
including confirmed reassignment/deletion after replacement readback. Context,
names, tags and address changes can intentionally affect the next discovery.

## Configuration and lifecycle

`openclaw_discovery_enabled` follows `platform_enabled` by default. It requires
NetBox integration and an already provisioned Platform repository. `site.yml`
provisions Platform before OpenClaw; for component deployment run the existing
`automation.yml` before `agent.yml` when Platform is not yet installed.

| Setting | Default |
| --- | --- |
| `openclaw_discovery_username` | `infrabox-openclaw-discovery` |
| `openclaw_discovery_gitea_url` | Platform Gitea URL |
| `openclaw_discovery_organization` | `infrabox-platform` |
| `openclaw_discovery_repository` | `automation` |
| `openclaw_discovery_branch` | `master` |
| `openclaw_discovery_managed_tag` | `infrabox-managed` |

The dedicated Gitea account belongs to the managed `OpenClawDiscovery` team:
Code Read / Actions Write on this repository only. It receives a token with
`read:user` and `write:repository` scopes; effective code permissions remain
read-only. Gitea Actions Write includes broader Actions operations at the API
level; the model's only interface is the three fixed tools, which expose no
workflow edits, cancellation, artifact deletion or arbitrary requests. Account
administration and runner/provisioner credentials are not available to Gateway.

OpenBao owns `kv/openclaw/integrations/discovery`, field `apiToken`, plus ownership
and token-ID metadata. Runtime delivery uses
`/etc/infrabox/openclaw/secrets/discovery-token` (UID/GID 1000, mode 0600), mounted
read-only at `/run/openclaw-secrets/discovery-token`. The token does not appear in
Gateway configuration, environment, tool arguments or conversations. The plugin
reads the file for each request, so atomic replacement needs no credential-cache
restart. Healthy reruns preserve it. Invalid tokens are replaced and validated
before publication; superseded integration tokens are retired only after
Gateway-side verification. Rerun `agent.yml` to repair credentials.

Disabling discovery removes its tools/configuration from Gateway and keeps the
identity, credentials and saved request history for re-enablement. It does not
cancel already running Platform jobs or delete their artifacts.

## Persistence, errors and retention

Requests are private JSON records under `/srv/infrabox/openclaw/state/discovery`,
outside the workspace-readable tree. A unique request_id is reserved before any
POST. Reusing that ID returns the existing run; reusing it for different hosts
fails. A dispatch timeout/process crash can leave `dispatch_unknown` (or an
unfinished preparation record). These requests never automatically redispatch:
inspect the retained Gitea Actions history before explicitly deciding to retry
under a new ID. No distributed exactly-once guarantee is claimed for an HTTP
request whose response was lost. Completed request records are retained; they
contain selection/run metadata, not raw facts or credentials.

Gateway restarts preserve request IDs. Waiting is bounded and can be resumed in
a later conversation; there is no unsolicited background completion notification,
discovery scheduler, recurring monitor or canary.

An initial run uses attempt 1. Native Gitea reruns retain separate
`discovery-<run-id>-<attempt>` artifacts. The plugin selects an explicit attempt,
verifies manifest/run/SHA/selection/counts and validates a bounded ZIP in memory,
without filesystem extraction. Gitea's REST `run_attempt` is not used as truth;
the pinned server has reported zero despite real attempt 1/2 artifacts.
The latest workflow conclusion may describe a different attempt from the one
being read and is labeled separately from collection outcome.

Only the configured Gitea origin and exact signed artifact download endpoint may
receive download redirects. TLS uses the existing private RootCA; no verification
bypass exists. Network/authentication errors do not trigger token replacement or
new discovery runs from inside Gateway.

Facts artifacts have Platform's limited retention. Missing/expired artifacts are
reported without rerunning. Confirmed NetBox changes include compact provenance
(time, run/attempt, URL, SHA, affected fields) in supported description/comments
fields, preserving operator text and avoiding duplicate notes on repeated writes.

## Verification and acceptance

Core syntax/unit tests, plugin tests (`node --test tests/*.mjs`), actual Gateway
plugin registration, Gitea identity/permission checks and verified HTTPS reads
are part of deployment verification. These do not dispatch discovery or mutate
inventory. Automatic inference/conversational acceptance is not performed.

Run the following only with a prepared, explicitly authorized target; use the
selected appliance inventory and protected controller inputs. Store non-secret
acceptance parameters in a local JSON file:

```json
{
  "openclaw_discovery_acceptance_request_id": "acceptance-unique-001",
  "openclaw_discovery_acceptance_hosts": [
    {"name": "server01.example.com", "object_type": "device", "object_id": 12}
  ]
}
```

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml acceptance-openclaw-discovery.yml \
  -e @.secrets/infrabox1/inputs.json -e @/path/to/acceptance-parameters.json
```

This dispatches the fixed workflow through the registered plugin tools, checks
request deduplication, waits for completion and validates the downloaded native
facts for exactly one host. It saves a bounded report with the actual run URL
under `artifacts/<inventory_hostname>/krg9/`. Reuse the same request ID after a
controller interruption to inspect the original request rather than creating a
new run. It makes no model calls and does not write/delete inventory. Real
conversational proposals, confirmed writes and migrations remain operator
acceptance; report their status separately from tool/transport checks.

For explicitly authorized Gateway restart acceptance, also set
`openclaw_discovery_acceptance_restart_gateway=true`. The playbook restarts only
Gateway, resumes the same request through its actual tools and requires the same
run, artifact and SHA. It saves a separate `-restart.json` report. No managed host
or appliance reboot is involved; no new workflow is dispatched for that request.
The post-restart check only calls status/result, so missing persistence fails
without creating a replacement run. For a standalone read-only replay, set
`openclaw_discovery_acceptance_resume_only=true` with the existing request ID.

# OpenClaw discovery and pipeline reconciliation (KRG-21)

[Documentation index](README.md) · [Ownership contract](discovery-reconciliation.md)

An explicit request for selected prepared managed hosts authorizes the fixed
Platform workflow, including deterministic writes of discovery-owned NetBox data.
OpenClaw reads current NetBox state after completion and explains unresolved warnings.
Manual semantic edits, deletions and migrations still need a confirmed proposal.

1. Read NetBox and select exact managed Device/VM names and IDs.
2. Call `infrabox_discovery_start` with a persistent request_id and explicit hosts.
3. Poll `infrabox_discovery_status`; preserve the same request_id across restarts.
4. Read `infrabox_discovery_result` with an explicit available attempt. It returns
   a compact host summary. Use `offset`/`next_offset` for all hosts or select
   `host: device-ID` / `vm-ID` for paginated changes, warnings and errors.
5. Read NetBox for resulting state. Collection success alone is not write success.

The result tool only downloads `reconciliation-<run>-<attempt>`. Native facts and
DMI records remain in the separate `discovery-<run>-<attempt>` Gitea artifact for
operator debugging, with seven-day retention. No facts/pointer tool interface or
LLM-based routine reconciliation remains. Historical requests retain their IDs,
but old artifacts require manual Gitea inspection; never redispatch just to read.

## Configuration and lifecycle

`openclaw_discovery_enabled` follows `platform_enabled` by default. It requires
NetBox integration and an already provisioned Platform repository. `site.yml`
provisions Platform before OpenClaw; for component deployment run the existing
`automation.yml` before `agent.yml` when Platform is not yet installed.

| Setting | Default |
| --- | --- |
| `openclaw_discovery_username` | `svc-openclaw` |
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
`reconciliation-<run-id>-<attempt>` compact artifacts and separate raw debugging
artifacts. The plugin selects an explicit attempt,
verifies manifest/run/SHA/selection/counts and validates a bounded ZIP in memory,
without filesystem extraction. Gitea's REST `run_attempt` is not used as truth;
the pinned server has reported zero despite real attempt 1/2 artifacts.
The latest workflow conclusion may describe a different attempt from the one
being read and is labeled separately from collection outcome.

Only the configured Gitea origin and exact signed artifact download endpoint may
receive download redirects. TLS uses the existing private RootCA; no verification
bypass exists. Network/authentication errors do not trigger token replacement or
new discovery runs from inside Gateway.

Both artifacts have Platform's seven-day retention. Missing/expired compact
artifacts are reported without rerunning. Pipeline provenance is stored in the
fixed NetBox discovery custom fields; operator comments/descriptions are preserved.

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
request deduplication, waits for completion and validates the downloaded compact
reconciliation report for one or two explicitly selected hosts. It saves a bounded report with the actual run URL
under `artifacts/<inventory_hostname>/krg9/`. Reuse the same request ID after a
controller interruption to inspect the original request rather than creating a
new run. It makes no model calls. The dispatched workflow writes discovery-owned inventory
fields, so authorize the selected target for enrichment. Real
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

# OpenClaw service or integration failure

Gateway liveness, native diagnostics, Vault resolution and NetBox MCP access are
independent checks. A healthy NetBox plus failed MCP authentication normally
points to the integration identity/token path. A stopped Gateway must remain
visible in Grafana; no conversation is needed to detect it.

Check Gateway unit/readiness and the fixed runtime probe. For NetBox inspect the
five permitted tools and run the owning NetBox credential verification without
printing token values. For Vault verify the restricted periodic token's expiry
and native renewal unit. Do not use the certificate Agent's AppRole or root token
for OpenClaw. Provider requests are not made by baseline health checks.

Restore configuration with `agent.yml`; replacement credentials must work before
superseded credentials are retired. Require new observations after restart.
Tool/schema/permission failures need their targeted tests even after health is
otherwise green. Conversational approval behavior remains separate acceptance.

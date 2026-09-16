# OpenClaw model providers

[Documentation index](README.md) · [Gateway setup](openclaw.md)

The Gateway starts without provider credentials. InfraBox does not provision
model keys or enable production integrations. An operator can store an API key in
KV v2 at `kv/openclaw/providers/<provider>` with a string field named `apiKey`,
then configure an appropriate provider using a reference such as:

```yaml
openclaw_model_providers:
  example:
    baseUrl: https://api.example.com/v1
    api: openai-completions
    models: [] # Supply the model definitions required by your provider.
    apiKey:
      source: exec
      provider: vault
      id: openclaw/providers/example/apiKey
```

The SecretRef ID omits the mount name and KV v2 `/data/` API segment. Resolved keys
are runtime values; configuration retains references. See the official
[Vault plugin guide](https://docs.openclaw.ai/plugins/vault) and
[container documentation](https://docs.openclaw.ai/install/docker).

## Example: OpenAI API key in OpenBao

This example uses the default `kv` mount and an OpenAI Platform API key. The
OpenAI key is separate from both the Gateway login token and OpenClaw's OpenBao
service token.

First, open `https://vault.infrabox.example.com` (substitute your service domain)
and sign in with a personal account holding `infrabox:openbao:admin`, which
permits KV administration. The retained controller root token is reserved for
infrastructure management; never use it as a provider or runtime credential.
In **Secrets**, open the **kv** engine, create a secret at
`openclaw/providers/openai`, and add a string field named **apiKey** whose value
is your OpenAI API key. Save it before deploying the provider configuration.

| Item | Value with the default mount |
| --- | --- |
| KV engine | `kv` (version 2) |
| Secret path inside the engine | `openclaw/providers/openai` |
| Field containing the OpenAI API key | `apiKey` |
| OpenBao API path | `kv/data/openclaw/providers/openai` |
| OpenClaw SecretRef ID | `openclaw/providers/openai/apiKey` |

Add this to `inventories/local/group_vars/all.yml`, merging it with any existing
`openclaw_model_providers` entries:

```yaml
openclaw_model_providers:
  openai:
    baseUrl: https://api.openai.com/v1
    api: openai-responses
    models:
      - id: gpt-6-astra
        name: GPT-6 Astra
        reasoning: true
        input: [text, image]
        contextWindow: 1050000
        maxTokens: 128000
    apiKey:
      source: exec
      provider: vault
      id: openclaw/providers/openai/apiKey
```

`api: openai-responses` selects OpenAI's Responses API protocol. The `baseUrl`
points directly to OpenAI, and `models[].id` selects the actual hosted model.
`openai-completions` is the Chat Completions adapter, not a model name or a mock
provider. This example uses Responses for direct OpenAI access.

`gpt-6-astra` is the existing repository example recorded on 2026-09-12,
not a promise of current model availability. Your
OpenAI API project must have access to it. When selecting another model, update
its capabilities and limits as well as its ID. The inventory contains only a
reference, never the key. If you changed `openclaw_openbao_kv_mount`, use that
engine in OpenBao; the SecretRef ID still omits the mount and `/data/` segment.

Model entries were checked against the
[OpenClaw 2026.9.4 configuration schema](https://github.com/openclaw/openclaw/blob/v2026.9.4/src/config/zod-schema.core.ts).
Only `id` and `name` are required within each explicitly configured model entry;
the other fields below are optional. The recorded example gives model capabilities
and limits; confirm them for your account against the [official model specifications](https://developers.openai.com/api/docs/models/gpt-6-astra).

| Model entry field | Meaning |
| --- | --- |
| `id` | Provider model ID, such as `gpt-6-astra`; omit the `openai/` prefix here. |
| `name` | Display label in OpenClaw. |
| `reasoning` | Whether the model supports reasoning/thinking controls; `true` for GPT-6 Astra. |
| `input` | Supported input types. GPT-6 Astra accepts `text` and `image`; declare only capabilities the selected model supports. |
| `contextWindow` | Native context limit in tokens. |
| `contextTokens` | Optional smaller runtime context budget for session budgeting and compaction. |
| `maxTokens` | Maximum output token budget, separate from the context window. |
| `cost` | Optional USD-per-million-token accounting fields: `input`, `output`, `cacheRead`, `cacheWrite`, and optional `tieredPricing`. These describe costs; they do not enforce a spending limit. |
| `api`, `baseUrl` | Optional per-model overrides of the provider's adapter and endpoint. |
| `params`, `compat`, `thinkingLevelMap` | Advanced request parameters, adapter compatibility, and reasoning-level mapping; use only settings supported by the selected provider/model. |

The schema also accepts `agentRuntime`, `headers`, `mediaInput`, and
`metadataSource`; these are not needed for this example. Keep credentials in the
Vault SecretRef, including when considering custom headers. Do not copy model
limits or reasoning flags to a different model without checking its specifications.

In InfraBox, `openclaw_model_providers` becomes `models.providers` in OpenClaw's
JSON configuration. Each provider's `models` value is a list of model objects,
not a list of model-name strings. Top-level `models.mode` (`merge` or `replace`)
and `agents.defaults.model.primary` are separate OpenClaw settings; the current
Ansible role does not expose variables for them. Use session model selection
below; listing models here does not configure a default or an access allowlist.

Apply the configuration from the controller:

```sh
.venv/bin/ansible-playbook -i inventories/local/hosts.yml agent.yml -e @.secrets/infrabox1/inputs.json
```

Open `https://claw.infrabox.example.com`, authenticate with the Gateway token,
and select `openai/gpt-6-astra` for the chat session using the model picker or
`/model openai/gpt-6-astra`. Send a short message to verify an actual provider call.
Adding a provider alone does not set the agent's default model. Keep configuration
changes in Ansible because the deployed `openclaw.json` is read-only.

To rotate the OpenAI key, update the same OpenBao secret's `apiKey` field and
run `sudo systemctl restart openclaw` on the appliance to resolve the new value.
A healthy Ansible rerun may make no changes and does not itself guarantee a
secret reload. The OpenBao service token does not need replacement for this
rotation. See OpenClaw's [OpenAI provider guide](https://docs.openclaw.ai/providers/openai)
and [model selection guide](https://docs.openclaw.ai/concepts/models).

## Local Ollama on the LAN

Merge an `ollama` entry into `openclaw_model_providers` alongside existing
providers. Following the [OpenClaw Ollama documentation](https://docs.openclaw.ai/providers/ollama/configuration),
use the native endpoint without `/v1` and the non-secret `ollama-local` marker
for an unauthenticated LAN server. Real credentials still require Vault SecretRefs.
The role enables the bundled Ollama plugin when this provider is configured.

```yaml
openclaw_model_providers:
  ollama:
    baseUrl: http://192.0.2.10:11434
    api: ollama
    apiKey: ollama-local
    models:
      - id: qwen3.5:9b
        name: Qwen 3.5 9B
        reasoning: true
        input: [text, image]
        contextWindow: 262144
        maxTokens: 8192
```

Replace the example address and model with your server's values. Check `/api/tags`
and `/api/show` from the Gateway container before configuring model capabilities.
The context value describes model metadata, not a verified server memory budget;
`maxTokens: 8192` is an output budget. Add the server address to `openclaw_no_proxy`
while preserving its existing entries if outbound proxies are configured.

Apply `agent.yml` with the selected inventory and existing protected inputs as
above, then repeat it to check stability. Configuration changes restart the
Gateway. Select `/model ollama/qwen3.5:9b` in a session; adding this provider does
not change the default model or configure fallback. Native OpenAI hosted web
search does not become available through Ollama automatically.

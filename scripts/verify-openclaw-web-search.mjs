// Run inside the pinned Gateway after readiness. No model or search request is sent.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createOpenAINativeWebSearchWrapper} from '/app/dist/extensions/openai/native-web-search.js';
import {t as resolveWebSearchToolPolicy} from '/app/dist/web-search-tool-policy-6zib_RzU.mjs';

globalThis.fetch = () => { throw Error('Network requests are forbidden in this verification'); };
const config = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH, 'utf8'));
assert.equal(config.tools.web.search.enabled, true);
assert.equal(config.tools.web.search.provider, undefined);
assert.ok(config.plugins.allow.includes('openai'));
assert.equal(config.plugins.entries.openai.enabled, true);

function policy(cfg, model) {
  return resolveWebSearchToolPolicy({config: cfg, agentId: 'main',
    modelProvider: model.provider, modelId: model.id,
    webSearchEnabled: cfg.tools.web.search.enabled}).allowed;
}
function payloadFor(cfg, model, allowed) {
  const payload = {tools: [{type: 'function', name: 'netbox_read'},
    {type: 'function', name: 'web_search'}]};
  const capture = (_model, _context, options) => { options?.onPayload?.(payload); return payload; };
  return createOpenAINativeWebSearchWrapper(capture,
    {config: cfg, agentId: 'main', nativeWebSearchAllowedByToolPolicy: allowed})(model, {}, {});
}

let checked = 0;
const provider = config.models?.providers?.openai;
for (const entry of provider?.models ?? []) {
  const model = {id: entry.id, provider: 'openai', api: entry.api ?? provider.api,
    baseUrl: entry.baseUrl ?? provider.baseUrl};
  if (model.api !== 'openai-responses' || (model.baseUrl && !/^https:\/\/api\.openai\.com(?:\/v1)?\/?$/.test(model.baseUrl))) continue;
  assert.equal(policy(config, model), true, 'effective profile blocks web search');
  const payload = payloadFor(config, model, true);
  assert.equal(payload.tools.filter(t => t.type === 'web_search').length, 1);
  assert.ok(!payload.tools.some(t => t.type === 'function' && t.name === 'web_search'));
  assert.ok(payload.tools.some(t => t.name === 'netbox_read'));
  const disabled = structuredClone(config);
  disabled.tools.web.search.enabled = false;
  assert.equal(policy(disabled, model), false);
  assert.ok(!payloadFor(disabled, model, true).tools.some(t => t.type === 'web_search'));
  const unlisted = structuredClone(config);
  unlisted.tools.alsoAllow = unlisted.tools.alsoAllow.filter(t => t !== 'web_search');
  assert.equal(policy(unlisted, model), false, 'base profile unexpectedly grants search');
  const denied = structuredClone(config);
  denied.tools.deny.push('web_search');
  assert.equal(policy(denied, model), false);
  assert.ok(!payloadFor(config, model, false).tools.some(t => t.type === 'web_search'));
  assert.ok(!payloadFor(config, {...model, baseUrl: 'https://proxy.example.com/v1'}, true).tools.some(t => t.type === 'web_search'));
  checked++;
}
console.log(checked ? `Native OpenAI search payload and effective tool policy verified for ${checked} configured models` :
  'Web search configuration enabled; no direct OpenAI Responses models configured, so native payload checks were skipped');
console.log('No model inference, search request, or inventory mutation performed');

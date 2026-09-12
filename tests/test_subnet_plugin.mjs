import assert from 'node:assert/strict';
import {test} from 'node:test';
import plugin, {TOOL, validateTarget} from '../roles/openclaw/files/subnet-scan/index.mjs';

test('strict single IPv4 target without address allowlist', () => {
  for (const subnet of ['192.0.2.0/24', '192.0.2.128/25', '8.8.8.8/32']) assert.equal(validateTarget({subnet}), subnet);
  for (const subnet of ['192.0.2.0/23', '192.0.2.1/24', '::/120', 'example.com/24', '192.0.2.0/24 -A', '192.0.2.1/32/extra', '192.0.2.1/32\n']) {
    assert.throws(() => validateTarget({subnet}));
  }
  assert.throws(() => validateTarget({subnet: '192.0.2.1/32', approved: true}));
});

test('native approval covers exact target and requires ownership, with no persistent approval', () => {
  let hook, tool, options;
  plugin.register({on(name, fn) {assert.equal(name, 'before_tool_call'); hook = fn;}, registerTool(t, o) {tool=t; options=o;}});
  assert.equal(options.optional, true);
  assert.equal(tool.name, TOOL);
  assert.equal(hook({toolName: 'netbox_read'}), undefined);
  assert.equal(hook({toolName: TOOL, params: {subnet: '192.0.2.0/23'}}).block, true);
  const approval = hook({toolName: TOOL, params: {subnet: '192.0.2.0/24'}}).requireApproval;
  assert.deepEqual(approval.allowedDecisions, ['allow-once', 'deny']);
  assert.match(approval.description, /192\.0\.2\.0\/24/);
  assert.match(approval.description, /your own local network/);
  assert.match(approval.description, /active probes/);
  assert.match(approval.description, /OS guesses may be wrong/);
  assert.ok(approval.description.length <= 512);
});

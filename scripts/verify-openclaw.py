#!/usr/bin/env python3
"""Read-only checks; report no credentials or complete container metadata."""
import json
from pathlib import Path
import subprocess
import sys

port, config_dir, storage_dir, ca_path, period = sys.argv[1:]

def run(*args):
    return subprocess.check_output(args, text=True)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

for unit in ['openclaw.service', 'openclaw-token-renew.timer']:
    require(run('systemctl', 'is-active', unit).strip() == 'active', unit + ' inactive')
require(run('systemctl', 'is-enabled', 'openclaw-token-renew.timer').strip() == 'enabled', 'renewal timer disabled')
require(run('systemctl', 'show', 'openclaw-token-renew.timer', '-p', 'NextElapseUSecRealtime', '--value').strip(), 'renewal timer unscheduled')
container = json.loads(run('podman', 'inspect', 'openclaw'))[0]
require(container['Config']['User'] == '1000:1000', 'unexpected image UID/GID')
require(not container['HostConfig']['Privileged'], 'privileged container')
require(not container['HostConfig'].get('Devices'), 'host devices exposed')
require(not container.get('EffectiveCaps'), 'container capabilities enabled')
require(container['HostConfig']['Memory'] > 0, 'container memory limit missing')
require(container['HostConfig']['PidsLimit'] > 0, 'container PID limit missing')
require(container['HostConfig']['NanoCpus'] > 0, 'container CPU limit missing')
require('no-new-privileges' in container['HostConfig']['SecurityOpt'], 'no-new-privileges absent')
ports = container['NetworkSettings']['Ports']
require(ports[str(port) + '/tcp'] == [{'HostIp': '127.0.0.1', 'HostPort': str(port)}], 'Gateway exposed beyond loopback')
allowed = {config_dir + '/openclaw.json', config_dir + '/secrets', storage_dir + '/state', storage_dir + '/workspace', ca_path}
require({m['Source'] for m in container['Mounts']} == allowed, 'unexpected container mount')
for mount in container['Mounts']:
    if mount['Source'] in {config_dir + '/openclaw.json', config_dir + '/secrets', ca_path}:
        require(not mount['RW'], 'credential/configuration/CA mount is writable')
for name in ['openclaw.json', 'openclaw.env', 'secrets/vault-token']:
    require(Path(config_dir, name).stat().st_mode & 0o077 == 0, 'world/group-readable configuration or secret')
configuration = json.loads(Path(config_dir, 'openclaw.json').read_text())
require(configuration['gateway']['auth']['mode'] == 'token', 'Gateway token auth disabled')
require(configuration['gateway']['terminal']['enabled'] is False, 'Gateway terminal enabled')
require(configuration['agents']['defaults']['sandbox']['mode'] == 'off', 'nested sandbox enabled')
require(configuration['plugins']['entries']['vault']['enabled'] is True, 'bundled Vault plugin disabled')
require(not configuration['gateway']['tls']['enabled'], 'unexpected Gateway TLS server')
env = dict(item.split('=', 1) for item in container['Config']['Env'] if '=' in item)
require('VAULT_TOKEN' not in env and 'BAO_TOKEN' not in env, 'OpenBao token present in environment')
require(env.get('OPENCLAW_VAULT_AUTH_METHOD') == 'token_file', 'incorrect Vault auth method')
require('NODE_TLS_REJECT_UNAUTHORIZED' not in env, 'TLS verification bypass')
require(env.get('NODE_EXTRA_CA_CERTS') == '/run/infrabox-ca/root-ca.crt', 'Node RootCA missing')
# Node validates the actual peer names with the same trust environment as the Gateway.
node = r'''
const fs = require('node:fs');
(async () => {
  const token = fs.readFileSync(process.env.VAULT_TOKEN_FILE, 'utf8').trim();
  const r = await fetch(process.env.VAULT_ADDR + '/v1/auth/token/lookup-self', {headers: {'X-Vault-Token': token}});
  if (!r.ok) throw Error('OpenBao token lookup rejected');
  const d = (await r.json()).data;
  if (!d.renewable || !d.orphan || d.type !== 'service' || d.policies.length !== 1 ||
      d.policies[0] !== 'infrabox-openclaw' || d.period !== Number(process.argv[1]) ||
      d.explicit_max_ttl !== 0 || d.ttl <= 0) throw Error('Token contract mismatch');
  const publicResponse = await fetch('https://example.com', {signal: AbortSignal.timeout(15000)});
  if (!publicResponse.ok) throw Error('Public HTTPS trust failed');
  console.log('OpenBao token contract and private/public TLS trust verified');
})().catch(e => {console.error('Node TLS/token verification failed:', e.message, e.cause?.code || ''); process.exit(1)});
'''
print(run('podman', 'exec', 'openclaw', 'node', '-e', node, period).strip())
print('OpenClaw isolation, permissions, limits, and renewal timer verified')

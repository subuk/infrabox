#!/usr/bin/env python3
"""Read-only scanner checks: no packets sent and no model inference."""
import json
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


require(run('systemctl', 'is-active', 'infrabox-scanner.service').strip() == 'active', 'scanner inactive')
container = json.loads(run('podman', 'inspect', 'infrabox-scanner'))[0]
host = container['HostConfig']
require(container['Config']['User'] == '0:1000', 'unexpected scanner identity')
require(set(container.get('EffectiveCaps', [])) == {'CAP_NET_RAW'}, 'unexpected scanner capabilities')
require(not host['Privileged'] and not host.get('Devices'), 'scanner host privilege/device access')
require(host['ReadonlyRootfs'], 'scanner root filesystem is writable')
require('no-new-privileges' in host['SecurityOpt'], 'scanner no-new-privileges absent')
require('label=disable' not in host['SecurityOpt'], 'scanner SELinux labeling disabled')
environment_names = {value.split('=', 1)[0] for value in container['Config']['Env']}
require(not environment_names.intersection({'VAULT_TOKEN', 'BAO_TOKEN', 'NETBOX_TOKEN', 'OPENCLAW_GATEWAY_TOKEN', 'VAULT_TOKEN_FILE'}), 'application credentials exposed to scanner')
require(host['Memory'] > 0 and host['NanoCpus'] > 0 and host['PidsLimit'] > 0, 'scanner limits absent')
require(not any(container['NetworkSettings']['Ports'].values()), 'scanner publishes network ports')
require(set(container['NetworkSettings']['Networks']) == {'infrabox-scanner'}, 'scanner network isolation incorrect')
binds = [m for m in container['Mounts'] if m['Type'] == 'bind']
require(len(binds) == 1 and binds[0]['Source'] == '/run/infrabox-scanner' and binds[0]['Destination'] == '/run/infrabox-scanner', 'unexpected scanner bind mount')
require('Nmap version 7.93' in run('podman', 'exec', 'infrabox-scanner', '/usr/bin/nmap', '--version'), 'unexpected Nmap version')
runtime = json.loads(run('podman', 'exec', 'openclaw', 'node', 'openclaw.mjs',
                         'plugins', 'inspect', 'infrabox-subnet-scan', '--runtime', '--json'))
require(runtime['plugin']['status'] == 'loaded', 'native scanner plugin did not load')
require(runtime['plugin']['toolNames'] == ['infrabox_scan_subnet'], 'unexpected scanner tool registration')
require(runtime['typedHooks'] == [{'name': 'before_tool_call'}], 'native approval hook missing')
require(runtime['tools'] == [{'names': ['infrabox_scan_subnet'], 'optional': True}], 'scanner tool is not optional')
require(not runtime['diagnostics'], 'scanner plugin diagnostics reported errors')
node = r'''
const {request} = await import('/opt/infrabox/plugins/subnet-scan/index.mjs');
const health = await request('/health');
if (health.service !== 'infrabox-subnet-scanner' || health.max_addresses !== 256) throw Error('Scanner health mismatch');
for (const subnet of ['192.0.2.0/23', '::/120', '192.0.2.0/24 -A']) {
  let rejected = false;
  try { await request('/scan', {subnet}); } catch (e) { rejected = /canonical IPv4 CIDR/.test(e.message); }
  if (!rejected) throw Error('Scanner target validation failed');
}
console.log('Gateway socket access and invalid-target rejection verified; no scan executed');
'''
print(run('podman', 'exec', 'openclaw', 'node', '--input-type=module', '-e', node).strip())
print('Scanner image, isolation, raw capability, and resource limits verified')
print('Native scanner tool and before_tool_call approval hook loaded without diagnostics')

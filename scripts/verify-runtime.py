#!/usr/bin/python3
"""Read-only final-state checks; never output container environments or secrets."""
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

domain = sys.argv[1]
claw_hostname = sys.argv[2] if len(sys.argv) > 2 else "claw." + domain
def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

for unit in ['openbao', 'openbao-agent', 'postgresql', 'redis', 'gitea', 'netbox',
             'netbox-worker', 'nginx', 'prometheus', 'grafana', 'gitea-runner',
             'openbao-agent-secret-id.timer', 'infrabox-runner-firewall']:
    run(['systemctl', 'is-active', unit])
for name in ['openbao', 'postgresql', 'redis', 'nginx']:
    base = '/etc/infrabox/pki/' + name + '/'
    public = run(['openssl', 'x509', '-in', base + 'server.crt', '-pubkey', '-noout'])
    assert public == run(['openssl', 'pkey', '-in', base + 'server.key', '-pubout']), name + ' key mismatch'
    if name == 'nginx':
        for service in ['git', 'netbox', 'vault', 'grafana', 'claw']:
            run(['openssl', 'x509', '-in', base + 'server.crt', '-noout', '-checkhost', claw_hostname if service == 'claw' else service + '.' + domain])
assert 'tls_disable = true' not in Path('/etc/infrabox/openbao/config.hcl').read_text().split('listener "unix"')[0]
try:
    with urlopen('http://127.0.0.1:8200/v1/sys/health', timeout=10) as response:
        raise AssertionError('OpenBao accepted a plaintext TCP health request')
except HTTPError as error:
    assert error.code == 400, 'Unexpected plaintext listener response'
nginx = run(['nginx', '-T'])
assert 'proxy_ssl_verify on;' in nginx
runner = json.loads(run(['podman', 'inspect', 'gitea-runner']))[0]
assert set(runner['NetworkSettings']['Networks']) == {'infrabox-runner'}
assert all('sock' not in m['Destination'] for m in runner['Mounts'])
assert int(run(['podman', 'exec', 'gitea-runner', 'cat', '/proc/self/uid_map']).split()[1]) != 0
for name, port in [('postgresql', 5432), ('redis', 6379)]:
    info = json.loads(run(['podman', 'inspect', name]))[0]
    assert not info['HostConfig']['PortBindings'], name + ' publishes a host port'
    address = info['NetworkSettings']['Networks']['infrabox']['IPAddress']
    result = subprocess.run(['podman', 'exec', 'gitea-runner', 'timeout', '3', 'nc', '-w', '2', address, str(port)],
                            input='', capture_output=True, text=True)
    assert result.returncode in [1, 124, 143], name + ' network isolation failed'
for service, suffix in [('git', '/api/healthz'), ('netbox', '/login/')]:
    run(['podman', 'exec', 'gitea-runner', 'wget', '-q', '-O', '/dev/null', '-T', '10', 'https://' + service + '.' + domain + suffix])
for service in ['vault', 'grafana', 'claw']:
    result = subprocess.run(['podman', 'exec', 'gitea-runner', 'wget', '-S', '-O', '/dev/null', '-T', '10', 'https://' + (claw_hostname if service == 'claw' else service + '.' + domain)], capture_output=True, text=True)
    assert result.returncode != 0 and '403 Forbidden' in result.stderr, service + ' runner restriction failed'
print('Certificate keys/SANs, active services, verified nginx upstream, and runner isolation passed.')

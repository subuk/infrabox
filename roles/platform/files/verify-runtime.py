#!/usr/bin/env python3
"""Read-only Platform isolation checks; never output credentials or container env."""
import json
import subprocess
import sys


def command(args, input=None):
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Platform runtime check failed')
    return result.stdout


def verify(c):
    metadata = json.loads(command(['podman', 'inspect', 'platform-runner', '--format',
        '{"networks":{{json .NetworkSettings.Networks}},"mounts":{{json .Mounts}},"privileged":{{json .HostConfig.Privileged}},"label":{{json .ProcessLabel}}}']))
    assert set(metadata['networks']) == {'infrabox-platform'}, 'Unexpected runner network'
    assert not metadata['privileged'], 'Privileged runner'
    assert ':container_t:' in metadata['label'], 'Runner lacks container SELinux confinement'
    assert all('sock' not in m['Destination'] for m in metadata['mounts']), 'Runtime socket mounted'
    assert int(command(['podman', 'exec', 'platform-runner', 'cat', '/proc/self/uid_map']).split()[1]) != 0, 'Host root mapping'
    for name, port in [('postgresql', 5432), ('redis', 6379)]:
        address = command(['podman', 'inspect', name, '--format',
            '{{(index .NetworkSettings.Networks "infrabox").IPAddress}}']).strip()
        c.setdefault('blocked', []).append([address, port])
    backend = json.loads(command(['podman', 'network', 'inspect', 'infrabox']))[0]
    for subnet in backend['subnets']:
        for port in (22, 8200, 9100):
            c['blocked'].append([subnet['gateway'], port])
    code = '''import json,os,socket,ssl,sys
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler,ProxyHandler
from urllib.error import HTTPError
c=json.load(sys.stdin)
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert status['NoNewPrivs'].strip()=='1' and int(status['CapEff'].strip(),16)==0
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args): raise RuntimeError('Unexpected redirect')
opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=os.environ['SSL_CERT_FILE'])))
for url,expected in [(c['gitea_url']+'/api/healthz',200),(c['netbox_url']+'/login/',200),(c['bao_url']+'/v1/sys/health',200),(c['grafana_url'],403),(c['openclaw_url'],403)]:
 try:
  with opener.open(url,timeout=10) as response: actual=response.status
 except HTTPError as error: actual=error.code
 assert actual==expected
sys.path.insert(0,'/opt/platform/scripts')
from discover import bao,DiscoveryError
mount=os.environ['PLATFORM_KV_MOUNT']
token=bao(mount+'/data/platform/netbox')['token']
with opener.open(Request(c['netbox_url']+'/api/dcim/devices/?limit=1',headers={'Authorization':'Bearer '+token}),timeout=10) as response:
 assert 'results' in json.load(response)
try:
 bao(mount+'/data/core/platform/gitea')
except DiscoveryError as error:
 assert str(error)=='openbao_http_403'
else: raise RuntimeError('Platform token can read Core credentials')
for address,port in c['blocked']:
 try:
  connection=socket.create_connection((address,port),timeout=2)
 except OSError: continue
 connection.close()
 raise RuntimeError('Restricted backend or management port reachable')
'''
    command(['podman', 'exec', '-i', 'platform-runner', 'python3', '-c', code], json.dumps(c))
    print('Platform HTTPS, scoped credentials, SELinux, UID/capabilities, network and socket isolation passed.')


if __name__ == '__main__':
    try:
        verify(json.load(sys.stdin))
    except Exception as error:
        print('Platform verification failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)

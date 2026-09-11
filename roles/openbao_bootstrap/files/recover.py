#!/usr/bin/env python3
"""Repair expired leaf certificates via authenticated local management."""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

os.umask(0o077)
c = json.load(sys.stdin)
config = json.loads(Path('/etc/infrabox/openbao-agent/certificates.json').read_text())
class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(c['socket'])
changed = False
for spec in config['certificates']:
    leaf = Path(config['root']) / spec['name'] / 'server.crt'
    if not leaf.exists():
        raise RuntimeError('Required leaf certificate missing: ' + spec['name'])
    check = subprocess.run(['openssl', 'x509', '-in', str(leaf), '-noout', '-checkend', '0'], capture_output=True)
    if check.returncode == 0:
        continue
    # Do not interpret malformed certificates as expiration.
    subprocess.run(['openssl', 'x509', '-in', str(leaf), '-noout'], check=True, capture_output=True)
    payload = {'common_name': spec['common_name'], 'alt_names': ','.join(spec.get('alt_names', [])),
               'ttl': c['ttl']}
    h = Connection('localhost', timeout=30)
    h.request('POST', '/v1/pki-server/issue/infrabox-server', json.dumps(payload),
              {'X-Vault-Token': c['token'], 'Content-Type': 'application/json'})
    response = h.getresponse(); body = response.read(); h.close()
    if response.status != 200:
        raise RuntimeError('Certificate recovery issuance failed with status ' + str(response.status))
    data = json.loads(body)['data']
    dest = Path('/etc/infrabox/openbao-agent/rendered') / (spec['name'] + '.json')
    temporary = dest.with_suffix('.new')
    temporary.write_text(json.dumps(data)); temporary.chmod(0o600); os.replace(temporary, dest)
    subprocess.run(['python3', '/etc/infrabox/openbao-agent/render.py', spec['name']], check=True, capture_output=True)
    changed = True
print(json.dumps({'changed': changed}))

#!/usr/bin/python3
"""Development fault injection: rotation, then expired leaves and SecretID."""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

os.umask(0o077)
config = json.load(sys.stdin)
class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect('/run/infrabox-openbao/api.sock')
def api(path, data):
    connection = Connection('localhost', timeout=30)
    connection.request('POST', '/v1/' + path, json.dumps(data), {'X-Vault-Token': config['token'], 'Content-Type': 'application/json'})
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, json.loads(body) if body else {}
def checked(path, data):
    status, result = api(path, data)
    assert status in [200, 204], 'Test API failed: ' + path
    return result
def run(args):
    subprocess.run(args, check=True, capture_output=True)

auth = Path('/etc/infrabox/openbao-agent/auth')
role = 'auth/approle/role/infrabox-openbao-agent'
state = Path('/run/infrabox-expired-secret-id.json')
if len(sys.argv) > 1 and sys.argv[1] == 'verify':
    expired = json.loads(state.read_text())
    status, _ = api('auth/approle/login', {'role_id': (auth / 'role-id').read_text().strip(), 'secret_id': expired['secret_id']})
    assert status in [400, 403], 'Repaired SecretID still authenticates with the old value'
    login = checked('auth/approle/login', {'role_id': (auth / 'role-id').read_text().strip(), 'secret_id': (auth / 'secret-id').read_text().strip()})
    checked('auth/token/revoke', {'token': login['auth']['client_token']})
    state.unlink()
    print('Expired SecretID revoked; repaired SecretID authenticates.')
    raise SystemExit(0)
old = (auth / 'secret-id').read_text().strip()
aged = time.time() - 90000
os.utime(auth / 'secret-id', (aged, aged))
run(['systemctl', 'start', 'openbao-agent-secret-id.service'])
assert (auth / 'secret-id').read_text().strip() != old
assert api('auth/approle/login', {'role_id': (auth / 'role-id').read_text().strip(), 'secret_id': old})[0] in [400, 403], 'Old SecretID still authenticates after rotation'
print('Restricted-token SecretID rotation passed; old SecretID revoked.', flush=True)
run(['systemctl', 'stop', 'openbao-agent-secret-id.timer', 'openbao-agent.service'])
fresh = checked(role + '/secret-id', {'ttl': '60s'})['data']
assert fresh['secret_id_ttl'] == 60
expires = time.time() + 60
state.write_text(json.dumps({'secret_id': fresh['secret_id']}))
old_accessor = (auth / 'secret-id-accessor').read_text().strip()
for name, value in [('secret-id', fresh['secret_id']), ('secret-id-accessor', fresh['secret_id_accessor'])]:
    (auth / name).write_text(value + '\n')
checked(role + '/secret-id-accessor/destroy', {'secret_id_accessor': old_accessor})
registry = json.loads(Path('/etc/infrabox/openbao-agent/certificates.json').read_text())
for spec in registry['certificates']:
    leaf = checked('pki-server/issue/infrabox-server', {'common_name': spec['common_name'],
                   'alt_names': ','.join(spec.get('alt_names', [])), 'ttl': '60s'})['data']
    Path('/etc/infrabox/openbao-agent/rendered', spec['name'] + '.json').write_text(json.dumps(leaf))
    run(['python3', '/etc/infrabox/openbao-agent/render.py', spec['name']])
time.sleep(65)
for spec in registry['certificates']:
    result = subprocess.run(['openssl', 'x509', '-in', registry['root'] + '/' + spec['name'] + '/server.crt', '-noout', '-checkend', '0'], capture_output=True)
    assert result.returncode == 1
assert time.time() > expires
print('All ' + str(len(registry['certificates'])) + ' leaf certificates and the replacement SecretID have expired.', flush=True)

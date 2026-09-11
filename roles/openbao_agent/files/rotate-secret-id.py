#!/usr/bin/env python3
"""Rotate only this Agent's SecretID using its existing, restricted token."""
import json
import os
from pathlib import Path
import ssl
import time
from urllib.request import Request, urlopen

os.umask(0o077)
base = Path('/etc/infrabox/openbao-agent/auth')
config = json.loads(Path('/etc/infrabox/openbao-agent/rotation.json').read_text())
if time.time() - (base / 'secret-id').stat().st_mtime < config['rotate_after_seconds']:
    raise SystemExit(0)
token = Path('/run/infrabox-openbao-agent/token').read_text().strip()
context = ssl.create_default_context(cafile=config['ca_file'])

def api(path, data, credential=token):
    request = Request(config['address'] + '/v1/' + path, json.dumps(data).encode(),
                      {'X-Vault-Token': credential, 'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, context=context, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else {}

role = 'auth/approle/role/infrabox-openbao-agent'
fresh = api(role + '/secret-id', {})['data']
# Check replacement authentication before publishing it. Revoke only the test token.
test_token = api('auth/approle/login', {'role_id': (base / 'role-id').read_text().strip(),
                                     'secret_id': fresh['secret_id']}, credential='')['auth']['client_token']
api('auth/token/revoke-self', {}, credential=test_token)
old_accessor = (base / 'secret-id-accessor').read_text().strip()
for name, value in [('secret-id', fresh['secret_id']), ('secret-id-accessor', fresh['secret_id_accessor'])]:
    temporary = base / (name + '.new')
    temporary.write_text(value + '\n')
    temporary.chmod(0o600)
    os.replace(temporary, base / name)
api(role + '/secret-id-accessor/destroy', {'secret_id_accessor': old_accessor})
print('Agent SecretID replaced; previous SecretID revoked.')

#!/usr/bin/env python3
"""Idempotent PKI bootstrap over the host-only Unix listener."""
import http.client
import json
from pathlib import Path
import socket
import sys

c = json.load(sys.stdin)
changed = False
class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(c['socket'])
def api(method, path, data=None, missing=False, raw=False):
    h = Connection('localhost', timeout=30)
    h.request(method, '/v1/' + path, json.dumps(data) if data is not None else None,
              {'X-Vault-Token': c['token'], 'Content-Type': 'application/json'})
    r = h.getresponse()
    body = r.read()
    h.close()
    if missing and r.status == 404:
        return None
    if r.status >= 300:
        raise RuntimeError('OpenBao API failed: ' + method + ' ' + path + ' status=' + str(r.status))
    if raw:
        return body.decode()
    return json.loads(body) if body else {}
def write(path, data):
    global changed
    result = api('POST', path, data)
    changed = True
    return result
mounts = api('GET', 'sys/mounts')['data']
for mount in ['pki-root', 'pki-server', 'pki-user']:
    if mount + '/' not in mounts:
        write('sys/mounts/' + mount, {'type': 'pki', 'config': {'max_lease_ttl': c['root_ttl'] if mount == 'pki-root' else c['intermediate_ttl']}})
    elif mounts[mount + '/']['type'] != 'pki':
        raise RuntimeError('Existing mount has wrong engine type: ' + mount)
root_ca = api('GET', 'pki-root/ca/pem', missing=True, raw=True)
if not root_ca:
    write('pki-root/root/generate/internal', {'common_name': 'InfraBox RootCA', 'ttl': c['root_ttl'], 'key_type': 'rsa', 'key_bits': 4096, 'max_path_length': 1})
    root_ca = api('GET', 'pki-root/ca/pem', raw=True)
for mount, name, path_length in [('pki-server', 'ServerCA', 0), ('pki-user', 'UserCA', 0)]:
    cert = api('GET', mount + '/ca/pem', missing=True, raw=True)
    if not cert:
        csr = write(mount + '/intermediate/generate/internal', {'common_name': 'InfraBox ' + name, 'key_type': 'rsa', 'key_bits': 4096})['data']['csr']
        signed = write('pki-root/root/sign-intermediate', {'csr': csr, 'common_name': 'InfraBox ' + name, 'ttl': c['intermediate_ttl'], 'format': 'pem_bundle', 'max_path_length': path_length})['data']['certificate']
        write(mount + '/intermediate/set-signed', {'certificate': signed})
# Numeric TTLs compare cleanly with the API's canonical representation.
def seconds(value):
    return int(value[:-1]) * {'h': 3600, 'm': 60, 's': 1}[value[-1]] if isinstance(value, str) and value[-1].isalpha() else int(value)
server = {'allowed_domains': [c['domain'], c['internal_domain']], 'allow_subdomains': True,
          'allow_bare_domains': True, 'allow_ip_sans': False, 'server_flag': True, 'client_flag': False,
          'key_type': 'rsa', 'key_bits': 2048, 'ttl': seconds(c['server_ttl']),
          'max_ttl': seconds(c['server_ttl']), 'generate_lease': True}
user = {'allow_any_name': True, 'server_flag': False, 'client_flag': True,
        'key_type': 'rsa', 'key_bits': 2048, 'ttl': 3600, 'max_ttl': 86400}
for path, spec in [('pki-server/roles/infrabox-server', server), ('pki-user/roles/infrabox-user', user)]:
    current = api('GET', path, missing=True)
    if current is None or any(current['data'].get(k) != v for k,v in spec.items()):
        write(path, spec)
auth = api('GET', 'sys/auth')['data']
if 'approle/' not in auth:
    write('sys/auth/approle', {'type': 'approle'})
elif auth['approle/']['type'] != 'approle':
    raise RuntimeError('Unexpected existing auth method at approle/')
policy = 'path "pki-server/issue/infrabox-server" { capabilities = ["update"] }\npath "pki-server/ca/pem" { capabilities = ["read"] }\npath "pki-server/cert/ca_chain" { capabilities = ["read"] }\npath "auth/approle/role/infrabox-openbao-agent/secret-id" { capabilities = ["update"] }\npath "auth/approle/role/infrabox-openbao-agent/secret-id-accessor/destroy" { capabilities = ["update"] }\n'
policy_path = 'sys/policies/acl/infrabox-openbao-agent'
current = api('GET', policy_path, missing=True)
if current is None or current['data']['policy'] != policy:
    write(policy_path, {'policy': policy})
role_path = 'auth/approle/role/infrabox-openbao-agent'
role_spec = {'token_policies': ['infrabox-openbao-agent'], 'token_period': 3600,
             'secret_id_ttl': int(c['secret_id_ttl']), 'secret_id_num_uses': 0,
             'token_no_default_policy': False, 'bind_secret_id': True}
current = api('GET', role_path, missing=True)
if current is None or any(current['data'].get(k) != v for k,v in role_spec.items()):
    write(role_path, role_spec)
print(json.dumps({'changed': changed, 'root_ca': root_ca}))

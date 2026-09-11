#!/usr/bin/env python3
import http.client
import json
import os
from pathlib import Path
import socket
import sys
from datetime import datetime, timezone

c=json.load(sys.stdin)
os.umask(0o077)
class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.connect(c['socket'])
def api(method,path,data=None,missing=False):
    conn=Connection('localhost',timeout=30)
    conn.request(method,'/v1/'+path,json.dumps(data) if data is not None else None,
                 {'X-Vault-Token':c['token'],'Content-Type':'application/json'})
    r=conn.getresponse();body=r.read();conn.close()
    if missing and r.status in [400,404]: return None
    if r.status>=300: raise RuntimeError('Credential API failed: '+path+' '+str(r.status))
    return json.loads(body) if body else {}
base=Path('/etc/infrabox/openbao-agent/auth')
role='auth/approle/role/infrabox-openbao-agent'
role_id=api('GET',role+'/role-id')['data']['role_id']
changed=False
def save(name,value):
    path=base/name
    tmp=base/(name+'.new')
    tmp.write_text(value+'\n');tmp.chmod(0o600);os.replace(tmp,path)
if not (base/'role-id').exists() or (base/'role-id').read_text().strip()!=role_id:
    save('role-id',role_id);changed=True
current=None
if (base/'secret-id').exists():
    current=api('POST',role+'/secret-id/lookup',{'secret_id':(base/'secret-id').read_text().strip()},missing=True)
if current is not None:
    metadata = current.get('data') or {}
    expiration = metadata.get('expiration_time')
    # AppRole expiry cleanup is asynchronous; a successful lookup is not proof
    # that the SecretID is still within its lifetime.
    if not expiration or datetime.fromisoformat(expiration.replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        api('POST', role+'/secret-id/destroy', {'secret_id': (base/'secret-id').read_text().strip()})
        current = None
    elif not (base/'secret-id-accessor').exists() or (base/'secret-id-accessor').read_text().strip() != metadata['secret_id_accessor']:
        save('secret-id-accessor', metadata['secret_id_accessor']); changed=True
if current is None:
    fresh=api('POST',role+'/secret-id',{})['data']
    save('secret-id',fresh['secret_id'])
    save('secret-id-accessor',fresh['secret_id_accessor'])
    changed=True
# Failed retries with an expired credential can lock this RoleID. Repair only
# this Agent's lockout after validating/replacing its credential; retain the
# mount's lockout policy and leave every other identity untouched.
mount_accessor = api('GET', 'sys/auth')['data']['approle/']['accessor']
locked = api('GET', 'sys/locked-users').get('data') or {}
for namespace in locked.get('by_namespace') or []:
    if namespace.get('namespace_path') != '':
        continue
    for mount in namespace.get('mount_accessors') or []:
        if mount['mount_accessor'] == mount_accessor and role_id in (mount.get('alias_identifiers') or []):
            api('POST', 'sys/locked-users/' + mount_accessor + '/unlock/' + role_id, {})
            changed=True
print(json.dumps({'changed':changed}))

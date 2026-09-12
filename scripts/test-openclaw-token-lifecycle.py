#!/usr/bin/env python3
"""Disposable lifecycle checks. State contains only a digest and token accessor."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

c = json.load(sys.stdin)
class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(c['socket'])
def api(path, data=None, token=None, expected=200):
    h = Connection('localhost', timeout=30)
    try:
        h.request('GET' if data is None else 'POST', '/v1/' + path,
                  json.dumps(data) if data is not None else None,
                  {'X-Vault-Token': token if token is not None else c['root_token'],
                   'Content-Type': 'application/json'})
        response = h.getresponse()
        body = response.read()
        assert response.status == expected, f'{path}: expected {expected}, got {response.status}'
        return json.loads(body) if body else {}
    finally:
        h.close()
def invocation():
    return subprocess.check_output(['systemctl', 'show', 'openclaw', '-p', 'InvocationID', '--value'], text=True).strip()
path = Path(c['config_dir'], 'secrets/vault-token')
state = Path(c['config_dir'], 'lifecycle-test.json')
digest = hashlib.sha256(path.read_bytes()).hexdigest()
if c['action'] in ['capture', 'revoke', 'expire']:
    assert not state.exists(), 'An earlier lifecycle fixture needs review'
    token = path.read_text().strip()
    data = api('auth/token/lookup-self', token=token)['data']
    assert data['policies'] == ['infrabox-openclaw'], 'Refusing to revoke an unrelated token'
    if c['action'] == 'expire':
        # A real short-lived periodic token exercises expiry without a week-long wait.
        previous = data['accessor']
        fixture = api('auth/token/create-orphan', {
            'policies': ['infrabox-openclaw'], 'no_default_policy': True,
            'period': '5s', 'renewable': True, 'display_name': 'infrabox-expiry-acceptance',
        })['auth']
        token = fixture['client_token']
        data = api('auth/token/lookup-self', token=token)['data']
        assert data['orphan'] and data['renewable'] and data['period'] == 5
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.expiry-test-')
        try:
            owner = path.stat()
            os.fchown(fd, owner.st_uid, owner.st_gid)
            with os.fdopen(fd, 'w') as stream:
                stream.write(token + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        api('auth/token/revoke-accessor', {'accessor': previous}, expected=204)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with os.fdopen(os.open(state, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump({'digest': digest, 'accessor': data['accessor'], 'invocation': invocation()}, stream)
    if c['action'] in ['revoke', 'expire']:
        if c['action'] == 'revoke':
            api('auth/token/revoke-accessor', {'accessor': data['accessor']}, expected=204)
        else:
            time.sleep(7)
            api('auth/token/lookup-self', token=token, expected=403)
        result = subprocess.run(['systemctl', 'start', 'openclaw-token-renew.service'], capture_output=True)
        assert result.returncode != 0, 'Revoked-token renewal unexpectedly succeeded'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'Renewer modified a revoked token'
        assert invocation() == json.loads(state.read_text())['invocation'], 'Renewer restarted Gateway'
        print(c['action'] + ': renewal failed visibly without changing the file or restarting Gateway')
    else:
        print('Recorded token identity before changing its desired period')
elif c['action'] == 'verify':
    before = json.loads(state.read_text())
    assert digest != before['digest'], 'Ansible did not replace the token'
    assert invocation() != before['invocation'], 'Gateway was not restarted after replacement'
    api('auth/token/lookup-accessor', {'accessor': before['accessor']}, expected=400)
    data = api('auth/token/lookup-self', token=path.read_text().strip())['data']
    assert data['policies'] == ['infrabox-openclaw'] and data['period'] == c['period'], 'Replacement contract mismatch'
    assert not Path(c['config_dir'], 'superseded-token-accessor').exists(), 'Token finalization did not complete'
    assert not Path(c['config_dir'], 'restart-required').exists(), 'Gateway restart was not finalized'
    state.unlink()
    print('Ansible replaced the token, restarted Gateway, and retired the old identity')
else:
    raise RuntimeError('Unknown lifecycle action')

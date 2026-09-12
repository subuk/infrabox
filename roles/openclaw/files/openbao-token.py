#!/usr/bin/env python3
"""Restricted controller-driven management; root credential arrives only on stdin."""
import http.client
import json
import os
from pathlib import Path
import socket
import secrets
import subprocess
import sys
import tempfile

class APIError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'OpenBao management request failed (HTTP {status})')

def seconds(value):
    return int(value[:-1]) * {'h': 3600, 'm': 60, 's': 1}[value[-1]] if str(value)[-1].isalpha() else int(value)

def matches(data, period):
    return (data.get('renewable') is True and data.get('orphan') is True
            and data.get('type') == 'service'
            and set(data.get('policies', [])) == {'infrabox-openclaw'}
            and data.get('period') == period
            and data.get('explicit_max_ttl', 0) == 0 and data.get('ttl', 0) > 0)

def atomic(path, value, uid=None, gid=None):
    fd, name = tempfile.mkstemp(prefix='.openclaw-', dir=path.parent)
    try:
        if uid is not None:
            os.fchown(fd, uid, gid)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)

def main(c):
    class Connection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(c['socket'])
    def api(method, path, data=None, token=None, missing=False):
        h = Connection('localhost', timeout=30)
        try:
            h.request(method, '/v1/' + path, json.dumps(data) if data is not None else None,
                      {'X-Vault-Token': c['root_token'] if token is None else token,
                       'Content-Type': 'application/json'})
            response = h.getresponse()
            body = response.read()
            if missing and response.status == 404:
                return None
            if response.status >= 300:
                raise APIError(response.status)
            return json.loads(body) if body else {}
        finally:
            h.close()
    changed = False
    period = seconds(c['period'])
    if c['action'] == 'configure':
        mount = c['mount']
        if not mount or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for ch in mount):
            raise ValueError('KV mount must be a single safe path component')
        mounts = api('GET', 'sys/mounts')['data']
        if mount + '/' not in mounts:
            api('POST', 'sys/mounts/' + mount, {'type': 'kv', 'options': {'version': '2'}})
            changed = True
        else:
            existing = mounts[mount + '/']
            if existing['type'] != 'kv' or existing.get('options', {}).get('version') != '2':
                raise ValueError('Existing mount is not KV v2; refusing to migrate it')
        policy = (f'path "{mount}/data/openclaw/*" {{ capabilities = ["read"] }}\n'
                  'path "auth/token/lookup-self" { capabilities = ["read"] }\n'
                  'path "auth/token/renew-self" { capabilities = ["update"] }\n')
        specs = {
            'sys/policies/acl/infrabox-openclaw': {'policy': policy},
            'auth/token/roles/infrabox-openclaw': {
                'allowed_policies': ['infrabox-openclaw'], 'disallowed_policies': ['default'],
                'orphan': True, 'renewable': True, 'token_type': 'service',
                'token_period': period, 'token_explicit_max_ttl': 0,
            },
        }
        for path, spec in specs.items():
            current = api('GET', path, missing=True)
            if current is None or any(current['data'].get(k) != v for k, v in spec.items()):
                api('POST', path, spec)
                changed = True
    elif c['action'] == 'provision':
        path = Path(c['token_file'])
        pending = path.parent.parent / 'superseded-token-accessor'
        restart = path.parent.parent / 'restart-required'
        old = None
        if path.exists():
            token = path.read_text().strip()
            try:
                old = api('GET', 'auth/token/lookup-self', token=token)['data']
            except APIError as exc:
                if exc.status != 403:
                    raise
                # A wrongly scoped live token may lack lookup-self. Privileged
                # lookup distinguishes that case so its accessor can be retired.
                try:
                    old = api('POST', 'auth/token/lookup', {'token': token})['data']
                except APIError as lookup_error:
                    if lookup_error.status not in (400, 403):
                        raise
            if old and 'root' in old.get('policies', []):
                raise RuntimeError('Refusing to manage a root token found in the OpenClaw credential file')
            if old and matches(old, period):
                print(json.dumps({'changed': False}))
                return
        if pending.exists():
            raise RuntimeError('Previous token replacement awaits verification and finalization')
        new = api('POST', 'auth/token/create/infrabox-openclaw', {
            'policies': ['infrabox-openclaw'], 'no_default_policy': True,
            'renewable': True, 'period': c['period'], 'display_name': 'infrabox-openclaw',
        })['auth']['client_token']
        try:
            if not matches(api('GET', 'auth/token/lookup-self', token=new)['data'], period):
                raise RuntimeError('New OpenClaw token does not satisfy the required contract')
            if old:
                atomic(pending, old['accessor'])
            atomic(restart, 'Token replacement requires Gateway restart and verification.\n')
            atomic(path, new + '\n', int(c['uid']), int(c['gid']))
        except Exception:
            api('POST', 'auth/token/revoke', {'token': new})
            pending.unlink(missing_ok=True)
            restart.unlink(missing_ok=True)
            raise
        changed = True
    elif c['action'] == 'finalize':
        pending = Path(c['token_file']).parent.parent / 'superseded-token-accessor'
        if pending.exists():
            # Confirm the replacement works through the actual bundled resolver
            # before retiring the old token. Leave pending state on any failure.
            fixture = 'openclaw/test/replacement-' + secrets.token_hex(8)
            value = secrets.token_hex(32)
            try:
                api('POST', c['mount'] + '/data/' + fixture, {'data': {'probe': value}})
                result = subprocess.run(
                    ['podman', 'exec', '-i', 'openclaw', 'node',
                     '/app/dist/extensions/vault/vault-secret-ref-resolver.js'],
                    input=json.dumps({'protocolVersion': 1, 'ids': [fixture + '/probe']}),
                    text=True, capture_output=True, timeout=30)
                if result.returncode or json.loads(result.stdout).get('values', {}).get(fixture + '/probe') != value:
                    raise RuntimeError('Replacement token failed bundled Vault SecretRef verification')
            finally:
                api('DELETE', c['mount'] + '/metadata/' + fixture)
            accessor = pending.read_text().strip()
            try:
                api('POST', 'auth/token/revoke-accessor', {'accessor': accessor})
            except APIError as exc:
                if exc.status != 400:
                    raise
            pending.unlink()
            changed = True
        restart = Path(c['token_file']).parent.parent / 'restart-required'
        if restart.exists():
            restart.unlink()
            changed = True
    else:
        raise ValueError('Unknown action')
    print(json.dumps({'changed': changed}))

if __name__ == '__main__':
    try:
        main(json.load(sys.stdin))
    except Exception as exc:
        # No response bodies, token values, or request parameters in diagnostics.
        print(str(exc), file=sys.stderr)
        sys.exit(1)

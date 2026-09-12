#!/usr/bin/env python3
"""Capture/verify Gateway identity around two normal site runs on the appliance."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

config = Path('/etc/infrabox/openclaw')
base = config / 'idempotence-test.json'
markers = [Path('/srv/infrabox/openclaw', kind, '.infrabox-idempotence-test') for kind in ['state', 'workspace']]
def snapshot():
    token = config / 'secrets/vault-token'
    return {
        'token': hashlib.sha256(token.read_bytes()).hexdigest(),
        'token_inode': token.stat().st_ino,
        'gateway_invocation': subprocess.check_output(['systemctl', 'show', 'openclaw', '-p', 'InvocationID', '--value'], text=True).strip(),
        'nginx_certificate': hashlib.sha256(Path('/etc/infrabox/pki/nginx/server.crt').read_bytes()).hexdigest(),
        'markers': [p.read_text() for p in markers],
    }
if sys.argv[1] == 'capture':
    assert not base.exists() and not any(p.exists() for p in markers), 'Existing acceptance baseline requires review'
    for marker in markers:
        marker.write_text(secrets.token_hex(16))
    with os.fdopen(os.open(base, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(snapshot(), stream)
    print('Recorded token, Gateway, certificate, and persistent-state baseline')
elif sys.argv[1] == 'verify':
    assert json.loads(base.read_text()) == snapshot(), 'An ordinary rerun changed Gateway identity or persistent state'
    base.unlink()
    for marker in markers:
        marker.unlink()
    print('Token and inode, Gateway invocation, nginx certificate, state and workspace survived both site runs unchanged')
else:
    raise ValueError('Use capture or verify')

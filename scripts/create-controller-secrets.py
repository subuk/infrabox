#!/usr/bin/env python3
"""Create local bootstrap inputs once, without printing secret values."""
import json
import argparse
import os
from pathlib import Path
import re
import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--inventory-hostname', default='infrabox1',
                    help='Host alias in the selected inventory; also the secret directory name.')
args = parser.parse_args()
if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.inventory_hostname):
    parser.error('inventory hostname must be a single safe directory name')

base = Path(__file__).resolve().parents[1] / '.secrets' / args.inventory_hostname
base.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(base.parent, 0o700)
os.chmod(base, 0o700)
path = base / 'inputs.json'
identity_keys = [
    'lldap_database_password', 'lldap_admin_password', 'lldap_reader_password',
    'lldap_jwt_secret', 'lldap_key_seed',
    'identity_openclaw_password', 'identity_platform_password', 'identity_monitor_password',
]
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    # Add newly introduced inputs while preserving every existing credential.
    os.chmod(path, 0o600)
    data = json.loads(path.read_text())
    missing = [key for key in ['openclaw_gateway_token', *identity_keys] if key not in data]
    if missing:
        import tempfile
        data.update({key: secrets.token_hex(32) for key in missing})
        fd, temporary = tempfile.mkstemp(dir=base, prefix='.inputs-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        print('Added missing protected inputs; existing credentials preserved.')
    else:
        print('Existing controller secret inputs preserved.')
else:
    keys = [
        'tpm2_pkcs11_so_pin', 'tpm2_pkcs11_user_pin',
        'postgresql_admin_password', 'gitea_database_password',
        'netbox_database_password', 'grafana_database_password',
        'redis_password', 'netbox_secret_key',
        'gitea_internal_token', 'gitea_secret_key', 'netbox_api_token_pepper',
        'openclaw_gateway_token',
    ]
    keys.extend(identity_keys)
    with os.fdopen(fd, 'w') as stream:
        json.dump({key: secrets.token_hex(32) for key in keys}, stream)
        stream.write('\n')
    print('Created protected controller secret inputs.')

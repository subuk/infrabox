#!/usr/bin/env python3
"""Create local bootstrap inputs once, without printing secret values."""
import json
import os
from pathlib import Path
import secrets

base = Path(__file__).resolve().parents[1] / '.secrets' / 'infrabox1'
base.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(base.parent, 0o700)
os.chmod(base, 0o700)
path = base / 'inputs.json'
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print('Existing controller secret inputs preserved.')
else:
    with os.fdopen(fd, 'w') as stream:
        json.dump({key: secrets.token_hex(32) for key in (
            'tpm2_pkcs11_so_pin', 'tpm2_pkcs11_user_pin',
            'postgresql_admin_password', 'gitea_database_password',
            'netbox_database_password', 'grafana_database_password',
            'redis_password', 'gitea_admin_password', 'netbox_admin_password',
            'grafana_admin_password', 'netbox_secret_key',
            'gitea_internal_token', 'gitea_secret_key', 'netbox_api_token_pepper',
        )}, stream)
        stream.write('\n')
    print('Created protected controller secret inputs.')

#!/usr/bin/env python3
"""Provision one dedicated store. Never repair missing keys over existing Bao data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml

os.umask(0o077)
c = json.load(sys.stdin)
store = Path(c['store'])
os.environ['TPM2_PKCS11_STORE'] = str(store)
os.environ['INFRABOX_TPM_PIN'] = c['user_pin']
changed = False

def run(args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        # No arguments or provider output: these operations handle credentials.
        detail = result.stderr.replace(c['so_pin'], '[REDACTED]').replace(c['user_pin'], '[REDACTED]')
        raise RuntimeError('TPM operation failed: ' + args[0] + ' ' + args[1] + ': ' + repr(detail[-2000:]))
    return result.stdout

def guard():
    data = Path(c['openbao_data'])
    if data.exists() and any(data.rglob('*')):
        raise RuntimeError('Refusing to create missing seal material while OpenBao data exists')

if not (store / 'tpm2_pkcs11.sqlite3').exists():
    guard()
    run(['tpm2_ptool', 'init', '--path', str(store)])
    changed = True
primaries = yaml.safe_load(run(['tpm2_ptool', 'listprimaries', '--path', str(store)]))
if not isinstance(primaries, list) or len(primaries) != 1:
    raise RuntimeError('Dedicated store must contain exactly one primary')
pid = str(primaries[0]['id'])
tokens = yaml.safe_load(run(['tpm2_ptool', 'listtokens', '--pid', pid, '--path', str(store)])) or []
matches = [t for t in tokens if t['label'] == c['token']]
if not matches:
    guard()
    run(['tpm2_ptool', 'addtoken', '--pid', pid, '--label', c['token'],
         '--sopin', c['so_pin'], '--userpin', c['user_pin'], '--path', str(store)])
    changed = True
elif len(matches) != 1:
    raise RuntimeError('Ambiguous TPM token')
base = ['pkcs11-tool', '--module', c['library'], '--token-label', c['token'],
        '--login', '--pin', 'env:INFRABOX_TPM_PIN']
objects = run(base + ['--list-objects', '--type', 'privkey', '--label', c['key']])
if 'Private Key Object' not in objects:
    guard()
    public = run(base + ['--list-objects', '--type', 'pubkey', '--label', c['key']])
    if 'Public Key Object' in public:
        raise RuntimeError('Incomplete seal key pair; refusing replacement')
    run(['tpm2_ptool', 'addkey', '--label', c['token'], '--key-label', c['key'],
         '--algorithm', 'rsa' + str(c['bits']), '--userpin', c['user_pin'], '--path', str(store)])
    changed = True
print(json.dumps({'changed': changed}))

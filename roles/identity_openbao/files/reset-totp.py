#!/usr/bin/env python3
"""Explicit controller recovery for one prepared human; no runtime root token."""
import importlib.util
import json
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('configuration', Path(__file__).with_name('openbao-configure.py'))
configuration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configuration)


def reset(p):
    c = p['identity']
    matches = [user for user in configuration.humans(c) if user['username'] == p['username']]
    if len(matches) != 1:
        raise RuntimeError('Recovery requires exactly one current human identity')
    bao = configuration.Bao(c)
    accessor = bao.api('GET', 'sys/auth')['ldap-human/']['accessor']
    entity = bao.api('POST', 'identity/lookup/entity', {
        'alias_name': matches[0]['uuid'], 'alias_mount_accessor': accessor})
    if not entity or entity.get('disabled') or not any(
            alias['mount_accessor'] == accessor and alias['name'] == matches[0]['uuid']
            for alias in entity.get('aliases', [])):
        raise RuntimeError('Prepared human identity does not match the current directory')
    method = json.loads((Path(c['directory']) / 'openbao-state.json').read_text()).get('method_id')
    if not method:
        raise RuntimeError('No retained TOTP method exists')
    bao.api('POST', 'identity/mfa/method/totp/admin-destroy', {'method_id': method, 'entity_id': entity['id']})
    for mount in ('ldap-human', 'ldap-enrollment'):
        bao.api('POST', 'sys/leases/revoke-prefix/auth/' + mount + '/login/' + p['username'], {})
    return {'totp_reset': True, 'mfa_required': False,
            'application_sessions_require_separate_revocation': True}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(json.dumps(reset(json.load(sys.stdin))))
    except Exception as error:
        print('TOTP recovery failed: ' + (str(error) if isinstance(error, RuntimeError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)

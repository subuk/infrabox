#!/usr/bin/env python3
"""One-shot native APIs; root authorization arrives on stdin, never stored."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import quote


def ldif_records(text):
    unfolded = []
    for line in text.splitlines():
        if line.startswith(' ') and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    records, record = [], {}
    for line in unfolded + ['']:
        if not line:
            if record:
                records.append(record)
                record = {}
        elif not line.startswith('#') and ':' in line:
            key, value = line.split(':', 1)
            if value.startswith(':'):
                value = base64.b64decode(value[1:].strip()).decode()
            elif value.startswith('<'):
                raise RuntimeError('External LDIF values are not supported')
            else:
                value = value.lstrip(' ')
            record.setdefault(key.lower(), []).append(value)
    return records


def humans(p):
    with tempfile.TemporaryDirectory(prefix='identity-read-', dir='/run') as temporary:
        password = Path(temporary) / 'password'
        password.write_text(p['bind_password'])
        password.chmod(0o600)
        result = subprocess.run([
            'ldapsearch', '-LLL', '-x', '-H', p['controller_ldap_url'],
            '-D', 'uid=' + p['bind_username'] + ',ou=people,' + p['base_dn'],
            '-y', str(password), '-b', 'ou=people,' + p['base_dn'],
            '(infraboxIdentityType=human)', 'uid', 'entryUUID', 'mail', 'displayName',
        ], env={**os.environ, 'LDAPTLS_CACERT': p['ca_file'], 'LDAPTLS_REQCERT': 'demand'},
            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Verified LDAPS human-directory read failed')
    users = []
    for record in ldif_records(result.stdout):
        if any(len(record.get(key, [])) != 1 for key in ('uid', 'entryuuid', 'mail')):
            raise RuntimeError('A human identity needs one UID, entryUUID and email')
        if str(uuid.UUID(record['entryuuid'][0])) != record['entryuuid'][0]:
            raise RuntimeError('Directory entryUUID is not canonical')
        users.append({'uuid': record['entryuuid'][0], 'username': record['uid'][0],
                      'email': record['mail'][0],
                      'display_name': record.get('displayname', record['uid'])[0]})
    return users


def save_json(path, value):
    content = json.dumps(value, sort_keys=True, indent=2) + '\n'
    if path.exists() and path.read_text() == content:
        return False
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.identity-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


class Bao:
    def __init__(self, p):
        self.p = p
        self.changed = False
        self.changes = []

    def api(self, method, path, data=None, missing=False):
        class Connection(http.client.HTTPConnection):
            def connect(inner):
                inner.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                inner.sock.settimeout(inner.timeout)
                inner.sock.connect(self.p['socket'])
        connection = Connection('localhost', timeout=30)
        try:
            connection.request(method, '/v1/' + path,
                               json.dumps(data) if data is not None else None,
                               {'X-Vault-Token': self.p['token'], 'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = response.read()
            if missing and response.status == 404:
                return None
            if response.status >= 300:
                raise RuntimeError('OpenBao operation failed: ' + method + ' ' + path + ' status=' + str(response.status))
            parsed = json.loads(body) if body else {}
            if parsed.get('auth'):
                return parsed
            return parsed.get('data', parsed)
        finally:
            connection.close()

    def write(self, path, data):
        result = self.api('POST', path, data)
        self.changed = True
        self.changes.append(path)
        return result

    def ensure(self, path, spec, read_spec=None):
        current = self.api('GET', path, missing=True)
        expected = read_spec if read_spec is not None else spec
        if current is None or any(not equivalent(current.get(k), v) for k, v in expected.items()):
            self.write(path, spec)
            return self.api('GET', path)
        return current


def equivalent(current, desired):
    if isinstance(desired, list):
        return sorted(current or []) == sorted(desired)
    if isinstance(desired, dict):
        return (current or {}) == desired
    return current == desired


def human_policy(provider):
    # Entity metadata is user-owned profile data, never an authorization input.
    # No list, create, delete, alias, name, disabled, or policies permission.
    return (
        'path "auth/token/lookup-self" { capabilities = ["read"] }\n'
        'path "auth/token/revoke-self" { capabilities = ["update"] }\n'
        'path "sys/capabilities-self" { capabilities = ["update"] }\n'
        'path "identity/entity/id/{{identity.entity.id}}" { '
        'capabilities = ["read", "update"] allowed_parameters = { "metadata" = [] } }\n'
        'path "identity/oidc/provider/' + provider + '/authorize" '
        '{ capabilities = ["read", "update"] }\n'
    )


def configure(p):
    directory = Path(p['directory'])
    state_path = directory / 'openbao-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    bao = Bao(p)
    auth = bao.api('GET', 'sys/auth')
    for mount in ('ldap-human', 'ldap-service', 'ldap-enrollment'):
        if mount + '/' not in auth:
            bao.write('sys/auth/' + mount, {'type': 'ldap'})
        elif auth[mount + '/']['type'] != 'ldap':
            raise RuntimeError('Unexpected auth mount type at ' + mount)
    auth = bao.api('GET', 'sys/auth')
    # Preserve any existing TOTP method, secrets, entities and aliases. Disable
    # only our enforcement; do not create or merge identities during deployment.
    enforcement = 'identity/mfa/login-enforcement/infrabox-humans'
    if bao.api('GET', enforcement, missing=True) is not None:
        bao.api('DELETE', enforcement)
        bao.changed = True
        bao.changes.append(enforcement)
    self_policy = ('path "auth/token/lookup-self" { capabilities = ["read"] }\n'
                   'path "auth/token/revoke-self" { capabilities = ["update"] }\n'
                   'path "sys/capabilities-self" { capabilities = ["update"] }\n')
    policies = {
        'infrabox-enrollment': self_policy,
        'infrabox-human': human_policy(p['provider']),
        'infrabox-service': self_policy + 'path "auth/token/renew-self" { capabilities = ["update"] }\n',
        'infrabox-monitoring': 'path "sys/metrics" { capabilities = ["read", "list"] }\n',
        'infrabox-kv-admin': 'path "kv/*" { capabilities = ["create", "read", "update", "patch", "delete", "list"] }\n',
    }
    for name, policy in policies.items():
        bao.ensure('sys/policies/acl/' + name, {'policy': policy})
    # Only the human mount attaches the human administrator's KV permission.
    bao.ensure('auth/ldap-human/groups/' + quote('infrabox:openbao:admin', safe=''),
               {'policies': ['infrabox-kv-admin']})
    bao.ensure('auth/ldap-service/groups/' + quote('infrabox:openbao:monitor', safe=''),
               {'policies': ['infrabox-monitoring']})
    group_ids = {}
    for name in p['role_groups']:
        group = bao.ensure('identity/group/name/' + quote(name, safe=''),
                           {'type': 'external', 'policies': [], 'metadata': {'managed_by': 'infrabox'}})
        group_ids[name] = group['id']
        alias = group.get('alias') or {}
        if alias and (alias.get('name') != name or alias.get('mount_accessor') != auth['ldap-human/']['accessor']):
            raise RuntimeError('Managed external group alias conflicts')
        if not alias:
            bao.write('identity/group-alias', {'name': name, 'canonical_id': group['id'],
                                             'mount_accessor': auth['ldap-human/']['accessor']})
    # LDAP creates entities on first login using its immutable entryUUID alias.
    # Keep the retired enrollment mount/accessor but deny all new enrollments.
    for mount, kind, policy in [('ldap-human', 'human', 'infrabox-human'),
                                ('ldap-service', 'service', 'infrabox-service'),
                                ('ldap-enrollment', 'human', 'infrabox-enrollment')]:
        enrollment = mount == 'ldap-enrollment'
        spec = {
            'url': p['ldap_url'], 'certificate': Path(p['ca_file']).read_text(),
            'insecure_tls': False, 'starttls': False,
            'binddn': 'uid=' + p['bind_username'] + ',ou=people,' + p['base_dn'],
            'userdn': 'ou=people,' + p['base_dn'], 'userattr': 'entryuuid',
            'userfilter': ('(!(objectClass=*))' if enrollment else
                           '(&(uid={{.Username}})(infraboxIdentityType=' + kind + ')(entryUUID=*))'),
            'username_as_alias': False, 'groupdn': 'ou=groups,' + p['base_dn'],
            'groupfilter': '(!(objectClass=*))' if enrollment else '(member={{.UserDN}})',
            'groupattr': 'cn', 'token_no_default_policy': True, 'token_policies': [policy],
            'token_ttl': int(p['enrollment_ttl'] if enrollment else p['human_ttl']),
            'token_max_ttl': int(p['enrollment_ttl'] if enrollment else p['human_max_ttl']),
        }
        current = bao.api('GET', 'auth/' + mount + '/config', missing=True)
        fingerprint = hashlib.sha256(p['bind_password'].encode()).hexdigest()
        if (current is None or state.get('bind_fingerprint') != fingerprint or
                any(not equivalent(current.get(k), v) for k, v in spec.items())):
            bao.write('auth/' + mount + '/config', {**spec, 'bindpass': p['bind_password']})
    state['bind_fingerprint'] = fingerprint
    # Actual clients use role-based assignments below, not per-user allowlists.
    if bao.api('GET', 'identity/oidc/assignment/infrabox-humans', missing=True) is not None:
        bao.api('DELETE', 'identity/oidc/assignment/infrabox-humans')
        bao.changed = True
        bao.changes.append('identity/oidc/assignment/infrabox-humans')
    alias_name = 'identity.entity.aliases.' + auth['ldap-human/']['accessor'] + '.metadata.name'
    scopes = {
        'profile': '{"email": {{identity.entity.metadata.email}}, "email_verified": false, '
                   '"preferred_username": {{' + alias_name + '}}, "name": {{identity.entity.metadata.display_name}}}',
        'roles': '{"groups": {{identity.entity.groups.names}}}',
    }
    for name, template in scopes.items():
        # Native reads return the decoded template.
        bao.ensure('identity/oidc/scope/' + name, {'template': template})
    key_path = 'identity/oidc/key/infrabox'
    if bao.api('GET', key_path, missing=True) is None:
        bao.write(key_path, {'algorithm': 'RS256', 'allowed_client_ids': []})
    clients = {}
    for name, client in p['clients'].items():
        application_groups = sorted(group_id for group_name, group_id in group_ids.items()
                                    if group_name.startswith('infrabox:' + name + ':'))
        if not application_groups:
            raise RuntimeError('OIDC client has no managed application roles')
        bao.ensure('identity/oidc/assignment/infrabox-' + name,
                   {'entity_ids': [], 'group_ids': application_groups})
        current = bao.ensure('identity/oidc/client/' + name, {
            'key': 'infrabox', 'assignments': ['infrabox-' + name],
            'redirect_uris': client['redirect_uris'], 'client_type': 'confidential',
            'id_token_ttl': int(p['human_ttl']), 'access_token_ttl': int(p['human_ttl']),
        })
        clients[name] = {key: current[key] for key in ('client_id', 'client_secret', 'redirect_uris')}
    client_ids = sorted(client['client_id'] for client in clients.values())
    bao.ensure(key_path, {'allowed_client_ids': client_ids})
    provider_spec = {
        'issuer': p['issuer'], 'allowed_client_ids': client_ids, 'scopes_supported': list(scopes),
    }
    bao.ensure('identity/oidc/provider/' + p['provider'], provider_spec,
               read_spec={**provider_spec, 'issuer': p['issuer'] + '/v1/identity/oidc/provider/' + p['provider']})
    for path, data in [(directory / 'clients.json', clients), (state_path, state),
                       (directory / 'browser.json', {'provider': p['provider'],
                                                    'human_mount_accessor': auth['ldap-human/']['accessor'],
                                                    'clients': {n: {k: v for k, v in c.items() if k != 'client_secret'} for n, c in clients.items()}})]:
        bao.changed = save_json(path, data) or bao.changed
    return {'changed': bao.changed, 'human_provisioning': 'native LDAP first login', 'changed_paths': bao.changes}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(json.dumps(configure(json.load(sys.stdin))))
    except Exception as error:
        # Never echo directory data, token-bearing responses or request bodies.
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print('Identity configuration failed: ' + reason, file=sys.stderr)
        sys.exit(1)

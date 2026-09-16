#!/usr/bin/env python3
"""One-shot native LLDAP bootstrap; completed identities are never reconciled."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class Directory:
    def __init__(self, parameters):
        self.parameters = parameters
        self.token = None
        self.token = self.request('/auth/simple/login', {
            'username': parameters['admin_username'], 'password': parameters['admin_password'],
        })['token']

    def request(self, path, data):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = Request(self.parameters['http_address'] + path,
                          data=json.dumps(data).encode(), headers=headers)
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def graphql(self, query, variables=None):
        response = self.request('/api/graphql', {'query': query, 'variables': variables or {}})
        if response.get('errors'):
            raise RuntimeError('Native LLDAP operation failed; no credentials or response body logged')
        return response['data']

    def set_initial_password(self, username, password):
        p = self.parameters
        with tempfile.TemporaryDirectory(prefix='lldap-bootstrap-', dir='/run') as temporary:
            root = Path(temporary)
            for name, value in [('admin', p['admin_password']), ('initial', password)]:
                path = root / name
                path.write_text(value)
                path.chmod(0o600)
            result = subprocess.run([
                'ldappasswd', '-x', '-H', p['ldaps_address'],
                '-D', 'uid=' + p['admin_username'] + ',ou=people,' + p['base_dn'],
                '-y', str(root / 'admin'), '-T', str(root / 'initial'),
                'uid=' + username + ',ou=people,' + p['base_dn'],
            ], env={**os.environ, 'LDAPTLS_CACERT': p['ca_file'], 'LDAPTLS_REQCERT': 'demand'},
                capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError('Initial LDAP password operation failed')


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.bootstrap-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def bootstrap(directory, p, state_path):
    state = json.loads(state_path.read_text()) if state_path.exists() else {'users': {}}
    changed = False
    schema = directory.graphql('{schema{userSchema{attributes{name attributeType isList isVisible isEditable}}}}')
    attributes = schema['schema']['userSchema']['attributes']
    attribute = next((a for a in attributes if a['name'].lower() == 'infraboxidentitytype'), None)
    if attribute is None:
        directory.graphql('mutation{addUserAttribute(name:"infraboxIdentityType",attributeType:STRING,isList:false,isVisible:true,isEditable:false){ok}}')
        changed = True
    elif (attribute['attributeType'], attribute['isList'], attribute['isVisible'], attribute['isEditable']) != ('STRING', False, True, False):
        raise RuntimeError('Existing identity type schema differs from the required contract')
    groups = {g['displayName']: g['id'] for g in directory.graphql('{groups{id displayName}}')['groups']}
    for name in p['role_groups']:
        if name not in groups:
            groups[name] = directory.graphql('mutation($name:String!){createGroup(name:$name){id}}', {'name': name})['createGroup']['id']
            changed = True
    users = {u['id']: u for u in directory.graphql('{users{id uuid attributes{name value} groups{displayName}}}')['users']}
    for user in p['users']:
        name = user['username']
        if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', name) or user['type'] not in ('human', 'service'):
            raise ValueError('Invalid bootstrap identity')
        prior = state['users'].get(name)
        if prior and prior.get('complete'):
            # An intentionally deleted identity or removed role stays deleted.
            # A different UUID indicates replacement and requires operator review.
            if name in users and users[name]['uuid'] != prior['uuid']:
                raise RuntimeError('Completed bootstrap identity UUID changed')
            continue
        if not prior:
            if name in users and name != p['admin_username']:
                raise RuntimeError('Unrecorded existing identity cannot be adopted automatically')
            if name not in users:
                created = directory.graphql('mutation($user:CreateUserInput!){createUser(user:$user){id uuid}}', {
                    'user': {'id': name, 'email': user['email'], 'attributes': [
                        {'name': 'infraboxIdentityType', 'value': [user['type']]},
                    ]},
                })['createUser']
                users[name] = created
            else:
                directory.graphql('mutation($user:UpdateUserInput!){updateUser(user:$user){ok}}', {
                    'user': {'id': name, 'insertAttributes': [{'name': 'infraboxIdentityType', 'value': [user['type']]}]},
                })
            prior = state['users'][name] = {'uuid': users[name]['uuid'], 'password_set': name == p['admin_username']}
            save_state(state_path, state)
            changed = True
        if name not in users or users[name]['uuid'] != prior['uuid']:
            raise RuntimeError('Incomplete bootstrap identity disappeared or changed UUID')
        if not prior['password_set']:
            directory.set_initial_password(name, user['password'])
            prior['password_set'] = True
            save_state(state_path, state)
            changed = True
        for group in user.get('groups', []):
            if group not in groups:
                raise ValueError('Bootstrap membership refers to an unknown role')
            if group in [g['displayName'] for g in users[name].get('groups', [])]:
                continue
            directory.graphql('mutation($user:String!,$group:Int!){addUserToGroup(userId:$user,groupId:$group){ok}}',
                              {'user': name, 'group': groups[group]})
        prior['complete'] = True
        save_state(state_path, state)
        changed = True
    return {'changed': changed}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        parameters = json.load(sys.stdin)
        print(json.dumps(bootstrap(Directory(parameters), parameters, Path(parameters['state_file']))))
    except Exception as error:
        # HTTP/LDAP exception text can include credential-bearing requests.
        reason = str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__
        if isinstance(error, HTTPError):
            reason = 'HTTP status ' + str(error.code)
        print('Central directory bootstrap failed: ' + reason, file=sys.stderr)
        sys.exit(1)

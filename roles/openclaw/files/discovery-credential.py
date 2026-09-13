#!/usr/bin/env python3
"""Provision the dedicated Gitea discovery identity; credentials only via stdin."""
import base64
import fcntl
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler


class ManagementError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ManagementError(message)


def atomic(path, text, uid, gid):
    fd, temporary = tempfile.mkstemp(prefix='.discovery-', dir=path.parent)
    try:
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ManagementError('Discovery credential operation refused redirect')


class Manager:
    def __init__(self, c):
        self.c, self.changed = c, False
        for key in ('username', 'organization', 'repository', 'branch', 'mount'):
            require(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}', c[key]), 'Invalid discovery configuration')
        require(c['url'].startswith('https://'), 'Gitea requires verified HTTPS')
        self.repo = '/repos/' + c['organization'] + '/' + c['repository']
        self.secret = c['mount'] + '/data/openclaw/integrations/discovery'
        self.admin = 'Basic ' + base64.b64encode((c['admin_user'] + ':' + c['admin_password']).encode()).decode()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=c['ca'])))

    def api(self, path, data=None, method='GET', auth=None, missing=False, sudo=None):
        try:
            with self.opener.open(Request(self.c['url'].rstrip('/') + '/api/v1' + path,
                    json.dumps(data).encode() if data is not None else None,
                    {'Authorization': auth or self.admin, 'Content-Type': 'application/json', **({'Sudo': sudo} if sudo else {})}, method=method), timeout=30) as response:
                body = response.read(2 * 1024 * 1024 + 1)
                require(len(body) <= 2 * 1024 * 1024, 'Gitea response exceeds limit')
                return json.loads(body) if body else {}
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise ManagementError('Gitea discovery operation HTTP ' + str(error.code)) from None

    def pages(self, path, sudo=None, auth=None):
        values = []
        for page in range(1, 21):
            rows = self.api(path + f'?limit=50&page={page}', sudo=sudo, auth=auth)
            require(isinstance(rows, list), 'Unexpected Gitea list')
            values.extend(rows)
            if len(rows) < 50:
                return values
        raise ManagementError('Gitea identity inventory exceeds limit')

    def bao(self, data=None):
        c = self.c
        class Connection(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.settimeout(30)
                self.sock.connect(c['socket'])
        conn = Connection('localhost', timeout=30)
        try:
            conn.request('GET' if data is None else 'POST', '/v1/' + self.secret,
                         json.dumps(data) if data is not None else None,
                         {'X-Vault-Token': c['root_token'], 'Content-Type': 'application/json'})
            response = conn.getresponse()
            raw = response.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, 'OpenBao response exceeds limit')
            if data is None and response.status == 404:
                return None
            require(response.status < 300, 'OpenBao discovery credential operation failed')
            return json.loads(raw) if raw else {}
        finally:
            conn.close()

    def identity(self, configure):
        c = self.c
        repo = self.api(self.repo)
        require(repo['private'] and repo['has_actions'], 'Platform must be provisioned before OpenClaw discovery')
        user = self.api('/users/' + c['username'], missing=True)
        # Only adopt an existing identity bearing our dedicated ownership marker.
        email = c['username'] + '@infrabox.invalid'
        if user is not None:
            require(user.get('email') == email, 'Discovery username belongs to another identity')
        desired = {'admin': False, 'allow_create_organization': False, 'allow_git_hook': False,
                   'allow_import_local': False, 'max_repo_creation': 0}
        if user is None:
            require(configure, 'Discovery identity missing')
            self.api('/admin/users', {**desired, 'username': c['username'], 'email': email,
                     'password': secrets.token_urlsafe(48), 'must_change_password': False}, 'POST')
            self.changed = True
        else:
            # Gitea's public user response calls this is_admin; inspect privileged
            # settings through the admin user list before reconciling.
            require(not user.get('is_admin', False), 'Discovery identity unexpectedly has administrator authority')
        org = '/orgs/' + c['organization']
        teams = self.pages(org + '/teams')
        team = next((t for t in teams if t['name'] == 'OpenClawDiscovery'), None)
        settings = {'name': 'OpenClawDiscovery', 'description': 'InfraBox managed discovery identity',
                    'permission': 'read', 'units_map': {'repo.code': 'read', 'repo.actions': 'write'},
                    'can_create_org_repo': False, 'includes_all_repositories': False}
        if team is None:
            require(configure, 'Discovery team missing')
            team = self.api(org + '/teams', settings, 'POST')
            self.changed = True
        elif any(team.get(k) != v for k, v in {**settings, 'permission': 'none'}.items()):
            require(configure, 'Discovery team permissions differ from contract')
            team = self.api('/teams/' + str(team['id']), settings, 'PATCH')
            self.changed = True
        team_path = '/teams/' + str(team['id'])
        repositories = self.pages(team_path + '/repos')
        require(all(r['id'] == repo['id'] for r in repositories), 'Discovery team has unrelated repositories')
        if not repositories:
            require(configure, 'Discovery repository membership missing')
            self.api(team_path + '/repos/' + c['organization'] + '/' + c['repository'], method='PUT')
            self.changed = True
        members = self.pages(team_path + '/members')
        require(all(u['login'] == c['username'] for u in members), 'Discovery team has unrelated members')
        if not members:
            require(configure, 'Discovery team membership missing')
            self.api(team_path + '/members/' + c['username'], method='PUT')
            self.changed = True
        # Direct collaborator grants and other teams could override Code Read.
        member_teams = self.pages('/user/teams', sudo=c['username'])
        require({t['id'] for t in member_teams} == {team['id']}, 'Discovery identity has unexpected teams')
        access = self.api(self.repo + '/collaborators/' + c['username'] + '/permission')
        require(access.get('permission') in ('read', 'none'), 'Discovery identity has unexpected repository authority')
        return repo

    def valid(self, value):
        if not isinstance(value, str) or not value:
            return False
        try:
            auth = 'token ' + value
            user = self.api('/user', auth=auth)
            require(user['login'] == self.c['username'] and not user.get('is_admin'), 'Stored token belongs to another identity')
            repositories = self.pages('/user/repos', auth=auth)
            require({r['full_name'] for r in repositories} == {self.c['organization'] + '/' + self.c['repository']}, 'Discovery token has unexpected repository membership')
            repo = self.api(self.repo, auth=auth)
            permissions = repo.get('permissions', {})
            require(permissions.get('pull') and not permissions.get('push') and not permissions.get('admin'), 'Discovery token can modify execution code or lacks read access')
            self.api(self.repo + '/actions/workflows/discover.yml', auth=auth)
            return True
        except ManagementError as error:
            if str(error) in ('Gitea discovery operation HTTP 401', 'Gitea discovery operation HTTP 403'):
                return False
            raise

    def run(self):
        c = self.c
        configure = c['action'] == 'provision'
        require(c['action'] in ('provision', 'verify', 'finalize'), 'Unknown discovery credential action')
        self.identity(configure)
        record = self.bao()
        fields = record['data']['data'] if record else {}
        if fields:
            require(fields.get('username') == c['username'] and fields.get('repository') == c['organization'] + '/' + c['repository'], 'OpenBao credential belongs to another discovery integration')
        value = fields.get('apiToken', '')
        valid = self.valid(value)
        if valid:
            tokens = self.pages('/users/' + c['username'] + '/tokens')
            current = next((t for t in tokens if t['id'] == fields.get('tokenId')), None)
            valid = bool(current and current['name'].startswith('infrabox-discovery-') and
                         set(current.get('scopes', [])) == {'read:user', 'write:repository'})
        if not valid:
            require(configure, 'Discovery token unavailable or revoked')
            password = secrets.token_urlsafe(48)
            self.api('/admin/users/' + c['username'], {'source_id': 0, 'login_name': c['username'],
                     'password': password, 'must_change_password': False, 'admin': False,
                     'allow_create_organization': False, 'allow_git_hook': False,
                     'allow_import_local': False, 'max_repo_creation': 0}, 'PATCH')
            auth = 'Basic ' + base64.b64encode((c['username'] + ':' + password).encode()).decode()
            token = self.api('/users/' + c['username'] + '/tokens',
                             {'name': 'infrabox-discovery-' + secrets.token_hex(8),
                              'scopes': ['read:user', 'write:repository']}, 'POST', auth=auth)
            value = token['sha1']
            require(self.valid(value), 'Replacement discovery token validation failed')
            fields = {**fields, 'apiToken': value, 'tokenId': token['id'], 'username': c['username'],
                      'repository': c['organization'] + '/' + c['repository']}
            self.bao({'data': fields, 'options': {'cas': record['data']['metadata']['version'] if record else 0}})
            self.changed = True
        path = Path(c['token_file'])
        if configure:
            if not path.exists() or path.read_text() != value + '\n':
                atomic(path, value + '\n', int(c['uid']), int(c['gid']))
                self.changed = True
            if (path.stat().st_uid, path.stat().st_gid) != (int(c['uid']), int(c['gid'])) or path.stat().st_mode & 0o777 != 0o600:
                os.chown(path, int(c['uid']), int(c['gid']))
                path.chmod(0o600)
                self.changed = True
        else:
            require(path.exists() and path.read_text().strip() == value, 'Runtime discovery token differs from OpenBao')
            require(path.stat().st_mode & 0o777 == 0o600 and (path.stat().st_uid, path.stat().st_gid) == (int(c['uid']), int(c['gid'])), 'Runtime discovery token permissions differ')
        if c['action'] == 'finalize':
            # Called only after actual Gateway-side HTTPS verification. Retire only
            # our prefixed tokens of this dedicated identity; preserve the current one.
            for token in self.pages('/users/' + c['username'] + '/tokens'):
                if token['id'] != fields['tokenId'] and token['name'].startswith('infrabox-discovery-'):
                    self.api('/users/' + c['username'] + '/tokens/' + str(token['id']), method='DELETE')
                    self.changed = True
        return {'changed': self.changed}


if __name__ == '__main__':
    try:
        c = json.load(sys.stdin)
        with open(Path(c['token_file']).parent.parent / 'discovery-credential.lock', 'a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            print(json.dumps(Manager(c).run()))
    except Exception as error:
        print(str(error) if isinstance(error, ManagementError) else
              'Discovery credential management failed (' + type(error).__name__ + ')', file=sys.stderr)
        sys.exit(1)

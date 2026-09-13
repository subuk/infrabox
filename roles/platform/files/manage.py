#!/usr/bin/env python3
"""Scoped Platform provisioning. Root/admin input exists only in controller stdin."""
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
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler


class ManagementError(RuntimeError):
    pass


def atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.exists() and path.read_text() == content:
        return False
    fd, name = tempfile.mkstemp(prefix='.platform-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return True


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=kwargs.pop('timeout', 120), **kwargs)
    if result.returncode:
        raise ManagementError('Command failed: ' + args[0])
    return result.stdout.strip()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ManagementError('Credential request refused redirect')


class Manager:
    def __init__(self, c):
        self.c, self.changed = c, False
        self.paused = False
        self.directory = Path(c['directory'])
        self.git_base = c['gitea_url'].rstrip('/')
        self.repo = '/repos/' + c['organization'] + '/' + c['repository']
        self.admin = 'Basic ' + base64.b64encode((c['admin_user'] + ':' + c['admin_password']).encode()).decode()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=c['ca'])))
        for key in ('organization', 'repository', 'provisioner', 'branch', 'mount'):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', c[key]):
                raise ManagementError('Invalid configuration: ' + key)
        if not self.git_base.startswith('https://') or not c['netbox_url'].startswith('https://'):
            raise ManagementError('Verified HTTPS required')

    def api(self, path, data=None, method='GET', auth=None, missing=False):
        if method != 'GET' and not self.paused and self.c['action'] in ('prepare', 'configure'):
            self.pause()
        try:
            with self.opener.open(Request(self.git_base + '/api/v1' + path,
                    json.dumps(data).encode() if data is not None else None,
                    {'Authorization': auth or self.admin, 'Content-Type': 'application/json'}, method=method), timeout=30) as response:
                body = response.read(8 * 1024 * 1024)
                return json.loads(body) if body else {}
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise ManagementError(f'Gitea {method} {path.split("?")[0]} HTTP {error.code}') from None

    def bao(self, path, data=None, method='GET', token=None, missing=False):
        if method != 'GET' and not self.paused and self.c['action'] in ('prepare', 'configure'):
            self.pause()
        sock_path = self.c['bao_socket']
        class Unix(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.settimeout(30)
                self.sock.connect(sock_path)
        conn = Unix('localhost', timeout=30)
        try:
            conn.request(method, '/v1/' + path, json.dumps(data) if data is not None else None,
                         {'X-Vault-Token': token or self.c['root_token'], 'Content-Type': 'application/json'})
            response = conn.getresponse()
            body = response.read(8 * 1024 * 1024)
            if missing and response.status in (400, 403, 404):
                return None
            if response.status >= 300:
                raise ManagementError(f'OpenBao {method} operation HTTP {response.status}')
            return json.loads(body) if body else {}
        finally:
            conn.close()

    def kv(self, path, data=None):
        path = self.c['mount'] + '/data/' + path
        record = self.bao(path, missing=True)
        if data is None:
            return record['data']['data'] if record else None
        self.bao(path, {'data': data, 'options': {'cas': record['data']['metadata']['version'] if record else 0}}, 'POST')
        self.changed = True

    def netbox(self, action, token=''):
        if action in ('reconcile', 'create'):
            self.pause()
        config = {'action': action, 'username': 'infrabox-platform',
                  'permission_name': 'InfraBox Platform read only', 'description': 'InfraBox Platform inventory', 'token': token}
        code = Path(__file__).with_name('netbox-identity.py').read_text()
        output = command(['podman', 'exec', '-i', '--workdir', '/opt/netbox/netbox', 'netbox',
            '/opt/netbox/venv/bin/python', '-c',
            'import os,json,sys,django,contextlib,io\n'
            'os.environ.setdefault("DJANGO_SETTINGS_MODULE","netbox.settings")\n'
            'with contextlib.redirect_stdout(io.StringIO()): django.setup()\n'
            'data=json.load(sys.stdin);exec(data["code"],{"config":data["config"]})'],
            input=json.dumps({'config': config, 'code': code}))
        result = json.loads(output)
        self.changed |= result.get('changed', False)
        return result

    def identities(self):
        mount = self.c['mount']
        mounts = self.bao('sys/mounts')['data']
        if mount + '/' not in mounts or mounts[mount + '/'].get('options', {}).get('version') != '2':
            raise ManagementError('Existing OpenBao KV v2 mount required')
        record = self.kv('platform/netbox')
        token = record.get('token', '') if record else ''
        try:
            self.netbox('inspect', token)
        except ManagementError:
            self.netbox('reconcile')
        if not self.netbox('inspect', token)['valid']:
            token = self.netbox('create')['token']
            replacement = True
        else:
            replacement = False
        with self.opener.open(Request(self.c['netbox_url'] + '/api/dcim/devices/?limit=1',
                                     headers={'Authorization': 'Bearer ' + token}), timeout=30) as response:
            if 'results' not in json.load(response):
                raise ManagementError('NetBox identity read failed')
        if replacement:
            self.kv('platform/netbox', {'token': token})
        self.netbox('finalize', token)
        policy = (f'path "{mount}/data/platform/*" {{ capabilities = ["read"] }}\n'
                  'path "auth/token/lookup-self" { capabilities = ["read"] }\n'
                  'path "auth/token/renew-self" { capabilities = ["update"] }\n')
        path = 'sys/policies/acl/infrabox-platform'
        current = self.bao(path, missing=True)
        if not current or current['data']['policy'] != policy:
            self.bao(path, {'policy': policy}, 'POST'); self.changed = True
        file = self.directory / 'secrets/bao-token'
        token = file.read_text().strip() if file.exists() else None
        info = self.bao('auth/token/lookup-self', token=token, missing=True) if token else None
        valid = info and set(info['data'].get('policies', [])) == {'infrabox-platform'} and info['data'].get('ttl', 0) > 0 and info['data'].get('period') == self.c['token_period'] and info['data'].get('orphan') and info['data'].get('renewable') and info['data'].get('type') == 'service' and not info['data'].get('explicit_max_ttl')
        if info and 'root' in info['data'].get('policies', []):
            raise ManagementError('Refusing root token in Platform runtime')
        if not valid:
            token = self.bao('auth/token/create-orphan', {'policies': ['infrabox-platform'],
                'no_default_policy': True, 'period': self.c['token_period'], 'renewable': True,
                'display_name': 'infrabox-platform'}, 'POST')['auth']['client_token']
            self.bao(mount + '/data/platform/netbox', token=token)
            if info:
                pending = self.directory / 'superseded-accessors.json'
                accessors = json.loads(pending.read_text()) if pending.exists() else []
                accessors.append(info['data']['accessor'])
                atomic(pending, json.dumps(sorted(set(accessors))))
            self.changed |= atomic(file, token + '\n')
        return token

    def provisioner(self):
        user = self.c['provisioner']
        record = self.kv('core/platform/gitea')
        if record:
            try:
                if self.api('/user', auth='token ' + record['token'])['login'] == user:
                    return record['token']
            except ManagementError:
                pass
        password = secrets.token_urlsafe(40)
        data = {'username': user, 'email': user + '@localhost.invalid', 'password': password,
                'must_change_password': False, 'admin': False, 'allow_create_organization': False,
                'allow_git_hook': False, 'allow_import_local': False}
        if self.api('/users/' + user, missing=True) is None:
            self.api('/admin/users', data, 'POST')
        else:
            self.api('/admin/users/' + user, {**data, 'source_id': 0, 'login_name': user}, 'PATCH')
        auth = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
        token = self.api('/users/' + user + '/tokens', {'name': 'platform-' + secrets.token_hex(6),
            'scopes': ['read:user', 'write:repository']}, 'POST', auth=auth)['sha1']
        self.kv('core/platform/gitea', {'token': token})
        return token

    def repository(self):
        c = self.c
        org = '/orgs/' + c['organization']
        if self.api(org, missing=True) is None:
            self.api('/admin/users/' + c['provisioner'] + '/orgs', {
                'username': c['organization'], 'visibility': 'private'}, 'POST'); self.changed = True
        repo = self.api(self.repo, missing=True)
        if repo is None:
            repo = self.api(org + '/repos', {'name': c['repository'], 'private': True,
                'auto_init': False, 'default_branch': c['branch']}, 'POST'); self.changed = True
        desired = {'private': True, 'has_actions': True, 'has_pull_requests': False,
                   'has_issues': False, 'has_wiki': False, 'default_branch': c['branch']}
        if any(repo.get(k) != v for k, v in desired.items()):
            self.api(self.repo, desired, 'PATCH'); self.changed = True
        teams = self.api(org + '/teams?limit=50')
        team = next((t for t in teams if t['name'] == 'Operators'), None)
        settings = {'name': 'Operators', 'permission': 'read',
                    'units_map': {'repo.code': 'read', 'repo.actions': 'write'},
                    'can_create_org_repo': False, 'includes_all_repositories': False}
        if team is None:
            team = self.api(org + '/teams', settings, 'POST'); self.changed = True
        # Gitea reports permission=none for granular units_map teams.
        elif any(team.get(k) != v for k, v in {**settings, 'permission': 'none'}.items()):
            team = self.api('/teams/' + str(team['id']), settings, 'PATCH'); self.changed = True
        team_path = '/teams/' + str(team['id'])
        if self.api(team_path + '/repos/' + c['organization'] + '/' + c['repository'], missing=True) is None:
            self.api(team_path + '/repos/' + c['organization'] + '/' + c['repository'], method='PUT'); self.changed = True
        members = {m['login'] for m in self.api(team_path + '/members')}
        for user in set(c['operators']) - members:
            self.api(team_path + '/members/' + user, method='PUT'); self.changed = True
        for user in members - set(c['operators']):
            self.api(team_path + '/members/' + user, method='DELETE'); self.changed = True
        desired = {'rule_name': c['branch'], 'enable_push': True, 'enable_push_whitelist': True,
                   'push_whitelist_usernames': [c['provisioner']], 'enable_force_push': True,
                   'enable_force_push_allowlist': True, 'force_push_allowlist_usernames': [c['provisioner']]}
        path = self.repo + '/branch_protections'
        current = self.api(path + '/' + c['branch'], missing=True)
        if current is None:
            self.api(path, desired, 'POST'); self.changed = True
        elif any(current.get(k) != v for k, v in desired.items()):
            self.api(path + '/' + c['branch'], desired, 'PATCH'); self.changed = True

    def variables(self):
        for name, value in self.c['variables'].items():
            path = self.repo + '/actions/variables/' + name
            current = self.api(path, missing=True)
            if not current or current['data'] != str(value):
                self.api(path, {'value': str(value)}, 'POST' if current is None else 'PUT')
                self.changed = True

    def runner(self):
        registration = Path(self.c['storage']) / '.runner'
        if registration.exists():
            info = json.loads(registration.read_text())
            registered = self.api(self.repo + '/actions/runners/' + str(info['id']), missing=True)
            if registered and info['address'].rstrip('/') == self.git_base:
                return
            raise ManagementError('Runner registration mismatch; explicit repair required')
        token = self.api(self.repo + '/actions/runners/registration-token', method='POST')['token']
        env = os.environ.copy()
        env['GITEA_RUNNER_REGISTRATION_TOKEN'] = token
        command(['podman', 'run', '--rm', '--network=infrabox-platform', '--userns=auto:size=65536',
            '--cap-drop=all', '--security-opt=no-new-privileges',
            '--env=GITEA_RUNNER_REGISTRATION_TOKEN', '--env=SSL_CERT_FILE=/run/trust/ca-bundle.crt',
            '--volume=' + self.c['storage'] + ':/data:Z,U',
            '--volume=' + str(self.directory / 'trust') + ':/run/trust:ro,z,U',
            '--workdir=/data', self.c['image'], 'register', '--no-interactive',
            '--instance=' + self.git_base, '--name=infrabox-platform', '--labels=infrabox-platform:host'], env=env)
        self.changed = True

    def synchronize(self, token):
        c = self.c
        registration = Path(c['storage']) / '.runner'
        runner = json.loads(registration.read_text()) if registration.exists() else None
        path = self.repo + '/branches/' + c['branch']
        previous = self.api(path, missing=True)
        old = previous['commit']['id'] if previous else ''
        # Config/runtime fingerprint is supplied by Ansible, including source SHA.
        state_path = self.directory / 'deployed.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        update = old != c['revision'] or state.get('generation') != c['generation']
        if not update:
            return
        self.pause()
        cache = c['source_dir']
        env = os.environ.copy()
        auth = base64.b64encode((c['provisioner'] + ':' + token).encode()).decode()
        env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.' + self.git_base + '/.extraHeader',
                   GIT_CONFIG_VALUE_0='Authorization: Basic ' + auth, GIT_SSL_CAINFO=c['ca'], GIT_TERMINAL_PROMPT='0')
        if old != c['revision']:
            command(['git', '-C', cache, 'push', '--force-with-lease=refs/heads/' + c['branch'] + ':' + old,
                     self.git_base + '/' + c['organization'] + '/' + c['repository'] + '.git',
                     c['revision'] + ':refs/heads/' + c['branch']], env=env)
        # Keep paused until Ansible has applied the matching unit/config and verified runtime.
        atomic(self.directory / 'pending.json', json.dumps({'revision': c['revision'], 'generation': c['generation']}))
        self.changed = True

    def pause(self):
        if self.paused:
            return
        self.paused = True
        registration = Path(self.c['storage']) / '.runner'
        if not registration.exists():
            return
        runner = json.loads(registration.read_text())
        path = self.repo + '/actions/runners/' + str(runner['id'])
        if not self.api(path)['disabled']:
            self.api(path, {'disabled': True}, 'PATCH')
            self.changed = True
        for _ in range(120):
            jobs = self.api(self.repo + '/actions/jobs?status=in_progress&limit=1')
            jobs = jobs.get('jobs', []) if isinstance(jobs, dict) else jobs
            if not jobs:
                return
            time.sleep(10)
        raise ManagementError('Active Platform job did not finish; runner remains paused')

    def prepare(self):
        state = self.directory / 'deployed.json'
        if not state.exists() or json.loads(state.read_text()).get('generation') != self.c['generation']:
            self.pause()

    def finalize(self):
        c = self.c
        state = self.api(self.repo + '/branches/' + c['branch'])
        if state['commit']['id'] != c['revision']:
            raise ManagementError('Execution branch differs from prepared revision')
        actual = command(['podman', 'exec', 'platform-runner', 'cat', '/opt/platform/REVISION'])
        if actual != c['revision']:
            raise ManagementError('Runner runtime revision mismatch')
        # Verify the mounted runtime credential over HTTPS, not just privileged lookup.
        command(['podman', 'exec', 'platform-runner', 'python3', '-c',
            'import sys;sys.path.insert(0,"/opt/platform/scripts");from discover import bao;import os;'
            'token=bao(os.environ["PLATFORM_KV_MOUNT"]+"/data/platform/netbox")["token"];'
            'from urllib.request import Request,urlopen;import ssl,json;'
            'request=Request(' + repr(c['netbox_url'] + '/api/dcim/devices/?limit=1') + ',headers={"Authorization":"Bearer "+token});'
            'assert "results" in json.load(urlopen(request,context=ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"]),timeout=15))'])
        pending = self.directory / 'superseded-accessors.json'
        if pending.exists():
            for accessor in json.loads(pending.read_text()):
                if self.bao('auth/token/lookup-accessor', {'accessor': accessor}, 'POST', missing=True):
                    self.bao('auth/token/revoke-accessor', {'accessor': accessor}, 'POST')
            pending.unlink(); self.changed = True
        registration = json.loads((Path(c['storage']) / '.runner').read_text())
        path = self.repo + '/actions/runners/' + str(registration['id'])
        if self.api(path).get('disabled'):
            self.api(path, {'disabled': False}, 'PATCH'); self.changed = True
        self.changed |= atomic(self.directory / 'deployed.json', json.dumps({
            'revision': c['revision'], 'generation': c['generation'], 'source': c['source'],
            'ref': c['ref'], 'image': c['image']}))
        (self.directory / 'pending.json').unlink(missing_ok=True)

    def run(self):
        action = self.c['action']
        if action == 'prepare':
            self.prepare()
        elif action == 'configure':
            self.identities()
            token = self.provisioner()
            self.repository()
            self.synchronize(token)
            self.variables()
        elif action == 'register':
            self.runner()
        elif action == 'finalize':
            self.finalize()
        else:
            raise ManagementError('Unknown Platform action')
        return {'changed': self.changed, 'revision': self.c['revision']}


if __name__ == '__main__':
    try:
        c = json.load(sys.stdin)
        with open('/run/lock/infrabox-platform.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            print(json.dumps(Manager(c).run()))
    except Exception as error:
        location = traceback.extract_tb(error.__traceback__)[-1]
        message = str(error) if isinstance(error, ManagementError) else (
            'Platform management failed: ' + type(error).__name__ +
            ' at ' + Path(location.filename).name + ':' + str(location.lineno))
        print(message, file=sys.stderr)
        sys.exit(1)

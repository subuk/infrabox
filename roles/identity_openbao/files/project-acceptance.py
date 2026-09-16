"""Disposable native Gitea project boundary checks; no browser or real inventory."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError('Project acceptance credential request refused redirect')


class Projects:
    def __init__(self, c, p, directory, root, suffix, admin_auth):
        self.c, self.p, self.directory, self.root = c, p, directory, root
        self.orgs = ['acceptance-' + name + '-' + suffix for name in ('a', 'b', 'c')]
        self.unrelated_org = 'acceptance-unrelated-' + suffix
        self.unrelated_created = False
        self.roles = ['infrabox:gitea:' + org + ':' + role for org in self.orgs
                      for role in ('admin', 'developer', 'reader', 'operator', 'discovery')]
        self.groups, self.modified_sources = {}, False
        self.admin_auth = admin_auth
        self.base = 'https://' + c['clients']['gitea']['redirect_uris'][0].split('/')[2]
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
        spec = importlib.util.spec_from_file_location('gitea_configuration', Path(c['directory']) / 'gitea-configure.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.Manager = module.Manager
        organizations = sorted({name[len('infrabox:gitea:'):].rsplit(':', 1)[0]
                                for name in c['role_groups'] if name.startswith('infrabox:gitea:') and name.count(':') == 3})
        self.management = {'uid': p.get('gitea_uid', 1000), 'url': self.base, 'ca': c['ca_file'],
            'admin_user': p['admin_username'], 'admin_password': p['admin_password'],
            'ldap_host': c['ldap_url'].split('://')[1].split(':')[0], 'base_dn': c['base_dn'],
            'reader_password': c['bind_password'], 'organizations': organizations,
            'clients_file': str(Path(c['directory']) / 'clients.json'),
            'issuer': c['issuer'] + '/v1/identity/oidc/provider/' + c['provider']}

    def api(self, path, method='GET', body=None, auth=None, missing=False):
        try:
            with self.opener.open(Request(self.base + '/api/v1' + path,
                None if body is None else json.dumps(body).encode(),
                {'Authorization': auth or self.admin_auth, 'Content-Type': 'application/json'}, method=method), timeout=30) as response:
                data = response.read()
                return json.loads(data) if data else None
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise

    def setup(self):
        for org in self.orgs + [self.unrelated_org]:
            if self.api('/orgs/' + org, missing=True) is not None:
                raise RuntimeError('Disposable organization name already exists')
        for name in self.roles:
            if self.root.api('GET', 'identity/group/name/' + quote(name, safe=''), missing=True):
                raise RuntimeError('Disposable OpenBao group name already exists')
        for name in self.roles:
            self.groups[name] = self.directory.graphql('mutation($name:String!){createGroup(name:$name){id}}',
                                                      {'name': name})['createGroup']['id']
        self.modified_sources = True
        self.Manager({**self.management, 'organizations': self.management['organizations'] + self.orgs}).run()
        for org in self.orgs:
            self.api('/orgs/' + org + '/repos', 'POST', {'name': 'probe', 'private': True, 'auto_init': True})
        return {**self.c, 'role_groups': self.c['role_groups'] + self.roles}

    def verify(self, human, auth, check):
        a, b, c = self.orgs
        try:
            self.api('/orgs', 'POST', {'username': self.unrelated_org, 'visibility': 'private'}, auth=auth)
            self.unrelated_created = True
            forbidden = False
        except HTTPError as error:
            forbidden = error.code == 403
        check('Gitea project admin cannot create an unrelated organization', forbidden)
        first = self.api('/repos/' + a + '/probe', auth=auth)
        second = self.api('/repos/' + b + '/probe', auth=auth)
        check('Gitea project A grants native admin', first['permissions']['admin'])
        check('Gitea project B grants only read access', second['permissions']['pull'] and not second['permissions']['push'] and not second['permissions']['admin'])
        check('Gitea project C remains inaccessible', self.api('/repos/' + c + '/probe', auth=auth, missing=True) is None)
        self.api('/repos/' + a + '/probe', 'PATCH', {'description': 'Disposable central project admin check'}, auth=auth)
        check('Gitea project A permits repository administration', True)
        try:
            self.api('/repos/' + b + '/probe', 'PATCH', {'description': 'Must be denied'}, auth=auth)
            forbidden = False
        except HTTPError as error:
            forbidden = error.code in (403, 404)
        check('Gitea project B rejects repository administration', forbidden)
        with tempfile.TemporaryDirectory(prefix='identity-projects-') as temporary:
            work = Path(temporary)
            def command(args, env=None, success=True):
                result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=45)
                if success and result.returncode:
                    raise RuntimeError('Disposable human Git transport operation failed: ' + args[0])
                return result
            command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(work / 'id')])
            key = self.api('/user/keys', 'POST', {'title': 'identity-projects', 'key': (work / 'id.pub').read_text()}, auth=auth)
            try:
                hostkeys = command(['ssh-keyscan', '-p', '2222', '127.0.0.1']).stdout
                (work / 'known_hosts').write_text(hostkeys)
                ssh = shlex.join(['ssh', '-i', str(work / 'id'), '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                                  '-o', 'UserKnownHostsFile=' + str(work / 'known_hosts')])
                env = {**os.environ, 'GIT_SSH_COMMAND': ssh, 'GIT_TERMINAL_PROMPT': '0'}
                for org in (a, b):
                    command(['git', 'clone', 'ssh://git@127.0.0.1:2222/' + org + '/probe.git', str(work / org)], env)
                    (work / org / 'identity.txt').write_text('Disposable human SSH authorization check\n')
                    command(['git', '-C', str(work / org), 'add', 'identity.txt'])
                    command(['git', '-C', str(work / org), '-c', 'user.name=Identity acceptance', '-c', 'user.email=acceptance@example.com',
                             'commit', '-m', 'Check scoped SSH access'])
                    result = command(['git', '-C', str(work / org), 'push'], env, success=False)
                    check('Human SSH push ' + ('works in project A' if org == a else 'is denied in project B'), result.returncode == 0 if org == a else result.returncode != 0)
                check('Human SSH cannot clone project C', command(['git', 'clone', 'ssh://git@127.0.0.1:2222/' + c + '/probe.git',
                      str(work / c)], env, success=False).returncode != 0)
            finally:
                self.api('/user/keys/' + str(key['id']), 'DELETE', auth=auth)
        check('Human PAT and SSH work after central login and demotion', True)

    def reconcile(self):
        self.Manager({**self.management, 'organizations': self.management['organizations'] + self.orgs}).run()

    def verify_removed(self, auth, check):
        check('Gitea removes project A access after role removal and configuration rerun',
              self.api('/repos/' + self.orgs[0] + '/probe', auth=auth, missing=True) is None)
        repository = self.api('/repos/' + self.orgs[1] + '/probe', auth=auth)
        check('Gitea preserves independent project B reader access',
              repository['permissions']['pull'] and not repository['permissions']['push'])

    def cleanup(self):
        if self.unrelated_created:
            self.api('/orgs/' + self.unrelated_org, 'DELETE')
        if self.modified_sources:
            self.Manager(self.management).run()
            for org in self.orgs:
                self.api('/repos/' + org + '/probe', 'DELETE', missing=True)
                self.api('/orgs/' + org, 'DELETE', missing=True)
        for name, group_id in self.groups.items():
            group = self.root.api('GET', 'identity/group/name/' + quote(name, safe=''), missing=True)
            if group:
                self.root.api('DELETE', 'identity/group/id/' + group['id'])
            self.directory.graphql('mutation($group:Int!){deleteGroup(groupId:$group){ok}}', {'group': group_id})

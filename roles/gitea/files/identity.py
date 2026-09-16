#!/usr/bin/env python3
"""Configure native Gitea sources; no local admin or command-line credentials."""
import base64
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler, ProxyHandler
from urllib.error import HTTPError


class Form(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.values, self.capture = {}, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        name = a.get('name')
        if tag == 'input' and name:
            self.values[name] = (a.get('value', 'on') if 'checked' in a else '') if a.get('type') == 'checkbox' else a.get('value', '')
        if tag == 'textarea' and name:
            self.capture = name
            self.values[name] = ''

    def handle_data(self, data):
        if self.capture:
            self.values[self.capture] += data

    def handle_endtag(self, tag):
        if tag == 'textarea':
            self.capture = None


class Manager:
    def __init__(self, c):
        self.c, self.changed = c, False
        self.url = c['url'].rstrip('/')
        if not self.url.startswith('https://'):
            raise RuntimeError('Native Gitea management requires HTTPS')
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()),
                                  HTTPSHandler(context=ssl.create_default_context(cafile=c['ca'])))

    def cli(self, *args):
        result = subprocess.run(['podman', 'exec', '--user', str(self.c['uid']), 'gitea',
                                 'gitea', '--config', '/etc/gitea/app.ini', 'admin', 'auth', *args],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError('Native Gitea source command failed')
        return result.stdout

    def sources(self):
        sources = {}
        for line in self.cli('list').splitlines():
            fields = line.split()
            if fields and fields[0].isdigit():
                if fields[1] in sources:
                    raise RuntimeError('Duplicate managed Gitea source name')
                sources[fields[1]] = fields[0]
        return sources

    def page(self, path, data=None):
        request = Request(self.url + path, None if data is None else urlencode(data).encode(),
                          {'Origin': self.url, **({'Content-Type': 'application/x-www-form-urlencoded'} if data is not None else {})})
        with self.opener.open(request, timeout=30) as response:
            if not response.url.startswith(self.url + '/'):
                raise RuntimeError('Native Gitea management redirected outside the appliance')
            return response.url, response.read(2 * 1024 * 1024).decode()

    def ensure_source(self, name, desired):
        source = self.sources().get(name)
        path = '/-/admin/auths/' + (source or 'new')
        _, text = self.page(path)
        current = Form(text).values
        if 'name' not in current:
            raise RuntimeError('Native Gitea source administration unavailable')
        if source and all(current.get(k, '') == v for k, v in desired.items() if k != 'type'):
            return
        payload = dict(desired)
        self.page(path, {**payload, **({'_csrf': current['_csrf']} if current.get('_csrf') else {})})
        self.changed = True
        source = self.sources().get(name)
        if not source:
            raise RuntimeError('Native Gitea source creation did not persist')
        _, text = self.page('/-/admin/auths/' + source)
        actual = Form(text).values
        mismatches = [k for k, v in desired.items() if k != 'type' and actual.get(k, '') != v]
        if mismatches:
            raise RuntimeError('Native Gitea source ' + name + ' differs in fields: ' + ', '.join(mismatches))

    def catalog(self, organizations, basic):
        def api(path, data=None, method='GET', missing=False):
            try:
                with self.opener.open(Request(self.url + '/api/v1' + path,
                        None if data is None else json.dumps(data).encode(),
                        {'Authorization': 'Basic ' + basic, 'Content-Type': 'application/json'}, method=method), timeout=30) as response:
                    body = response.read(2 * 1024 * 1024)
                    return json.loads(body) if body else {}
            except HTTPError as error:
                if missing and error.code == 404:
                    return None
                raise
        for organization in organizations:
            org = '/orgs/' + organization
            if api(org, missing=True) is None:
                api('/admin/users/' + self.c['admin_user'] + '/orgs',
                    {'username': organization, 'visibility': 'private'}, 'POST')
                self.changed = True
            teams = api(org + '/teams?limit=50')
            for name, code in [('Developers', 'write'), ('Readers', 'read')]:
                team = next((t for t in teams if t['name'] == name), None)
                desired = {'name': name, 'permission': 'read',
                           'units_map': {'repo.code': code, 'repo.actions': 'read'},
                           'can_create_org_repo': False, 'includes_all_repositories': True}
                if team is None:
                    api(org + '/teams', desired, 'POST')
                    self.changed = True
                elif any(team.get(k) != v for k, v in {**desired, 'permission': 'none'}.items()):
                    api('/teams/' + str(team['id']), desired, 'PATCH')
                    self.changed = True

    def run(self):
        c = self.c
        if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', c['admin_user']):
            raise RuntimeError('Invalid technical administrator name')
        admin_dn = 'cn=infrabox:gitea:admin,ou=groups,' + c['base_dn']
        # This source authenticates the same central technical administrator.
        # It needs no bind-reader password in argv and creates no second user.
        if 'infrabox-bootstrap' not in self.sources():
            self.cli('add-ldap-simple', '--name', 'infrabox-bootstrap',
                     '--security-protocol', 'LDAPS', '--host', c['ldap_host'], '--port', '6360',
                     '--user-dn', 'uid=%s,ou=people,' + c['base_dn'],
                     '--user-search-base', 'ou=people,' + c['base_dn'],
                     '--user-filter', '(&(uid=%s)(uid=' + c['admin_user'] + ')(infraboxIdentityType=service))',
                     '--admin-filter', '(memberOf=' + admin_dn + ')',
                     '--username-attribute', 'uid', '--email-attribute', 'mail', '--skip-local-2fa')
            self.changed = True
        basic = base64.b64encode((c['admin_user'] + ':' + c['admin_password']).encode()).decode()
        with self.opener.open(Request(self.url + '/api/v1/user', headers={'Authorization': 'Basic ' + basic}), timeout=30) as response:
            user = json.load(response)
        if user.get('login') != c['admin_user'] or not user.get('is_admin'):
            raise RuntimeError('Central technical account lacks the Gitea administrator role')
        _, login = self.page('/user/login')
        csrf = Form(login).values.get('_csrf')
        self.page('/user/login', {'user_name': c['admin_user'], 'password': c['admin_password'],
                                 **({'_csrf': csrf} if csrf else {})})
        organizations = c['organizations']
        if not organizations or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', org) for org in organizations):
            raise RuntimeError('Invalid managed Gitea organization catalog')
        self.catalog(organizations, basic)
        roles = {'admin': 'Owners', 'developer': 'Developers', 'reader': 'Readers',
                 'operator': 'Operators', 'discovery': 'OpenClawDiscovery'}
        mapping = {'infrabox:gitea:' + org + ':' + role: {org: [team]}
                   for org in organizations for role, team in roles.items()}
        self.ensure_source('infrabox-services', {
            'type': '2', 'name': 'infrabox-services', 'host': c['ldap_host'], 'port': '6360', 'security_protocol': '1',
            'bind_dn': 'uid=svc-ldap-reader,ou=people,' + c['base_dn'], 'bind_password': c['reader_password'],
            'user_base': 'ou=people,' + c['base_dn'], 'filter': '(&(uid=%s)(infraboxIdentityType=service))',
            'admin_filter': '(memberOf=' + admin_dn + ')',
            'attribute_username': 'uid', 'attribute_mail': 'mail', 'is_active': 'on', 'two_factor_policy': 'skip',
            'groups_enabled': 'on', 'group_dn': 'ou=groups,' + c['base_dn'], 'group_filter': '',
            'group_member_uid': 'member', 'user_uid': 'dn',
            'group_team_map': json.dumps({'cn=' + name + ',ou=groups,' + c['base_dn']: value for name, value in mapping.items()}),
            'group_team_map_removal': 'on', 'skip_verify': '', 'is_sync_enabled': '',
        })
        client = json.loads(Path(c['clients_file']).read_text())['gitea']
        self.ensure_source('openbao', {
            'type': '6', 'name': 'openbao', 'oauth2_provider': 'openidConnect',
            'oauth2_key': client['client_id'], 'oauth2_secret': client['client_secret'],
            'open_id_connect_auto_discovery_url': c['issuer'] + '/.well-known/openid-configuration',
            'oauth2_scopes': 'profile,roles', 'oauth2_full_name_claim_name': 'name',
            'oauth2_group_claim_name': 'groups', 'oauth2_admin_group': 'infrabox:gitea:admin',
            'oauth2_group_team_map': json.dumps(mapping), 'oauth2_group_team_map_removal': 'on',
            'is_active': 'on', 'two_factor_policy': 'skip', 'oauth2_use_custom_url': '',
        })
        return {'changed': self.changed}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(json.dumps(Manager(json.load(sys.stdin)).run()))
    except Exception as error:
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        if isinstance(error, HTTPError):
            reason = 'HTTP ' + str(error.code)
        print('Gitea identity configuration failed: ' + reason, file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Native first-login/profile acceptance; credentials are never logged."""
import base64
import hashlib
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import importlib.util
import json
import os
from pathlib import Path
import secrets
import re
import ssl
import subprocess
import sys
import time
import traceback
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler, ProxyHandler
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('configuration', Path(__file__).with_name('openbao-configure.py'))
configuration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configuration)
spec = importlib.util.spec_from_file_location('directory', Path(__file__).with_name('directory-bootstrap.py'))
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


class TokenForm(HTMLParser):
    """Read only native CSRF input and one-time PAT flash, never log HTML."""
    def __init__(self, text):
        super().__init__()
        self.csrf, self.token, self.flash = '', '', False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') in ('_csrf', 'csrfmiddlewaretoken'):
            self.csrf = attrs.get('value', '')
        if tag == 'div' and 'flash-info' in attrs.get('class', '').split():
            self.flash = True

    def handle_endtag(self, tag):
        if tag == 'div':
            self.flash = False

    def handle_data(self, data):
        if self.flash and re.fullmatch(r'[0-9a-f]{40}', data.strip()):
            self.token = data.strip()


def personal_gitea_token(opener, origin):
    path = origin + '/user/settings/applications'
    with opener.open(path, timeout=30) as response:
        form = TokenForm(response.read().decode())
        if urlparse(response.url).path != '/user/settings/applications':
            raise RuntimeError('Gitea OIDC did not establish personal settings session')
    data = {'_csrf': form.csrf, 'name': 'identity-acceptance',
            'scope-user': 'write:user', 'scope-organization': 'write:organization', 'scope-repository': 'write:repository'}
    with opener.open(Request(path, urlencode(data).encode(), {
        'Origin': origin, 'Content-Type': 'application/x-www-form-urlencoded'}), timeout=30) as response:
        token = TokenForm(response.read().decode()).token
    if not token:
        raise RuntimeError('Gitea native personal token generation failed')
    return token


def start_oidc(opener, origin, app):
    start = {'gitea': '/user/oauth2/openbao', 'netbox': '/oauth/login/oidc/',
             'grafana': '/login/generic_oauth'}[app]
    request = origin + start
    if app == 'netbox':
        with opener.open(origin + '/login/', timeout=30) as response:
            csrf = TokenForm(response.read().decode()).csrf
        if not csrf:
            raise RuntimeError('Native NetBox login CSRF token missing')
        request = Request(request, urlencode({'csrfmiddlewaretoken': csrf}).encode(), {
            'Origin': origin, 'Referer': origin + '/login/',
            'Content-Type': 'application/x-www-form-urlencoded'})
    with opener.open(request, timeout=30) as response:
        query = parse_qs(urlparse(response.url).query)
        response.read()
    return query


def run(p):
    c = original_c = p['identity']
    root = configuration.Bao(c)
    anonymous = configuration.Bao({**c, 'token': ''})
    d = directory.Directory({
        'http_address': 'http://127.0.0.1:17170', 'ldaps_address': c['controller_ldap_url'],
        'ca_file': c['ca_file'], 'base_dn': c['base_dn'],
        'admin_username': p['admin_username'], 'admin_password': p['admin_password'],
    })
    suffix = secrets.token_hex(5)
    human, service, missing = ('acceptance-' + kind + '-' + suffix for kind in ('human', 'service', 'unset'))
    password = secrets.token_urlsafe(32)
    created, entities, tokens, checks = [], [], [], []
    projects = None
    application_roles = []
    if p.get('gitea'):
        application_roles.append('infrabox:gitea:admin')
    if p.get('netbox'):
        application_roles.append('infrabox:netbox:admin')
    def check(name, value):
        if not value:
            raise RuntimeError('Identity acceptance failed: ' + name)
        checks.append(name)
    def denied(client, method, path, body=None):
        try:
            client.api(method, path, body)
            return False
        except RuntimeError as error:
            return 'status=403' in str(error) or 'status=400' in str(error)
    def session(auth):
        tokens.append(auth['client_token'])
        if auth.get('entity_id') and auth['entity_id'] not in entities:
            entities.append(auth['entity_id'])
        return configuration.Bao({**c, 'token': auth['client_token']})
    try:
        if p.get('projects'):
            spec = importlib.util.spec_from_file_location('project_acceptance', Path(__file__).with_name('project-acceptance.py'))
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            admin_auth = 'Basic ' + base64.b64encode((p['admin_username'] + ':' + p['admin_password']).encode()).decode()
            projects = module.Projects(c, p, d, root, suffix, admin_auth)
            c = projects.setup()
            configuration.configure(c)
        groups = {g['displayName']: g['id'] for g in d.graphql('{groups{id displayName}}')['groups']}
        for name, kind in [(human, 'human'), (service, 'service'), (missing, None)]:
            user = {'id': name, 'email': name + '@example.com'}
            if kind:
                user['attributes'] = [{'name': 'infraboxIdentityType', 'value': [kind]}]
            d.graphql('mutation($user:CreateUserInput!){createUser(user:$user){id uuid}}', {'user': user})
            created.append(name)
            d.set_initial_password(name, password)
        for name in ['infrabox:openbao:admin', 'infrabox:grafana:reader', *application_roles]:
            d.graphql('mutation($user:String!,$group:Int!){addUserToGroup(userId:$user,groupId:$group){ok}}',
                      {'user': human, 'group': groups[name]})
        # No configuration pass occurs between creation and first login.
        for mount in ('ldap-human', 'ldap-service', 'ldap-enrollment'):
            check('missing type denied on ' + mount, denied(anonymous, 'POST', 'auth/' + mount + '/login/' + missing, {'password': password}))
        check('service cannot enter human SSO', denied(anonymous, 'POST', 'auth/ldap-human/login/' + service, {'password': password}))
        check('enrollment is retired for humans', denied(anonymous, 'POST', 'auth/ldap-enrollment/login/' + human, {'password': password}))
        check('service cannot enroll TOTP', denied(anonymous, 'POST', 'auth/ldap-enrollment/login/' + service, {'password': password}))
        check('human cannot use service auth', denied(anonymous, 'POST', 'auth/ldap-service/login/' + human, {'password': password}))
        check('wrong human password denied', denied(anonymous, 'POST', 'auth/ldap-human/login/' + human, {'password': password + 'wrong'}))
        service_auth = anonymous.api('POST', 'auth/ldap-service/login/' + service, {'password': password})['auth']
        check('service receives token without MFA', bool(service_auth.get('client_token')) and not service_auth.get('mfa_requirement'))
        service_session = session(service_auth)
        check('service cannot authorize OIDC', denied(service_session, 'POST', 'identity/oidc/provider/' + c['provider'] + '/authorize', {}))
        authenticated = anonymous.api('POST', 'auth/ldap-human/login/' + human, {'password': password})['auth']
        human_session = session(authenticated)
        check('new human logs in without preparation or MFA', bool(authenticated.get('client_token')) and not authenticated.get('mfa_requirement'))
        entity_path = 'identity/entity/id/' + authenticated['entity_id']
        entity = human_session.api('GET', entity_path)
        check('native entity has no direct policies or imported profile', not entity['policies'] and not entity.get('metadata'))
        human_accessor = root.api('GET', 'sys/auth')['ldap-human/']['accessor']
        alias = next(a for a in entity['aliases'] if a['mount_accessor'] == human_accessor)
        profile = next(u for u in configuration.humans(c) if u['username'] == human)
        check('native alias uses immutable LDAP UUID', alias['name'] == profile['uuid'] and alias['metadata']['name'] == human)
        for label, body in [
            ('policies', {'policies': ['root']}), ('name', {'name': 'taken'}),
            ('disabled', {'disabled': True}),
            ('ID override', {'id': service_auth['entity_id'], 'metadata': {'email': 'stolen@example.com'}}),
            ('mixed metadata and policies', {'metadata': {'email': 'own@example.com'}, 'policies': ['root']}),
        ]:
            check('human cannot modify own ' + label, denied(human_session, 'POST', entity_path, body))
        foreign_path = 'identity/entity/id/' + service_auth['entity_id']
        check('foreign profile read denied', denied(human_session, 'GET', foreign_path))
        check('foreign profile write denied', denied(human_session, 'POST', foreign_path, {'metadata': {'email': 'stolen@example.com'}}))
        check('entity listing denied', denied(human_session, 'LIST', 'identity/entity/id'))
        check('entity deletion denied', denied(human_session, 'DELETE', entity_path))
        check('entity alias change denied', denied(human_session, 'POST', 'identity/entity-alias',
              {'name': profile['uuid'], 'mount_accessor': human_accessor, 'canonical_id': service_auth['entity_id']}))
        check('service cannot edit own entity profile', denied(service_session, 'POST', foreign_path, {'metadata': {'email': 'changed@example.com'}}))
        self_profile = {'email': human + '@example.com', 'display_name': 'Acceptance User',
                        'username': 'not-the-authenticated-user', 'groups': 'infrabox:netbox:admin'}
        human_session.api('POST', entity_path, {'metadata': self_profile})
        check('human saves own OpenBao profile', human_session.api('GET', entity_path)['metadata'] == self_profile)
        configuration.configure(c)
        check('Ansible preserves user-owned profile and identity', human_session.api('GET', entity_path)['metadata'] == self_profile)
        check('human receives configured human and KV policies', set(authenticated['policies']) == {'infrabox-human', 'infrabox-kv-admin'})
        caps = human_session.api('POST', 'sys/capabilities-self', {'paths': ['kv/data/example', 'pki-root/root/generate/internal']})
        check('KV admin can manage KV but not PKI', 'read' in caps['kv/data/example'] and caps['pki-root/root/generate/internal'] == ['deny'])
        client = json.loads((Path(c['directory']) / 'clients.json').read_text())['grafana']
        authorization = {'client_id': client['client_id'], 'redirect_uri': client['redirect_uris'][0],
                         'response_type': 'code', 'scope': 'openid profile roles', 'state': suffix, 'nonce': suffix}
        code = human_session.api('POST', 'identity/oidc/provider/' + c['provider'] + '/authorize', authorization)
        check('actual OIDC authorization grants code after password login', bool(code.get('code')))
        other = json.loads((Path(c['directory']) / 'clients.json').read_text())['netbox']
        if not p.get('netbox'):
            check('human without NetBox role cannot authorize NetBox', denied(
                human_session, 'POST', 'identity/oidc/provider/' + c['provider'] + '/authorize',
                {**authorization, 'client_id': other['client_id'], 'redirect_uri': other['redirect_uris'][0]}))
        if p.get('grafana'):
            grafana = urlparse(client['redirect_uris'][0])
            origin = grafana.scheme + '://' + grafana.netloc
            opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()),
                                 HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
            with opener.open(client['redirect_uris'][0], timeout=30) as response:
                query = parse_qs(urlparse(response.url).query)
                response.read()
            check('Grafana starts real PKCE authorization', query.get('code_challenge_method') == ['S256'] and bool(query.get('state')))
            request = {key: value[0] for key, value in query.items()}
            code = human_session.api('POST', 'identity/oidc/provider/' + c['provider'] + '/authorize', request)
            callback = client['redirect_uris'][0] + '?' + urlencode({'code': code['code'], 'state': request['state']})
            with opener.open(callback, timeout=30) as response:
                response.read()
            with opener.open(origin + '/api/user', timeout=30) as response:
                me = json.load(response)
            check('Grafana exchanges actual OIDC code and creates personal session', me['login'] == human and me['email'] == human + '@example.com')
            check('Grafana reader has no server administration', not me['isGrafanaAdmin'])
            with opener.open(origin + '/api/user/orgs', timeout=30) as response:
                orgs = json.load(response)
            check('Grafana maps native reader role to Viewer', len(orgs) == 1 and orgs[0]['role'] == 'Viewer')
            direct = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
            admin_header = {'Authorization': 'Basic ' + base64.b64encode((p['admin_username'] + ':' + p['admin_password']).encode()).decode(),
                            'Content-Type': 'application/json'}
            # A real disposable local password proves the disabled native
            # password backend cannot become a fallback for human/service LDAP.
            with direct.open(Request(origin + '/api/admin/users', json.dumps({
                'name': missing, 'login': missing, 'email': missing + '@example.com',
                'password': password, 'OrgId': 1}).encode(), admin_header), timeout=30) as response:
                response.read()
            for username, label in ((human, 'human LDAP password'), (service, 'unapproved service'), (missing, 'actual local password')):
                try:
                    direct.open(Request(origin + '/api/user', headers={'Authorization': 'Basic ' +
                        base64.b64encode((username + ':' + password).encode()).decode()}), timeout=30)
                    rejected = False
                except HTTPError as error:
                    rejected = error.code == 401
                check('Grafana rejects ' + label + ' through Basic auth', rejected)
        for app in ('gitea', 'netbox'):
            if not p.get(app):
                continue
            clients = json.loads((Path(c['directory']) / 'clients.json').read_text())
            app_client = clients[app]
            callback_uri = app_client['redirect_uris'][0]
            parsed = urlparse(callback_uri)
            origin = parsed.scheme + '://' + parsed.netloc
            opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()),
                                  HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
            query = start_oidc(opener, origin, app)
            check(app + ' starts native OIDC authorization', bool(query.get('state')) and query.get('client_id') == [app_client['client_id']])
            if app == 'netbox':
                check('NetBox requests PKCE', query.get('code_challenge_method') == ['S256'])
            request = {key: value[0] for key, value in query.items()}
            code = human_session.api('POST', 'identity/oidc/provider/' + c['provider'] + '/authorize', request)
            with opener.open(callback_uri + '?' + urlencode({'code': code['code'], 'state': request['state']}), timeout=30) as response:
                response.read()
            direct = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
            if app == 'gitea':
                with opener.open(origin + '/user/settings/account', timeout=30) as response:
                    form = TokenForm(response.read().decode())
                try:
                    opener.open(Request(origin + '/user/settings/account', urlencode({
                        '_csrf': form.csrf, 'old_password': '', 'password': password,
                        'retype': password}).encode(), {'Origin': origin,
                        'Content-Type': 'application/x-www-form-urlencoded'}), timeout=30)
                    blocked = False
                except HTTPError as error:
                    blocked = error.code == 404
                check('Gitea external user cannot create a local password', blocked)
                for route in ('forgot_password', 'reset_password'):
                    try:
                        direct.open(origin + '/user/' + route, timeout=30)
                        blocked = False
                    except HTTPError as error:
                        blocked = error.code == 404
                    check('Gitea blocks local ' + route + ' entry point', blocked)
                human_gitea_token = personal_gitea_token(opener, origin)
                human_header = {'Authorization': 'token ' + human_gitea_token}
                with direct.open(Request(origin + '/api/v1/user', headers=human_header), timeout=30) as response:
                    me = json.load(response)
                check('Gitea creates native central admin session', me['login'] == human and me['is_admin'] and me['email'] == human + '@example.com')
                try:
                    basic = base64.b64encode((human + ':' + password).encode()).decode()
                    direct.open(Request(origin + '/api/v1/user', headers={'Authorization': 'Basic ' + basic}), timeout=30)
                    human_password_denied = False
                except HTTPError as error:
                    human_password_denied = error.code in (401, 403)
                check('Gitea rejects human direct password authentication', human_password_denied)
                own_basic = base64.b64encode((service + ':' + password).encode()).decode()
                with direct.open(Request(origin + '/api/v1/users/' + service + '/tokens',
                    json.dumps({'name': 'identity-acceptance', 'scopes': ['read:user']}).encode(),
                    {'Authorization': 'Basic ' + own_basic, 'Content-Type': 'application/json'}), timeout=30) as response:
                    personal_token = json.load(response)
                with direct.open(Request(origin + '/api/v1/user', headers={'Authorization': 'token ' + personal_token['sha1']}), timeout=30) as response:
                    service_me = json.load(response)
                check('Gitea service provisions its own scoped PAT without MFA', service_me['login'] == service and not service_me['is_admin'])
            else:
                with opener.open(origin + '/api/users/users/?username=' + human, timeout=30) as response:
                    users = json.load(response)['results']
                check('NetBox creates native central admin session', len(users) == 1 and users[0]['username'] == human and {g['name'] for g in users[0]['groups']} == {'infrabox:netbox:admin'})
                try:
                    direct.open(Request(origin + '/api/users/tokens/provision/',
                        json.dumps({'username': human, 'password': password}).encode(),
                        {'Content-Type': 'application/json'}), timeout=30)
                    human_password_denied = False
                except HTTPError as error:
                    human_password_denied = error.code in (400, 401, 403)
                check('NetBox rejects human service-token password path', human_password_denied)
                d.graphql('mutation($user:String!,$group:Int!){addUserToGroup(userId:$user,groupId:$group){ok}}',
                          {'user': service, 'group': groups['infrabox:netbox:reader']})
                with direct.open(Request(origin + '/api/users/tokens/provision/',
                    json.dumps({'username': service, 'password': password, 'version': 2,
                                'description': 'Disposable identity acceptance', 'write_enabled': False}).encode(),
                    {'Content-Type': 'application/json'}), timeout=30) as response:
                    native_token = json.load(response)
                check('NetBox service provisions native v2 token without MFA', native_token.get('version') == 2 and bool(native_token.get('key') and native_token.get('token')))
                header = {'Authorization': 'Bearer nbt_' + native_token['key'] + '.' + native_token['token']}
                with direct.open(Request(origin + '/api/dcim/devices/?limit=1', headers=header), timeout=30) as response:
                    check('NetBox reader service can read inventory', 'results' in json.load(response))
                for endpoint in ('users', 'tokens', 'permissions'):
                    try:
                        direct.open(Request(origin + '/api/users/' + endpoint + '/', headers=header), timeout=30)
                        forbidden = False
                    except HTTPError as error:
                        forbidden = error.code == 403
                    check('NetBox service cannot enumerate ' + endpoint, forbidden)
                d.graphql('mutation($user:String!,$group:Int!){removeUserFromGroup(userId:$user,groupId:$group){ok}}',
                          {'user': service, 'group': groups['infrabox:netbox:reader']})
                # Native LDAP refresh reconciles removal. Merely removing the
                # directory group is not claimed to revoke an existing token.
                with direct.open(Request(origin + '/api/users/tokens/provision/',
                    json.dumps({'username': service, 'password': password, 'version': 2,
                                'description': 'Disposable removed-role acceptance', 'write_enabled': False}).encode(),
                    {'Content-Type': 'application/json'}), timeout=30) as response:
                    response.read()
                try:
                    direct.open(Request(origin + '/api/dcim/devices/?limit=1', headers=header), timeout=30)
                    removed = False
                except HTTPError as error:
                    removed = error.code == 403
                check('NetBox native LDAP removes role on fresh authentication', removed)
        def membership(name, add):
            action = 'addUserToGroup' if add else 'removeUserFromGroup'
            d.graphql('mutation($user:String!,$group:Int!){' + action + '(userId:$user,groupId:$group){ok}}',
                      {'user': human, 'group': groups[name]})

        def fresh_human_session():
            auth = anonymous.api('POST', 'auth/ldap-human/login/' + human, {'password': password})['auth']
            check('fresh login preserves canonical entity without MFA', auth['entity_id'] == entity['id'] and not auth.get('mfa_requirement'))
            return session(auth)

        def fresh_app_session(app, human_session):
            app_client = json.loads((Path(c['directory']) / 'clients.json').read_text())[app]
            callback_uri = app_client['redirect_uris'][0]
            parsed = urlparse(callback_uri)
            origin = parsed.scheme + '://' + parsed.netloc
            opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()),
                                  HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
            request = {key: value[0] for key, value in start_oidc(opener, origin, app).items()}
            code = human_session.api('POST', 'identity/oidc/provider/' + c['provider'] + '/authorize', request)
            with opener.open(callback_uri + '?' + urlencode({'code': code['code'], 'state': request['state']}), timeout=30) as response:
                response.read()
            return origin, opener

        if p.get('gitea') or p.get('netbox') or p.get('grafana'):
            if p.get('gitea'):
                membership('infrabox:gitea:admin', False)
                project_reader = next(name for name in original_c['role_groups'] if name.startswith('infrabox:gitea:') and name.endswith(':reader'))
                membership(project_reader, True)
                if projects:
                    membership('infrabox:gitea:' + projects.orgs[0] + ':admin', True)
                    membership('infrabox:gitea:' + projects.orgs[1] + ':reader', True)
            if p.get('netbox'):
                membership('infrabox:netbox:admin', False)
                membership('infrabox:netbox:reader', True)
            if p.get('grafana'):
                membership('infrabox:grafana:reader', False)
                membership('infrabox:grafana:admin', True)
            refreshed = fresh_human_session()
            if p.get('gitea'):
                origin, opener = fresh_app_session('gitea', refreshed)
                with opener.open(Request(origin + '/api/v1/user', headers=human_header), timeout=30) as response:
                    me = json.load(response)
                check('Gitea removes site admin on new central login', me['login'] == human and not me['is_admin'])
                with opener.open(Request(origin + '/api/v1/user/teams', headers=human_header), timeout=30) as response:
                    teams = json.load(response)
                check('Gitea grants project Reader through native team mapping', any(t['name'] == 'Readers' for t in teams))
                if projects:
                    projects.verify(human, human_header['Authorization'], check)
                    membership('infrabox:gitea:' + projects.orgs[0] + ':admin', False)
                    projects.reconcile()
                    fresh_app_session('gitea', fresh_human_session())
                    projects.verify_removed(human_header['Authorization'], check)
            if p.get('netbox'):
                origin, opener = fresh_app_session('netbox', refreshed)
                with opener.open(origin + '/api/dcim/devices/?limit=1', timeout=30) as response:
                    check('NetBox demoted human retains reader access', 'results' in json.load(response))
                try:
                    opener.open(origin + '/api/users/users/', timeout=30)
                    demoted = False
                except HTTPError as error:
                    demoted = error.code == 403
                check('NetBox removes native superuser on new central login', demoted)
            if p.get('grafana'):
                origin, opener = fresh_app_session('grafana', refreshed)
                with opener.open(origin + '/api/user', timeout=30) as response:
                    me = json.load(response)
                check('Grafana grants native server admin from central role', me['login'] == human and me['isGrafanaAdmin'])
                membership('infrabox:grafana:admin', False)
                membership('infrabox:grafana:reader', True)
                origin, opener = fresh_app_session('grafana', fresh_human_session())
                with opener.open(origin + '/api/user', timeout=30) as response:
                    me = json.load(response)
                with opener.open(origin + '/api/user/orgs', timeout=30) as response:
                    orgs = json.load(response)
                check('Grafana removes server admin and restores Viewer on new login',
                      not me['isGrafanaAdmin'] and len(orgs) == 1 and orgs[0]['role'] == 'Viewer')
        # LDAP profile edits must not overwrite the self-managed OpenBao profile.
        d.graphql('mutation($user:UpdateUserInput!){updateUser(user:$user){ok}}',
                  {'user': {'id': human, 'email': 'ldap-only-' + suffix + '@example.com'}})
        refreshed = fresh_human_session()
        configuration.configure(c)
        check('LDAP email changes do not overwrite OpenBao profile', refreshed.api('GET', entity_path)['metadata'] == self_profile)
        # A recreated LDAP username is a new identity, with no inherited profile.
        d.graphql('mutation($user:String!){deleteUser(userId:$user){ok}}', {'user': human})
        check('deleted LDAP human cannot log in', denied(anonymous, 'POST', 'auth/ldap-human/login/' + human, {'password': password}))
        d.graphql('mutation($user:CreateUserInput!){createUser(user:$user){id uuid}}',
                  {'user': {'id': human, 'email': human + '@example.com',
                            'attributes': [{'name': 'infraboxIdentityType', 'value': ['human']}]}})
        d.set_initial_password(human, password)
        replacement = anonymous.api('POST', 'auth/ldap-human/login/' + human, {'password': password})['auth']
        replacement_session = session(replacement)
        check('recreated username gets a new entity', replacement['entity_id'] != entity['id'])
        check('replacement inherits no profile or role policies', not replacement_session.api('GET',
              'identity/entity/id/' + replacement['entity_id']).get('metadata') and set(replacement['policies']) == {'infrabox-human'})
        check('profile group text cannot grant a role', denied(replacement_session, 'POST',
              'identity/oidc/provider/' + c['provider'] + '/authorize', authorization))
    finally:
        print(json.dumps({'completed_checks': checks}), file=sys.stderr)
        # Tokens are revoked and test users removed even when a check fails.
        for token in tokens:
            root.api('POST', 'auth/token/revoke', {'token': token})
        for name in created:
            for mount in ('ldap-human', 'ldap-service', 'ldap-enrollment'):
                root.api('POST', 'sys/leases/revoke-prefix/auth/' + mount + '/login/' + name, {})
            d.graphql('mutation($user:String!){deleteUser(userId:$user){ok}}', {'user': name})
        configuration.configure(original_c)
        for entity_id in entities:
            if root.api('GET', 'identity/entity/id/' + entity_id, missing=True):
                root.api('DELETE', 'identity/entity/id/' + entity_id)
        if p.get('grafana'):
            origin = urlparse(json.loads((Path(c['directory']) / 'clients.json').read_text())['grafana']['redirect_uris'][0]).netloc
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
            header = {'Authorization': 'Basic ' + base64.b64encode((p['admin_username'] + ':' + p['admin_password']).encode()).decode()}
            for username in (human, missing):
                try:
                    with opener.open(Request('https://' + origin + '/api/users/lookup?' + urlencode({'loginOrEmail': username}), headers=header), timeout=30) as response:
                        user = json.load(response)
                    check('Grafana cleanup selects only its disposable identity', user['login'] == username)
                    with opener.open(Request('https://' + origin + '/api/admin/users/' + str(user['id']), headers=header, method='DELETE'), timeout=30) as response:
                        response.read()
                except HTTPError as error:
                    if error.code != 404:
                        raise RuntimeError('Disposable Grafana mirror cleanup failed: HTTP ' + str(error.code)) from None
        if p.get('gitea'):
            basic = base64.b64encode((p['admin_username'] + ':' + p['admin_password']).encode()).decode()
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=c['ca_file'])))
            origin = urlparse(json.loads((Path(c['directory']) / 'clients.json').read_text())['gitea']['redirect_uris'][0]).netloc
            for username in (human, service):
                try:
                    with opener.open(Request('https://' + origin + '/api/v1/admin/users/' + username + '?purge=true',
                        headers={'Authorization': 'Basic ' + basic}, method='DELETE'), timeout=30) as response:
                        response.read()
                except HTTPError as error:
                    if error.code != 404:
                        raise RuntimeError('Disposable Gitea mirror cleanup failed: HTTP ' + str(error.code)) from None
        if p.get('netbox'):
            cleanup = ('import os,django;os.environ.setdefault("DJANGO_SETTINGS_MODULE","netbox.settings");'
                       'django.setup();from users.models import User;User.objects.filter(username__in=' + repr([human, service]) + ').delete()')
            result = subprocess.run(['podman', 'exec', '--workdir', '/opt/netbox/netbox', 'netbox',
                                     '/opt/netbox/venv/bin/python', '-c', cleanup], capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise RuntimeError('Disposable NetBox mirror cleanup failed')
        if projects:
            projects.cleanup()
    return {'checks': checks, 'disposable_users_removed': True, 'tokens_revoked': True}


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(json.dumps(run(json.load(sys.stdin))))
    except Exception as error:
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        if isinstance(error, HTTPError):
            reason += ' status=' + str(error.code) + ' path=' + urlparse(error.url).path
        frames = traceback.extract_tb(error.__traceback__)
        location = ', '.join(Path(f.filename).name + ':' + str(f.lineno) for f in frames)
        print('Native identity acceptance failed: ' + reason + ' [' + location + ']', file=sys.stderr)
        sys.exit(1)

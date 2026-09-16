#!/usr/bin/python3
"""Explicitly authorized LLDAP/OpenBao outage acceptance; no browser or root token."""
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler

sys.path.insert(0, '/usr/local/libexec/infrabox-monitoring')
import health

CONFIG = '/etc/infrabox/monitoring/catalog.json'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError('Identity recovery request refused redirect')


def main():
    catalog = json.loads(Path(CONFIG).read_text())
    # Read the same non-secret domain/CA settings consumed by the fixed worker.
    settings = catalog['settings']
    credentials = json.loads(Path('/etc/infrabox/monitoring/secrets/ldap.json').read_text())
    base = 'https://vault.' + settings['domain'] + '/v1/'
    ca = Path(settings['ca'])
    original_ca = hashlib.sha256(ca.read_bytes()).hexdigest()
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=str(ca))))
    checks = []

    def api(path, body=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Vault-Token'] = token
        with opener.open(Request(base + path, None if body is None else json.dumps(body).encode(), headers), timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}

    def check(name, value):
        if not value:
            raise RuntimeError(name)
        checks.append(name)
        print(json.dumps({'test': name, 'status': 'passed'}), flush=True)

    def authenticate(available):
        try:
            result = api('auth/ldap-service/login/' + quote(credentials['username'], safe=''),
                         {'password': credentials['password']})
        except HTTPError as error:
            if not available and error.code in (400, 403, 500, 502, 503):
                return
            raise RuntimeError('Expected service LDAP authentication unavailable') from None
        token = result.get('auth', {}).get('client_token')
        try:
            check('Service login requires available central dependencies' if not available else 'Service LDAP authentication recovered',
                  available and bool(token) and set(result['auth']['policies']) == {'infrabox-service', 'infrabox-monitoring'})
        finally:
            if token:
                api('auth/token/revoke-self', {}, token)

    def wait(predicate, label, component=None, timeout=360):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = health.load_snapshot(CONFIG, component=component)[0]
            if predicate(current):
                check(label, True)
                return
            time.sleep(5)
        raise RuntimeError(label + ' timed out')

    def healthy(current):
        return current['status'] == 'healthy' and current['coverage_complete']

    def issues(current, required):
        critical = {item['id'] for item in current['issues'] if item['state'] == 'critical'}
        return required <= critical

    def service(action, name):
        subprocess.run(['systemctl', action, name + '.service'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)

    required = {'unit_lldap', 'identity_ldap', 'unit_openbao', 'identity_oidc', 'openbao_metrics'}
    check('Identity outage checks are registered', required <= {item['id'] for item in catalog['checks']})
    wait(healthy, 'Initial complete appliance health', timeout=180)
    authenticate(True)
    original_cluster = api('sys/health')['cluster_id']
    try:
        service('stop', 'lldap')
        authenticate(False)
        check('LLDAP outage rejects service password authentication', True)
        wait(lambda current: issues(current, {'unit_lldap', 'identity_ldap', 'openbao_metrics'}),
             'LLDAP failure produces critical LDAP and OpenBao authentication alerts', timeout=300)
    finally:
        service('start', 'lldap')
    wait(healthy, 'LLDAP host recovery restores complete appliance health')
    authenticate(True)
    try:
        service('stop', 'openbao')
        authenticate(False)
        try:
            api('identity/oidc/provider/infrabox/.well-known/openid-configuration')
            unavailable = False
        except HTTPError as error:
            unavailable = error.code in (500, 502, 503)
        check('OpenBao outage makes native OIDC unavailable', unavailable)
        wait(lambda current: issues(current, {'unit_openbao', 'identity_oidc'}),
             'OpenBao failure produces critical OIDC alerts', 'openbao', timeout=300)
    finally:
        service('start', 'openbao')
    wait(healthy, 'OpenBao host recovery restores complete appliance health')
    authenticate(True)
    state = api('sys/health')
    check('OpenBao recovers unsealed with the same cluster and trust identity',
          state['initialized'] and not state['sealed'] and state['cluster_id'] == original_cluster
          and hashlib.sha256(ca.read_bytes()).hexdigest() == original_ca)
    check('OIDC discovery recovers on verified HTTPS',
          api('identity/oidc/provider/infrabox/.well-known/openid-configuration')['issuer'] == base + 'identity/oidc/provider/infrabox')
    print(json.dumps({'checks': checks, 'status': 'passed', 'services_restored': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Identity outage acceptance failed: ' + (str(error) if isinstance(error, RuntimeError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)

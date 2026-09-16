"""Native Grafana service-account API, using the central technical LDAP identity."""
import secrets


class Monitor:
    def __init__(self, api, base, auth):
        self.api, self.base, self.auth, self.changed = api, base, auth, False
        accounts = self.call('/api/serviceaccounts/search?query=infrabox-monitor')['serviceAccounts']
        matches = [a for a in accounts if a['name'] == 'infrabox-monitor']
        if len(matches) > 1:
            raise RuntimeError('Duplicate native Grafana monitoring identities')
        if matches:
            self.account = self.call('/api/serviceaccounts/' + str(matches[0]['id']))
        else:
            self.account = self.call('/api/serviceaccounts', 'POST', {
                'name': 'infrabox-monitor', 'role': 'Viewer', 'isDisabled': False})
            self.changed = True
        if self.account['role'] != 'Viewer' or self.account['isDisabled'] or self.account['orgId'] != 1:
            raise RuntimeError('Grafana monitoring identity differs from the native Viewer contract')
        self.path = '/api/serviceaccounts/' + str(self.account['id']) + '/tokens'

    def call(self, path, method='GET', data=None):
        return self.api(self.base, path, self.auth, method, data)

    def valid(self, token, token_id):
        current = next((t for t in self.call(self.path) if t['id'] == token_id), None)
        if not current or not current['name'].startswith('infrabox-monitor-') or current.get('hasExpired') or current.get('expiration'):
            return False
        try:
            user = self.api(self.base, '/api/user', 'Bearer ' + token)
            if user['login'] != self.account['login'] or user['isGrafanaAdmin'] or user['orgId'] != 1:
                return False
            self.api(self.base, '/api/datasources/uid/infrabox-prometheus', 'Bearer ' + token)
            return True
        except RuntimeError:
            return False

    def create(self):
        result = self.call(self.path, 'POST', {'name': 'infrabox-monitor-' + secrets.token_hex(8)})
        if not self.valid(result['key'], result['id']):
            raise RuntimeError('Native replacement Grafana token validation failed')
        self.changed = True
        return result['key'], result['id']

    def retire_except(self, token_id):
        for token in self.call(self.path):
            if token['id'] != token_id and token['name'].startswith('infrabox-monitor-'):
                self.call(self.path + '/' + str(token['id']), 'DELETE')
                self.changed = True
        return self.changed

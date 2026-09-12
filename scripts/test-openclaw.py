#!/usr/bin/env python3
"""Live acceptance using disposable KV fixtures; no credential values are logged."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import ssl

c = json.load(sys.stdin)
class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(c['socket'])
def api(method, path, data=None, token=None, expected=200):
    h = Connection('localhost', timeout=30)
    try:
        h.request(method, '/v1/' + path, json.dumps(data) if data is not None else None,
                  {'X-Vault-Token': c['root_token'] if token is None else token,
                   'Content-Type': 'application/json'})
        response = h.getresponse()
        body = response.read()
        assert response.status == expected, f'{method} {path}: expected HTTP {expected}, got {response.status}'
        return json.loads(body) if body else {}
    finally:
        h.close()
def run(*args, input=None, timeout=180):
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        diagnostic = (result.stdout + result.stderr)[-2000:]
        protected = [c['root_token'], globals().get('token'), globals().get('value')]
        for line in Path(c['config_dir'], 'openclaw.env').read_text().splitlines():
            if line.startswith('OPENCLAW_GATEWAY_TOKEN='):
                protected.append(line.split('=', 1)[1])
        for secret in protected:
            if secret:
                diagnostic = diagnostic.replace(secret, '[REDACTED]')
        raise RuntimeError('Acceptance subprocess failed: ' + args[0] + ' ' + args[1] + ': ' + diagnostic)
    return result.stdout

def replace_config(content):
    path = Path(c['config_dir'], 'openclaw.json')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.acceptance-')
    try:
        os.fchown(fd, c['uid'], c['gid'])
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    run('systemctl', 'restart', 'openclaw.service')
    ready()

def ready():
    probe = f'fetch("http://127.0.0.1:{c["port"]}/readyz").then(r => process.exit(r.status === 200 ? 0 : 1)).catch(() => process.exit(1))'
    for attempt in range(90):
        result = subprocess.run(['podman', 'exec', 'openclaw', 'node', '-e', probe],
                                capture_output=True, timeout=10)
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError('Gateway did not become ready')

path = Path(c['config_dir'], 'secrets/vault-token')
token = path.read_text().strip()
before = api('GET', 'auth/token/lookup-self', token=token)['data']
run('systemctl', 'start', 'openclaw-token-renew.service')
after = api('GET', 'auth/token/lookup-self', token=token)['data']
assert path.read_text().strip() == token, 'Renewal replaced token'
assert after['ttl'] >= before['ttl'] - 2 and after['ttl'] >= after['period'] - 10, 'Renewal did not reset TTL'
assert after['policies'] == ['infrabox-openclaw'] and after['orphan'] and after['renewable'], 'Renewal changed token contract'
print('Periodic renewal succeeded without changing token value or policies', flush=True)
for method, endpoint in [('GET', c['mount'] + '/data/unrelated/acceptance'),
                         ('POST', 'pki-server/issue/infrabox-server'), ('GET', 'sys/mounts'),
                         ('POST', 'auth/token/create'), ('POST', 'auth/token/revoke-accessor')]:
    api(method, endpoint, {} if method == 'POST' else None, token=token, expected=403)
print('Unrelated KV, PKI, system administration, token creation and revocation denied', flush=True)
fixture = 'openclaw/test/acceptance-' + secrets.token_hex(8)
value = secrets.token_hex(32)
config_path = Path(c['config_dir'], 'openclaw.json')
original = config_path.read_text()
modified = False
try:
    api('POST', c['mount'] + '/data/' + fixture, {'data': {'apiKey': value}})
    resolved = json.loads(run('podman', 'exec', '-i', 'openclaw', 'node',
        '/app/dist/extensions/vault/vault-secret-ref-resolver.js',
        input=json.dumps({'protocolVersion': 1, 'ids': [fixture + '/apiKey']})))
    assert resolved['values'][fixture + '/apiKey'] == value, 'Bundled Vault resolver returned incorrect data'
    assert value not in config_path.read_text(), 'Resolved secret persisted to config'
    print('Bundled Vault plugin resolved a scoped KV v2 SecretRef through verified TLS', flush=True)
    config = json.loads(original)
    config.setdefault('models', {}).setdefault('providers', {})['infrabox-acceptance'] = {
        'baseUrl': 'https://api.example.invalid/v1', 'api': 'openai-completions', 'models': [],
        'apiKey': {'source': 'exec', 'provider': 'vault', 'id': fixture + '/apiKey'},
    }
    modified = True
    print('Starting Gateway with disposable provider SecretRef', flush=True)
    replace_config(json.dumps(config))
    print('Gateway became ready with the provider SecretRef', flush=True)
    # Isolate the acceptance client's device identity from operator state.
    client_config = {'gateway': {'mode': 'remote', 'remote': {
        'url': 'wss://' + c['hostname'],
        'token': {'source': 'env', 'provider': 'default', 'id': 'OPENCLAW_GATEWAY_TOKEN'},
    }}, 'secrets': {'providers': {'default': {'source': 'env'}}}}
    create_client = """
const fs = require('node:fs');
(async () => {
 const dir = fs.mkdtempSync('/tmp/infrabox-client-');
 fs.writeFileSync(dir + '/config.json', fs.readFileSync(0), {mode: 0o600});
 process.env.OPENCLAW_STATE_DIR = dir + '/state';
 process.env.OPENCLAW_CONFIG_PATH = dir + '/config.json';
 const file = fs.readdirSync('/app/dist').find(n => /^device-identity-.*\\.mjs$/.test(n) && fs.readFileSync('/app/dist/' + n, 'utf8').includes('function loadOrCreateDeviceIdentity('));
 const identityModule = await import('/app/dist/' + file);
 const create = Object.values(identityModule).find(f => f.name === 'loadOrCreateDeviceIdentity');
 console.log(JSON.stringify({dir, deviceId: create().deviceId}));
})().catch(e => {console.error('Temporary device initialization failed:', e.message); process.exit(1)});
"""
    client = json.loads(run('podman', 'exec', '-i', 'openclaw', 'node', '-e', create_client,
                            input=json.dumps(client_config)))
    client_dir = client['dir']
    remote = ['podman', 'exec', '--env', 'OPENCLAW_CONFIG_PATH=' + client_dir + '/config.json',
              '--env', 'OPENCLAW_STATE_DIR=' + client_dir + '/state',
              'openclaw', 'node', 'openclaw.mjs', 'gateway', 'call']
    try:
        for method in ['health', 'secrets.reload']:
            args = remote + [method, '--json', '--timeout', '30000']
            result = subprocess.run(args, capture_output=True, text=True, timeout=180)
            if result.returncode:
                error = json.loads(result.stdout)['error']
                detail = error.get('details', {})
                assert error['code'] == 'NOT_PAIRED', 'Unexpected remote Gateway failure: ' + error['message']
                assert detail['deviceId'] == client['deviceId'], 'Pairing request does not belong to the test client'
                assert detail['requestedRole'] == 'operator'
                assert set(detail['requestedScopes']) <= {'operator.read', 'operator.admin'}
                run('podman', 'exec', 'openclaw', 'node', 'openclaw.mjs', 'devices',
                    'approve', detail['requestId'], '--json')
                run(*args)
    finally:
        try:
            run('podman', 'exec', 'openclaw', 'node', 'openclaw.mjs', 'devices',
                'remove', client['deviceId'], '--json')
        finally:
            run('podman', 'exec', 'openclaw', 'node', '-e',
                "require('node:fs').rmSync(process.argv[1], {recursive:true, force:true})", client_dir)
    assert value not in config_path.read_text(), 'Gateway persisted resolved credential'
    print('Gateway startup/reload resolved SecretRefs; authenticated WebSocket RPC through nginx passed', flush=True)
    # HTTP control surface: authentication must be checked before tool invocation.
    context = ssl.create_default_context(cafile=c['ca_path'])
    with urllib.request.urlopen('https://' + c['hostname'] + '/', context=context, timeout=10) as ui:
        assert ui.status == 200 and 'text/html' in ui.headers.get('Content-Type', ''), 'Control UI unavailable'
    print('Control UI served through verified HTTPS', flush=True)
    request = urllib.request.Request('https://' + c['hostname'] + '/tools/invoke',
                                    data=b'{"tool":"session_status","args":{}}',
                                    headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(request, context=context, timeout=10)
        raise RuntimeError('Unauthenticated privileged request was accepted')
    except urllib.error.HTTPError as exc:
        assert exc.code == 401, 'Unexpected unauthenticated Gateway result'
    print('Unauthenticated privileged Gateway request rejected', flush=True)
    logs = run('journalctl', '-u', 'openclaw', '-u', 'openclaw-token-renew.service',
               '--since', '10 minutes ago', '--no-pager', '-o', 'cat')
    assert value not in logs and token not in logs, 'OpenClaw secret material appeared in service logs'
    print('Resolved fixture and OpenBao token absent from service logs', flush=True)
finally:
    try:
        if modified:
            replace_config(original)
    finally:
        api('DELETE', c['mount'] + '/metadata/' + fixture, expected=204)
    print('Disposable SecretRef configuration and KV fixture removed', flush=True)
assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256((token + '\n').encode()).digest(), 'Acceptance changed token'
print('OpenClaw acceptance passed', flush=True)

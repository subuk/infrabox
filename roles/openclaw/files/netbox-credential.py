#!/usr/bin/env python3
"""OpenClaw-owned OpenBao storage/materialization; management credential via stdin."""
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


class ManagementError(RuntimeError):
    pass


def atomic(path, content, uid=0, gid=0):
    fd, name = tempfile.mkstemp(prefix='.netbox-', dir=path.parent)
    try:
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def manage(c, bao, netbox, validate):
    path = Path(c['token_file'])
    marker = path.parent.parent / 'netbox-restart-required'
    secret_path = c['mount'] + '/data/openclaw/integrations/netbox'
    record = bao('GET', secret_path)
    fields = record['data']['data'] if record else {}
    value = fields.get('apiToken', '')
    if not isinstance(value, str):
        raise ManagementError('NetBox apiToken field must be a string')
    valid = netbox('inspect', value)['valid']
    changed = False
    if c['action'] in ('verify', 'finalize'):
        if not valid or not path.exists() or path.read_text().strip() != value:
            raise ManagementError('OpenBao and runtime NetBox credentials do not match a valid integration token')
        stat = path.stat()
        if stat.st_mode & 0o777 != 0o600 or (stat.st_uid, stat.st_gid) != (int(c['uid']), int(c['gid'])):
            raise ManagementError('Runtime NetBox credential permissions are incorrect')
        validate(value)
        if c['action'] == 'finalize':
            changed = netbox('finalize', value)['changed']
            if marker.exists():
                marker.unlink()
                changed = True
        return {'changed': changed}
    if c['action'] != 'provision':
        raise ManagementError('Unknown credential action')
    if not valid:
        value = netbox('create', '')['token']
        validate(value)
        # A CAS conflict or interruption preserves prior credentials. A later
        # successful finalization disables unreferenced tokens of this identity.
        bao('POST', secret_path, {'data': {**fields, 'apiToken': value}, 'options': {
            'cas': record['data']['metadata']['version'] if record else 0}})
        changed = True
    else:
        validate(value)
    content = value + '\n'
    if not path.exists() or path.read_text() != content:
        # Persist before replacing the file: interruption cannot lose the need
        # to restart a child process which cached the previous credential.
        atomic(marker, 'NetBox credential replacement requires Gateway restart and verification.\n')
        atomic(path, content, int(c['uid']), int(c['gid']))
        changed = True
    return {'changed': changed}


def main(c):
    class Connection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(c['socket'])

    def bao(method, path, data=None):
        connection = Connection('localhost', timeout=30)
        try:
            connection.request(method, '/v1/' + path,
                               json.dumps(data) if data is not None else None,
                               {'X-Vault-Token': c['root_token'], 'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = response.read()
            if method == 'GET' and response.status == 404:
                return None
            if response.status >= 300:
                raise ManagementError(f'OpenBao NetBox credential operation failed (HTTP {response.status})')
            return json.loads(body) if body else {}
        finally:
            connection.close()

    code = Path('/usr/local/libexec/infrabox/netbox-openclaw-integration.py').read_text()

    def netbox(action, token):
        # NetBox gets only its own credential, never the OpenBao management token.
        request = {'code': code, 'config': {'action': action, 'token': token,
                   'username': c['username'], 'description': c['description']}}
        process = subprocess.run([
            'podman', 'exec', '-i', '--workdir', '/opt/netbox/netbox', 'netbox',
            '/opt/netbox/venv/bin/python', '-c',
            'import os,json,sys,django,contextlib,io\n'
            'os.environ.setdefault("DJANGO_SETTINGS_MODULE","netbox.settings")\n'
            'with contextlib.redirect_stdout(io.StringIO()):\n'
            '    django.setup()\n'
            'data=json.load(sys.stdin); exec(data["code"], {"config":data["config"]})'],
            input=json.dumps(request), text=True, capture_output=True, timeout=90)
        if process.returncode:
            raise ManagementError('NetBox identity or credential operation failed: ' + action)
        return json.loads(process.stdout)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ManagementError('NetBox credential verification refused an HTTP redirect')

    context = ssl.create_default_context(cafile=c['ca_path'])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPSHandler(context=context), NoRedirect())

    def validate(value):
        if not c['url'].startswith('https://'):
            raise ManagementError('NetBox URL must use verified HTTPS')
        request = urllib.request.Request(c['url'].rstrip('/') + '/api/dcim/sites/?limit=1',
                                         headers={'Authorization': 'Token ' + value})
        with opener.open(request, timeout=30) as response:
            if response.status != 200 or 'results' not in json.load(response):
                raise ManagementError('NetBox credential HTTPS read failed')
        for endpoint in ('users', 'tokens', 'permissions'):
            request = urllib.request.Request(c['url'].rstrip('/') + '/api/users/' + endpoint + '/?limit=1',
                                             headers={'Authorization': 'Token ' + value})
            try:
                with opener.open(request, timeout=30):
                    raise ManagementError('NetBox integration unexpectedly permits administrative reads')
            except urllib.error.HTTPError as exc:
                if exc.code != 403:
                    raise ManagementError('NetBox administrative-read denial was not HTTP 403') from None

    return manage(c, bao, netbox, validate)


if __name__ == '__main__':
    try:
        print(json.dumps(main(json.load(sys.stdin))))
    except Exception as exc:
        # Never emit subprocess output, HTTP bodies, input fields, or credentials.
        print(str(exc) if isinstance(exc, ManagementError) else
              'NetBox credential management failed (' + type(exc).__name__ + ')', file=sys.stderr)
        sys.exit(1)

#!/usr/bin/python3
"""Create a temporary private repository and exercise HTTPS, SSH, and Actions."""
import base64
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
import uuid

config = json.load(sys.stdin)
domain = config['domain']
authorization = 'Basic ' + base64.b64encode((config['username'] + ':' + config['password']).encode()).decode()
context = ssl.create_default_context()
base = 'https://git.' + domain
def api(method, path, data=None):
    request = Request(base + '/api/v1' + path, json.dumps(data).encode() if data is not None else None,
                      {'Authorization': authorization, 'Content-Type': 'application/json'}, method=method)
    with urlopen(request, context=context, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else {}
def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(args[0] + ': ' + result.stderr.replace(authorization, '[redacted]').replace(config['password'], '[redacted]'))
    return result.stdout

name = 'infrabox-acceptance-' + uuid.uuid4().hex[:10]
repo = api('POST', '/user/repos', {'name': name, 'private': True, 'auto_init': True})
path = '/repos/' + config['username'] + '/' + name
key = None
try:
    with tempfile.TemporaryDirectory(prefix='infrabox-acceptance-') as temporary:
        work = Path(temporary)
        environment = dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.extraHeader',
                           GIT_CONFIG_VALUE_0='Authorization: ' + authorization, GIT_TERMINAL_PROMPT='0')
        run(['git', 'clone', base + '/' + config['username'] + '/' + name + '.git', str(work / 'https')], env=environment)
        (work / 'https' / 'https-test.txt').write_text('InfraBox HTTPS acceptance\n')
        run(['git', '-C', str(work / 'https'), 'add', 'https-test.txt'])
        run(['git', '-C', str(work / 'https'), '-c', 'user.name=InfraBox acceptance', '-c', 'user.email=acceptance@' + domain, 'commit', '-m', 'Test HTTPS push'])
        run(['git', '-C', str(work / 'https'), 'push'], env=environment)
        print('Private Git HTTPS clone and push passed.', flush=True)
        run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(work / 'id')])
        key = api('POST', '/user/keys', {'title': name, 'key': (work / 'id.pub').read_text()})
        # Trust the server key read locally from the running, authenticated VM.
        hostkeys = run(['ssh-keyscan', '-p', '2222', '127.0.0.1'])
        (work / 'known_hosts').write_text(hostkeys)
        ssh = f'ssh -i {work}/id -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile={work}/known_hosts'
        run(['git', 'clone', 'ssh://git@127.0.0.1:2222/' + config['username'] + '/' + name + '.git', str(work / 'ssh')],
            env=dict(os.environ, GIT_SSH_COMMAND=ssh))
        (work / 'ssh' / 'ssh-test.txt').write_text('InfraBox SSH acceptance\n')
        run(['git', '-C', str(work / 'ssh'), 'add', 'ssh-test.txt'])
        run(['git', '-C', str(work / 'ssh'), '-c', 'user.name=InfraBox acceptance', '-c', 'user.email=acceptance@' + domain, 'commit', '-m', 'Test SSH push'])
        run(['git', '-C', str(work / 'ssh'), 'push'], env=dict(os.environ, GIT_SSH_COMMAND=ssh))
        print('Private Git SSH clone and push on port 2222 passed.', flush=True)
        workflow = '''name: InfraBox acceptance
on: [push]
jobs:
  smoke:
    runs-on: infrabox-shell
    steps:
      - name: Check container execution and permitted HTTPS
        run: |
          git --version
          test ! -S /var/run/docker.sock
          test ! -S /run/podman/podman.sock
          wget -q -O /dev/null https://git.DOMAIN/api/healthz
          wget -q -O /dev/null https://netbox.DOMAIN/login/
'''.replace('DOMAIN', domain)
        api('POST', path + '/contents/.gitea/workflows/acceptance.yml',
            {'content': base64.b64encode(workflow.encode()).decode(), 'message': 'Exercise isolated InfraBox runner'})
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = api('GET', path + '/actions/runs')
            runs = result.get('workflow_runs', result.get('runs', []))
            if runs and runs[0].get('status') == 'completed':
                if runs[0]['conclusion'] != 'success':
                    jobs = api('GET', path + '/actions/runs/' + str(runs[0]['id']) + '/jobs')
                    details = []
                    for job in jobs.get('jobs', []):
                        request = Request(base + '/api/v1' + path + '/actions/jobs/' + str(job['id']) + '/logs', headers={'Authorization': authorization})
                        with urlopen(request, context=context, timeout=30) as response:
                            details.append(response.read().decode(errors='replace')[-6000:])
                    raise RuntimeError('Acceptance workflow failed: ' + '\n'.join(details))
                print('Gitea Actions job completed successfully on infrabox-shell.', flush=True)
                break
            time.sleep(3)
        else:
            raise RuntimeError('Acceptance workflow timed out')
finally:
    if key:
        api('DELETE', '/user/keys/' + str(key['id']))
    api('DELETE', path)

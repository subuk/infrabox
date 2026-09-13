#!/usr/bin/env python3
"""One-time Gitea dispatch/checkout/artifact gate. Credentials arrive on stdin."""
import base64
from datetime import datetime, timezone
import io
import json
import re
import ssl
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
import zipfile


class GateError(RuntimeError):
    pass


class SameOrigin(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urlsplit(request.full_url)[:2] != urlsplit(newurl)[:2]:
            raise GateError('Artifact redirect left the local Gitea origin')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def verify_archive(data, revision):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist() != ['compatibility.txt']:
            raise GateError('Unexpected artifact contents')
        if archive.getinfo('compatibility.txt').file_size != 41:
            raise GateError('Unexpected artifact size')
        if archive.read('compatibility.txt').decode() != revision + '\n':
            raise GateError('Downloaded checkout SHA differs from dispatched SHA')


def verify_discovery_archive(data, revision, run_id, expected):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not {'summary.md', 'run.json'} <= set(names):
            raise GateError('Missing or duplicate discovery report')
        if any(name not in ('summary.md', 'run.json') and not re.fullmatch(r'facts/(device|vm)-[1-9][0-9]*\.json', name)
               for name in names):
            raise GateError('Unexpected discovery artifact file')
        if sum(item.file_size for item in archive.infolist()) > 32 * 1024 * 1024:
            raise GateError('Discovery artifact exceeds acceptance size limit')
        manifest = json.loads(archive.read('run.json'))
        if manifest['revision'] != revision or str(manifest['run_id']) != str(run_id):
            raise GateError('Discovery artifact does not match the dispatched run')
        if manifest['outcome'] != expected:
            raise GateError('Discovery outcome differs from expected acceptance outcome')
        counts = {'selected': len(manifest['hosts'])}
        counts.update({status: sum(h['status'] == status for h in manifest['hosts'])
                       for status in ('succeeded', 'failed', 'unreachable', 'not_completed')})
        if counts != manifest['counts'] or (expected == 'success' and counts['succeeded'] == 0):
            raise GateError('Invalid discovery host counts')
        for host in manifest['hosts']:
            if host['status'] == 'succeeded':
                facts = json.loads(archive.read(host['file']))
                if not isinstance(facts, dict) or not facts:
                    raise GateError('Successful host has no native facts')
                if any(key in ('ansible_env', 'ansible_local', 'env', 'local', 'facter', 'ohai') or
                       key.startswith(('facter_', 'ohai_')) for key in facts):
                    raise GateError('Excluded fact family was published')
        return {'counts': manifest['counts'], 'collection_outcome': manifest['outcome'],
                'hosts': [{'name': h['name'], 'status': h['status'], 'object_id': h['object_id']}
                          for h in manifest['hosts']]}


def run(c, report):
    base = c['gitea_url'].rstrip('/')
    if urlsplit(base).scheme != 'https':
        raise GateError('Verified HTTPS required')
    for name in ('organization', 'repository', 'branch'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', c[name]):
            raise GateError('Invalid repository configuration')
    auth = 'Basic ' + base64.b64encode((c['username'] + ':' + c['password']).encode()).decode()
    opener = build_opener(ProxyHandler({}), SameOrigin(), HTTPSHandler(
        context=ssl.create_default_context(cafile=c['ca'])))
    repo = '/api/v1/repos/' + c['organization'] + '/' + c['repository']
    workflow = c.get('workflow', 'compatibility.yml')
    expected = c.get('expected_outcome', 'success')
    if workflow not in ('compatibility.yml', 'discover.yml'):
        raise GateError('Unknown acceptance workflow')
    if workflow == 'discover.yml' and not c.get('targets', '').strip():
        raise GateError('Explicit authorized acceptance targets required')

    def request(path, data=None, binary=False):
        url = urljoin(base, path)
        if urlsplit(base)[:2] != urlsplit(url)[:2]:
            raise GateError('API URL left the local Gitea origin')
        try:
            with opener.open(Request(url, json.dumps(data).encode() if data is not None else None,
                    {'Authorization': auth, 'Content-Type': 'application/json'}), timeout=30) as response:
                limit = 32 * 1024 * 1024 if binary and workflow == 'discover.yml' else 1024 * 1024
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise GateError('Acceptance response exceeds size limit')
                return body if binary else json.loads(body)
        except HTTPError as error:
            raise GateError('Gitea compatibility HTTP ' + str(error.code)) from None

    revision = request(repo + '/branches/' + c['branch'])['commit']['id']
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise GateError('Invalid source revision')
    report['revision'] = revision
    payload = {'ref': c['branch']}
    if workflow == 'discover.yml':
        payload['inputs'] = {'targets': c['targets']}
    details = request(repo + '/actions/workflows/' + workflow + '/dispatches?return_run_details=true', payload)
    run_id = int(details['workflow_run_id'])
    report.update(run_id=run_id, run_url=details['html_url'])
    deadline = time.monotonic() + (1260 if workflow == 'discover.yml' else 420)
    while time.monotonic() < deadline:
        result = request(repo + '/actions/runs/' + str(run_id))
        if result['head_sha'] != revision:
            raise GateError('Dispatch raced a source update')
        if result['status'] == 'completed':
            if result['conclusion'] != ('success' if expected == 'success' else 'failure'):
                raise GateError('Workflow conclusion differs from expected acceptance outcome')
            break
        time.sleep(5)
    else:
        raise GateError('Compatibility run timed out; inspect its retained run')
    artifacts = request(repo + '/actions/runs/' + str(run_id) + '/artifacts')['artifacts']
    matches = [a for a in artifacts if not a['expired'] and
               (a['name'] == 'platform-compatibility' if workflow == 'compatibility.yml'
                else a['name'].startswith(f'discovery-{run_id}-'))]
    if len(matches) != 1:
        raise GateError('Expected one retained compatibility artifact')
    artifact_id = int(matches[0]['id'])
    data = request(repo + '/actions/artifacts/' + str(artifact_id) + '/zip', binary=True)
    if workflow == 'compatibility.yml':
        verify_archive(data, revision)
    else:
        report.update(verify_discovery_archive(data, revision, run_id, expected))
    report.update(outcome='passed', artifact_id=artifact_id,
                  checks=['manual_dispatch', 'exact_sha_checkout', 'artifact_upload_and_download'])


if __name__ == '__main__':
    report = {'outcome': 'failed', 'checked_at': datetime.now(timezone.utc).isoformat()}
    try:
        run(json.load(sys.stdin), report)
    except Exception as error:
        report['reason'] = str(error) if isinstance(error, GateError) else type(error).__name__
    print(json.dumps(report))
    sys.exit(0 if report['outcome'] == 'passed' else 1)

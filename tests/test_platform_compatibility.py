import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
from urllib.error import HTTPError
from urllib.request import Request

spec = importlib.util.spec_from_file_location('platform_gate', Path(__file__).resolve().parents[1] / 'scripts/test-platform-compatibility.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class CompatibilityTests(unittest.TestCase):
    def test_missing_fixture_never_dispatches_and_uncertain_dispatch_is_not_repeated(self):
        config = {'gitea_url': 'https://git.example.com', 'organization': 'project',
                  'repository': 'automation', 'branch': 'master', 'username': 'fixture',
                  'password': 'disposable-fixture', 'ca': '/unused/ca.pem'}
        for missing in (True, False):
            with self.subTest(missing_fixture=missing):
                methods, report = [], {}
                class Opener:
                    def open(self, request, timeout):
                        methods.append(request.get_method())
                        if '/branches/' in request.full_url:
                            return io.BytesIO(json.dumps({'commit': {'id': 'a' * 40}}).encode())
                        if '/contents/' in request.full_url:
                            if missing:
                                raise HTTPError(request.full_url, 404, 'missing fixture', {}, None)
                            return io.BytesIO(b'{"type":"file"}')
                        raise HTTPError(request.full_url, 503, 'uncertain server result', {}, None)
                with patch.object(gate, 'build_opener', return_value=Opener()), patch.object(gate.ssl, 'create_default_context', return_value=None):
                    with self.assertRaises(gate.GateError):
                        gate.run(config, report)
                self.assertEqual(methods.count('POST'), 0 if missing else 1)
                self.assertEqual(report['dispatch_status'], 'not_attempted' if missing else 'uncertain')
                self.assertNotIn('run_id', report)

    def archive(self, files):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for path, data in files.items():
                archive.writestr(path, data)
        return stream.getvalue()

    def test_downloaded_artifact_must_contain_exact_dispatch_sha(self):
        revision = 'a' * 40
        gate.verify_archive(self.archive({'compatibility.txt': revision + '\n'}), revision)
        for files in ({'compatibility.txt': 'b' * 40 + '\n'},
                      {'compatibility.txt': revision + '\n', 'extra': 'unexpected'},
                      {'../compatibility.txt': revision + '\n'}):
            with self.assertRaises(gate.GateError):
                gate.verify_archive(self.archive(files), revision)

    def test_authenticated_redirect_cannot_leave_gitea(self):
        request = Request('https://git.example.com/api/artifact', headers={'Authorization': 'fixture'})
        with self.assertRaises(gate.GateError):
            gate.SameOrigin().redirect_request(request, None, 302, '', {}, 'https://other.example.com/blob')

    def test_native_facts_download_checks_run_identity_and_confidentiality(self):
        revision = 'a' * 40
        manifest = {'revision': revision, 'run_id': '42', 'outcome': 'success',
                    'hosts': [{'name': 'testbox', 'status': 'succeeded', 'object_id': 12, 'file': 'facts/device-12.json'}],
                    'counts': {'selected': 1, 'succeeded': 1, 'failed': 0, 'unreachable': 0, 'not_completed': 0}}
        files = {'run.json': json.dumps(manifest), 'summary.md': 'fixture',
                 'facts/device-12.json': json.dumps({'ansible_kernel': 'native'})}
        result = gate.verify_discovery_archive(self.archive(files), revision, 42, 'success')
        self.assertEqual(result['hosts'][0]['name'], 'testbox')
        with self.assertRaises(gate.GateError):
            gate.verify_discovery_archive(self.archive(files), revision, 43, 'success')
        files['facts/device-12.json'] = json.dumps({'ansible_env': {'SECRET': 'fixture'}})
        with self.assertRaises(gate.GateError):
            gate.verify_discovery_archive(self.archive(files), revision, 42, 'success')

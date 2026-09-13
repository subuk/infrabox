import importlib.util
import io
import json
from pathlib import Path
import unittest
import zipfile
from urllib.request import Request

spec = importlib.util.spec_from_file_location('platform_gate', Path(__file__).resolve().parents[1] / 'scripts/test-platform-compatibility.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class CompatibilityTests(unittest.TestCase):
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

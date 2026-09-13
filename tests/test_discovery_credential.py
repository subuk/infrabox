import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('discovery_credential', Path('roles/openclaw/files/discovery-credential.py'))
credential = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(credential)


class DiscoveryCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'discovery-token'
        self.m = credential.Manager.__new__(credential.Manager)
        self.m.c = {'action': 'provision', 'username': 'discovery', 'organization': 'platform',
                    'repository': 'automation', 'token_file': str(self.path),
                    'uid': os.getuid(), 'gid': os.getgid()}
        self.m.changed = False
        self.m.identity = lambda configure: None
        self.valid = {'healthy', 'replacement'}
        self.m.valid = lambda value: value in self.valid
        self.record = None
        self.calls = []
        self.m.bao = self.bao
        self.m.api = self.api
        self.m.pages = lambda path: [{'id': 1, 'name': 'infrabox-discovery-old'},
                                      {'id': 2, 'name': 'infrabox-discovery-new', 'scopes': ['read:user', 'write:repository']},
                                      {'id': 3, 'name': 'unrelated'}]

    def existing(self, value='healthy'):
        self.record = {'data': {'data': {'apiToken': value, 'tokenId': 2, 'username': 'discovery',
                       'repository': 'platform/automation', 'operatorNote': 'preserve'}, 'metadata': {'version': 7}}}
        self.path.write_text(value + '\n')
        self.path.chmod(0o600)

    def bao(self, data=None):
        if data is None:
            return self.record
        self.calls.append(('bao', data))
        version = self.record['data']['metadata']['version'] if self.record else 0
        self.assertEqual(data['options']['cas'], version)
        self.record = {'data': {'data': data['data'], 'metadata': {'version': version + 1}}}

    def api(self, path, data=None, method='GET', **kwargs):
        self.calls.append((method, path))
        if method == 'POST':
            self.assertEqual(data['scopes'], ['read:user', 'write:repository'])
            return {'id': 2, 'sha1': 'replacement'}
        return {}

    def test_healthy_rerun_preserves_runtime_and_openbao(self):
        self.existing()
        st = self.path.stat()
        self.assertFalse(self.m.run()['changed'])
        self.assertEqual(st.st_mtime_ns, self.path.stat().st_mtime_ns)
        self.assertEqual(st.st_ino, self.path.stat().st_ino)
        self.assertEqual(self.calls, [])

    def test_replacement_published_after_validation_and_retired_only_on_finalize(self):
        self.existing('revoked')
        self.assertTrue(self.m.run()['changed'])
        self.assertEqual(self.path.read_text(), 'replacement\n')
        self.assertEqual(self.record['data']['data']['operatorNote'], 'preserve')
        self.assertFalse(any(c[0] == 'DELETE' for c in self.calls))
        self.m.changed = False
        self.m.c['action'] = 'finalize'
        self.assertTrue(self.m.run()['changed'])
        self.assertEqual([c for c in self.calls if c[0] == 'DELETE'], [('DELETE', '/users/discovery/tokens/1')])

    def test_failed_replacement_validation_preserves_existing_credentials(self):
        self.existing('revoked')
        self.valid.clear()
        with self.assertRaises(credential.ManagementError):
            self.m.run()
        self.assertEqual(self.path.read_text(), 'revoked\n')
        self.assertEqual(self.record['data']['metadata']['version'], 7)

    def test_interrupted_runtime_publication_reuses_openbao_replacement(self):
        self.existing('revoked')
        with patch.object(credential, 'atomic', side_effect=OSError('interruption')):
            with self.assertRaises(OSError):
                self.m.run()
        self.calls.clear()
        self.m.changed = False
        self.assertTrue(self.m.run()['changed'])
        self.assertEqual(self.path.read_text(), 'replacement\n')
        self.assertEqual(self.calls, [])

    def test_verify_and_finalize_never_repair_or_retire_mismatched_runtime(self):
        self.existing()
        self.path.write_text('different\n')
        for action in ['verify', 'finalize']:
            self.m.c['action'] = action
            with self.assertRaises(credential.ManagementError):
                self.m.run()
        self.assertEqual(self.calls, [])

    def test_namespace_identity_mismatch_is_not_overwritten(self):
        self.existing()
        self.record['data']['data']['repository'] = 'other/repo'
        with self.assertRaises(credential.ManagementError):
            self.m.run()
        self.assertEqual(self.calls, [])

    def test_excess_token_scopes_require_replacement(self):
        self.existing()
        self.m.pages = lambda path: [{'id': 2, 'name': 'infrabox-discovery-old', 'scopes': ['all']}]
        self.assertTrue(self.m.run()['changed'])
        self.assertEqual(self.path.read_text(), 'replacement\n')
        self.assertEqual(self.record['data']['metadata']['version'], 8)

    def test_live_validation_rejects_unrelated_repository_grants(self):
        self.m.api = lambda path, **kwargs: {'login': 'discovery', 'is_admin': False}
        self.m.pages = lambda path, **kwargs: [{'full_name': 'other/repository'}]
        with self.assertRaisesRegex(credential.ManagementError, 'unexpected repository membership'):
            credential.Manager.valid(self.m, 'healthy')

    def test_live_validation_rejects_execution_code_write(self):
        self.m.repo = '/repos/platform/automation'
        self.m.api = lambda path, **kwargs: ({'login': 'discovery', 'is_admin': False}
            if path == '/user' else {'permissions': {'pull': True, 'push': True, 'admin': False}})
        self.m.pages = lambda path, **kwargs: [{'full_name': 'platform/automation'}]
        with self.assertRaisesRegex(credential.ManagementError, 'modify execution code'):
            credential.Manager.valid(self.m, 'healthy')

    def test_private_file_mode_is_repaired_without_rotation(self):
        self.existing()
        self.path.chmod(0o644)
        self.assertTrue(self.m.run()['changed'])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()

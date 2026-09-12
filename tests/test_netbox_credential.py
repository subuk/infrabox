import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('netbox_credential',
    Path(__file__).resolve().parents[1] / 'roles/openclaw/files/netbox-credential.py')
credential = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(credential)


class CredentialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'secrets/netbox-token'
        self.path.parent.mkdir()
        self.config = {'action': 'provision', 'token_file': str(self.path), 'mount': 'kv',
                       'uid': os.getuid(), 'gid': os.getgid()}
        self.marker = self.path.parent.parent / 'netbox-restart-required'
        self.record = None
        self.calls = []
        self.valid = {'healthy-fixture', 'new-fixture'}
        self.fail_validation = False

    def bao(self, method, path, data=None):
        self.calls.append(('bao', method))
        if method == 'GET':
            return self.record
        expected_version = self.record['data']['metadata']['version'] if self.record else 0
        self.assertEqual(data['options']['cas'], expected_version)
        self.record = {'data': {'data': data['data'], 'metadata': {'version': expected_version + 1}}}

    def netbox(self, action, token):
        self.calls.append(('netbox', action))
        if action == 'inspect':
            return {'valid': token in self.valid}
        if action == 'create':
            return {'token': 'new-fixture'}
        if action == 'finalize':
            return {'changed': False}
        self.fail('Unexpected action')

    def validate(self, token):
        if self.fail_validation:
            raise RuntimeError('TLS unavailable')
        self.assertIn(token, self.valid)

    def run_action(self, action='provision'):
        self.config['action'] = action
        # macOS non-root CI cannot chown files to root, including markers.
        with patch.object(credential.os, 'fchown'):
            return credential.manage(self.config, self.bao, self.netbox, self.validate)

    def existing(self, value='healthy-fixture'):
        self.record = {'data': {'data': {'apiToken': value, 'operatorNote': 'preserve'},
                                'metadata': {'version': 7}}}
        self.path.write_text(value + '\n')
        self.path.chmod(0o600)

    def test_healthy_rerun_preserves_token_file_and_vault_version(self):
        self.existing()
        stat = self.path.stat()
        self.assertFalse(self.run_action()['changed'])
        self.assertEqual(self.path.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertEqual(self.record['data']['metadata']['version'], 7)
        self.assertNotIn(('netbox', 'create'), self.calls)
        self.assertFalse(self.marker.exists())

    def test_missing_runtime_materializes_vault_without_rotation(self):
        self.existing()
        self.path.unlink()
        self.assertTrue(self.run_action()['changed'])
        self.assertEqual(self.path.read_text(), 'healthy-fixture\n')
        self.assertTrue(self.marker.exists())
        self.assertNotIn(('netbox', 'create'), self.calls)

    def test_invalid_token_replacement_requires_finalization(self):
        self.existing('revoked-fixture')
        self.assertTrue(self.run_action()['changed'])
        self.assertEqual(self.record['data']['metadata']['version'], 8)
        self.assertEqual(self.record['data']['data']['operatorNote'], 'preserve')
        self.assertEqual(self.path.read_text(), 'new-fixture\n')
        self.assertTrue(self.marker.exists())
        self.assertNotIn(('netbox', 'finalize'), self.calls)
        self.assertTrue(self.run_action('finalize')['changed'])
        self.assertFalse(self.marker.exists())

    def test_https_failure_does_not_replace_runtime_or_vault(self):
        self.existing('revoked-fixture')
        self.fail_validation = True
        with self.assertRaises(RuntimeError):
            self.run_action()
        self.assertEqual(self.path.read_text(), 'revoked-fixture\n')
        self.assertEqual(self.record['data']['metadata']['version'], 7)
        self.assertFalse(self.marker.exists())

    def test_interrupted_materialization_resumes_without_rotation(self):
        self.existing('revoked-fixture')
        original = credential.atomic
        def interrupt(path, *args):
            if path == self.path:
                raise OSError('interrupted')
            return original(path, *args)
        with patch.object(credential, 'atomic', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.run_action()
        self.assertTrue(self.marker.exists())
        self.calls.clear()
        self.assertTrue(self.run_action()['changed'])
        self.assertNotIn(('netbox', 'create'), self.calls)
        self.assertEqual(self.path.read_text(), 'new-fixture\n')

    def test_finalize_does_not_retire_when_runtime_mismatches(self):
        self.existing()
        self.path.write_text('different-fixture\n')
        with self.assertRaises(credential.ManagementError):
            self.run_action('finalize')
        self.assertNotIn(('netbox', 'finalize'), self.calls)

    def test_verify_is_nonmutating(self):
        self.existing()
        self.assertFalse(self.run_action('verify')['changed'])
        self.assertEqual(self.calls, [('bao', 'GET'), ('netbox', 'inspect')])


if __name__ == '__main__':
    unittest.main()

"""Directory parsing must not split or corrupt stable identity/profile fields."""
import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'identity_openbao', Path(__file__).resolve().parents[1] / 'roles/identity_openbao/files/configure.py')
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class IdentityInputTests(unittest.TestCase):
    def test_folded_unicode_and_multiple_records(self):
        name = base64.b64encode('Человек'.encode()).decode()
        records = identity.ldif_records('dn: uid=first,dc=example\nentryUUID: stable-\n uuid\ndisplayName:: '
                                       + name[:4] + '\n ' + name[4:] + '\n\nuid: second\n')
        self.assertEqual(records[0]['entryuuid'], ['stable-uuid'])
        self.assertEqual(records[0]['displayname'], ['Человек'])
        self.assertEqual(records[1]['uid'], ['second'])

    def test_external_values_cannot_read_controller_files(self):
        with self.assertRaises(RuntimeError):
            identity.ldif_records('mail:< file:///etc/passwd\n')

    def test_state_is_private_atomic_and_stable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            self.assertTrue(identity.save_json(path, {'method': 'retained'}))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(identity.save_json(path, {'method': 'retained'}))

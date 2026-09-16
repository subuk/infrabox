import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        for source, target in [('configure.py', 'openbao-configure.py'), ('reset-totp.py', 'reset-totp.py')]:
            shutil.copyfile(Path('roles/identity_openbao/files') / source, directory / target)
        (directory / 'openbao-state.json').write_text(json.dumps({'method_id': 'method'}))
        spec = importlib.util.spec_from_file_location('reset_totp', directory / 'reset-totp.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.parameters = {'identity': {'directory': str(directory)}, 'username': 'personal'}

    def test_service_or_missing_human_never_reaches_management(self):
        with patch.object(self.module.configuration, 'humans', return_value=[]), patch.object(self.module.configuration, 'Bao') as bao:
            with self.assertRaisesRegex(RuntimeError, 'exactly one current human'):
                self.module.reset(self.parameters)
            bao.assert_not_called()

    def test_uuid_mismatch_never_resets_mfa(self):
        api = Mock()
        api.api.side_effect = [{'ldap-human/': {'accessor': 'ldap'}}, {'id': 'entity', 'aliases': [{'name': 'foreign', 'mount_accessor': 'ldap'}]}]
        with patch.object(self.module.configuration, 'humans', return_value=[{'username': 'personal', 'uuid': 'stable'}]), patch.object(self.module.configuration, 'Bao', return_value=api):
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                self.module.reset(self.parameters)
            self.assertEqual(api.api.call_count, 2)

    def test_reset_is_limited_to_the_canonical_human_and_login_prefixes(self):
        api = Mock()
        api.api.side_effect = [{'ldap-human/': {'accessor': 'ldap'}}, {'id': 'entity', 'aliases': [{'name': 'stable', 'mount_accessor': 'ldap'}]}, None, None, None]
        with patch.object(self.module.configuration, 'humans', return_value=[{'username': 'personal', 'uuid': 'stable'}]), patch.object(self.module.configuration, 'Bao', return_value=api):
            result = self.module.reset(self.parameters)
        calls = [call.args for call in api.api.call_args_list]
        self.assertEqual(calls[1], ('POST', 'identity/lookup/entity', {'alias_name': 'stable', 'alias_mount_accessor': 'ldap'}))
        self.assertEqual(calls[2], ('POST', 'identity/mfa/method/totp/admin-destroy', {'method_id': 'method', 'entity_id': 'entity'}))
        self.assertEqual([call[1] for call in calls[3:]], ['sys/leases/revoke-prefix/auth/ldap-human/login/personal', 'sys/leases/revoke-prefix/auth/ldap-enrollment/login/personal'])
        self.assertTrue(result['application_sessions_require_separate_revocation'])

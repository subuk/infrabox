import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('openclaw_token', Path(__file__).parents[1] / 'roles/openclaw/files/openbao-token.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PeriodicTokenContract(unittest.TestCase):
    def setUp(self):
        self.token = dict(renewable=True, orphan=True, type='service',
                          policies=['infrabox-openclaw'], period=604800,
                          explicit_max_ttl=0, ttl=600)

    def test_healthy_token_survives_rerun(self):
        self.assertTrue(module.matches(self.token, module.seconds('168h')))

    def test_expired_and_wrong_identity_require_replacement(self):
        for field, value in [('renewable', False), ('orphan', False), ('type', 'batch'),
                             ('policies', ['infrabox-openclaw', 'default']),
                             ('policies', ['root']), ('period', 3600),
                             ('explicit_max_ttl', 86400), ('ttl', 0)]:
            with self.subTest(field=field, value=value):
                self.assertFalse(module.matches(dict(self.token, **{field: value}), 604800))

class TokenProvisioning(unittest.TestCase):
    def test_healthy_token_is_preserved_without_creation(self):
        self.exercise(valid=True)

    def test_wrong_period_replaces_atomically_and_defers_revocation(self):
        self.exercise(valid=False)

    def test_invalid_replacement_preserves_old_credential(self):
        self.exercise(valid=False, invalid_new=True)

    def test_never_revoke_management_root_token(self):
        self.exercise(valid=True, root_old=True)

    def test_missing_token_is_created_with_persistent_restart_requirement(self):
        self.exercise(valid=False, missing=True)

    def test_wrong_policy_without_lookup_self_is_retired_after_replacement(self):
        self.exercise(valid=False, denied_self=True)

    def test_rerun_preserves_pending_restart_for_service_stage(self):
        self.exercise(valid=True, pending_restart=True)

    def test_openbao_forbidden_lookup_of_expired_token_is_repaired(self):
        self.exercise(valid=False, denied_self=True, expired=True)

    def exercise(self, valid, invalid_new=False, root_old=False, missing=False, denied_self=False, pending_restart=False, expired=False):
        import contextlib
        import io
        import json
        import os
        import tempfile
        from unittest.mock import patch
        healthy = dict(renewable=True, orphan=True, type='service',
                       policies=['infrabox-openclaw'], period=604800,
                       explicit_max_ttl=0, ttl=600, accessor='old-accessor')
        requests = []
        class Response:
            status = 200
            def __init__(self, body):
                self.body = body
            def read(self):
                return json.dumps(self.body).encode()
        class FakeConnection:
            def __init__(self, *args, **kwargs):
                pass
            def request(self, method, path, body, headers):
                requests.append((method, path, body, headers))
                if path.endswith('lookup-self'):
                    data = dict(healthy)
                    if headers['X-Vault-Token'] == 'old-token' and root_old:
                        data['policies'] = ['root']
                    if headers['X-Vault-Token'] == 'old-token' and not valid:
                        data['period'] = 3600
                    if headers['X-Vault-Token'] == 'new-token' and invalid_new:
                        data['policies'] = ['root']
                    self.response = Response({'data': data})
                    if denied_self and headers['X-Vault-Token'] == 'old-token':
                        self.response.status = 403
                elif path.endswith('auth/token/lookup'):
                    self.response = Response({'data': dict(healthy, policies=['legacy-openclaw'])})
                    if expired:
                        self.response.status = 403
                elif path.endswith('create/infrabox-openclaw'):
                    self.response = Response({'auth': {'client_token': 'new-token'}})
                elif path.endswith('revoke'):
                    self.response = Response({})
                else:
                    raise AssertionError('Unexpected API endpoint')
            def getresponse(self):
                return self.response
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'secrets', 'vault-token')
            path.parent.mkdir()
            if not missing:
                path.write_text('old-token\n')
            inode = path.stat().st_ino if path.exists() else None
            if pending_restart:
                Path(directory, 'restart-required').write_text('pending')
            c = dict(action='provision', token_file=str(path), period='168h',
                     root_token='controller-test-token', socket='unused', uid=os.getuid(), gid=os.getgid())
            with patch.object(module.http.client, 'HTTPConnection', FakeConnection), contextlib.redirect_stdout(io.StringIO()):
                if root_old:
                    with self.assertRaisesRegex(RuntimeError, 'root token'):
                        module.main(c)
                elif invalid_new:
                    with self.assertRaisesRegex(RuntimeError, 'required contract'):
                        module.main(c)
                else:
                    module.main(c)
            if valid or invalid_new:
                self.assertEqual(path.read_text(), 'old-token\n')
                self.assertEqual(path.stat().st_ino, inode)
                self.assertFalse(Path(directory, 'superseded-token-accessor').exists())
                self.assertEqual(Path(directory, 'restart-required').exists(), pending_restart)
            else:
                self.assertEqual(path.read_text(), 'new-token\n')
                self.assertNotEqual(path.stat().st_ino, inode)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                if missing or expired:
                    self.assertFalse(Path(directory, 'superseded-token-accessor').exists())
                else:
                    self.assertEqual(Path(directory, 'superseded-token-accessor').read_text(), 'old-accessor')
                self.assertTrue(Path(directory, 'restart-required').exists())
            if valid:
                self.assertEqual([req[0] for req in requests], ['GET'])
            elif invalid_new:
                self.assertEqual(json.loads(requests[-1][2]), {'token': 'new-token'})
            else:
                self.assertFalse(any(req[1].endswith('revoke') for req in requests))

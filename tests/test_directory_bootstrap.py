"""Completed directory bootstrap must not restore operator-removed authority."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'directory_bootstrap', Path(__file__).resolve().parents[1] / 'roles/lldap/files/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ExistingDirectory:
    def __init__(self, users):
        self.users = users

    def graphql(self, query, variables=None):
        if query.startswith('{schema'):
            return {'schema': {'userSchema': {'attributes': [{
                'name': 'infraboxidentitytype', 'attributeType': 'STRING',
                'isList': False, 'isVisible': True, 'isEditable': False,
            }]}}}
        if query.startswith('{groups'):
            return {'groups': [{'id': 1, 'displayName': 'infrabox:gitea:admin'}]}
        if query.startswith('{users'):
            return {'users': self.users}
        raise AssertionError('Completed bootstrap attempted a directory mutation')

    def set_initial_password(self, *args):
        raise AssertionError('Completed bootstrap attempted to reset a password')


class DirectoryBootstrapTests(unittest.TestCase):
    def run_existing(self, users):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'state.json'
            marker.write_text(json.dumps({'users': {'operator': {'uuid': 'original', 'complete': True}}}))
            parameters = {
                'role_groups': ['infrabox:gitea:admin'],
                'users': [{'username': 'operator', 'type': 'human', 'password': 'old initial value',
                           'groups': ['infrabox:gitea:admin']}],
            }
            return bootstrap.bootstrap(ExistingDirectory(users), parameters, marker)

    def test_rotated_password_and_removed_membership_are_untouched(self):
        self.assertFalse(self.run_existing([{'id': 'operator', 'uuid': 'original', 'groups': []}])['changed'])

    def test_intentionally_deleted_identity_stays_deleted(self):
        self.assertFalse(self.run_existing([])['changed'])

    def test_replaced_identity_requires_review(self):
        with self.assertRaisesRegex(RuntimeError, 'UUID changed'):
            self.run_existing([{'id': 'operator', 'uuid': 'replacement'}])

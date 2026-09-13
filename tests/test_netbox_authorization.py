"""The service boundary must deny implicit grants while preserving human access."""
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from jinja2 import Environment
import json


class PermissionDenied(Exception):
    pass


DEFAULTS = {'users.add_token': [{'user': '$user'}], 'extras.delete_bookmark': [{'user': '$user'}]}


class StockBackend:
    def get_object_permissions(self, user):
        return {**DEFAULTS, 'dcim.add_device': [None]}

    def has_perm(self, user, perm, obj=None):
        return perm in self.get_object_permissions(user)


class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modules = {}
        for name in ('django', 'django.conf', 'django.core', 'django.core.exceptions',
                     'netbox', 'netbox.authentication'):
            modules[name] = ModuleType(name)
        modules['django.conf'].settings = SimpleNamespace(DEFAULT_PERMISSIONS=DEFAULTS)
        modules['django.core.exceptions'].PermissionDenied = PermissionDenied
        modules['netbox.authentication'].ObjectPermissionBackend = StockBackend
        template = Path(__file__).resolve().parents[1] / 'roles/netbox/templates/infrabox_auth.py.j2'
        environment = Environment()
        environment.filters['to_json'] = json.dumps
        environment.filters['bool'] = bool
        code = environment.from_string(template.read_text()).render(netbox_openclaw_username='infrabox-openclaw', platform_enabled=True)
        namespace = {}
        with patch.dict(sys.modules, modules):
            exec(compile(code, str(template), 'exec'), namespace)
        cls.backend = namespace['InfraBoxObjectPermissionBackend']()

    def user(self, name):
        return SimpleNamespace(get_username=lambda: name)

    def test_service_cannot_reach_fallback_implicit_grants(self):
        user = self.user('infrabox-openclaw')
        for permission in DEFAULTS:
            with self.assertRaises(PermissionDenied):
                self.backend.has_perm(user, permission)
        self.assertEqual(self.backend.get_object_permissions(user), {'dcim.add_device': [None]})

    def test_allowed_service_actions_still_require_object_permissions(self):
        user = self.user('infrabox-openclaw')
        self.assertTrue(self.backend.has_perm(user, 'dcim.add_device'))
        self.assertFalse(self.backend.has_perm(user, 'dcim.delete_device'))
        self.assertFalse(self.backend.has_perm(user, 'users.add_user'))

    def test_platform_cannot_reach_fallback_implicit_grants(self):
        user = self.user('infrabox-platform')
        for permission in DEFAULTS:
            with self.assertRaises(PermissionDenied):
                self.backend.has_perm(user, permission)
        self.assertEqual(self.backend.get_object_permissions(user), {'dcim.add_device': [None]})

    def test_human_self_service_is_preserved(self):
        user = self.user('human')
        for permission in DEFAULTS:
            self.assertTrue(self.backend.has_perm(user, permission))
        self.assertEqual(self.backend.get_object_permissions(user), StockBackend().get_object_permissions(user))


if __name__ == '__main__':
    unittest.main()

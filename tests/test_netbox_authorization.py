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
                     'django.contrib', 'django.contrib.auth', 'django.contrib.auth.backends',
                     'social_core', 'social_core.exceptions', 'netbox', 'netbox.authentication'):
            modules[name] = ModuleType(name)
        modules['django.conf'].settings = SimpleNamespace(DEFAULT_PERMISSIONS=DEFAULTS)
        modules['django.core.exceptions'].PermissionDenied = PermissionDenied
        modules['netbox.authentication'].ObjectPermissionBackend = StockBackend
        modules['netbox.authentication'].RemoteUserBackend = StockBackend
        modules['django.contrib.auth.backends'].BaseBackend = object
        modules['social_core.exceptions'].AuthForbidden = PermissionDenied
        template = Path(__file__).resolve().parents[1] / 'roles/netbox/templates/infrabox_auth.py.j2'
        environment = Environment()
        environment.filters['to_json'] = json.dumps
        environment.filters['bool'] = bool
        code = environment.from_string(template.read_text()).render(netbox_openclaw_username='svc-openclaw', platform_enabled=True)
        catalog = ModuleType('infrabox_catalog')
        exec(Path('roles/netbox/files/catalog.py').read_text(), catalog.__dict__)
        modules['infrabox_catalog'] = catalog
        namespace = {}
        with patch.dict(sys.modules, modules):
            exec(compile(code, str(template), 'exec'), namespace)
        cls.backend = namespace['InfraBoxObjectPermissionBackend']()
        cls.password_boundary = namespace['RejectLocalPasswords']()

    def user(self, name):
        return SimpleNamespace(pk=1, username=name, is_active=True, is_superuser=False,
            groups=SimpleNamespace(values_list=lambda *a, **kw: ['infrabox:netbox:reader']), get_username=lambda: name,
            social_auth=SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: name == 'human')))

    def test_local_password_fallback_is_always_stopped(self):
        with self.assertRaises(PermissionDenied):
            self.password_boundary.authenticate(None, username='human', password='local-password')

    def test_permission_boundary_does_not_intercept_ldap_login(self):
        self.assertIsNone(self.backend.authenticate(None, username='service', password='ldap-password'))

    def test_service_cannot_reach_fallback_implicit_grants(self):
        user = self.user('svc-openclaw')
        for permission in DEFAULTS:
            with self.assertRaises(PermissionDenied):
                self.backend.has_perm(user, permission)
        self.assertEqual(self.backend.get_object_permissions(user), {'dcim.add_device': [None]})

    def test_allowed_service_actions_still_require_object_permissions(self):
        user = self.user('svc-openclaw')
        self.assertTrue(self.backend.has_perm(user, 'dcim.add_device'))
        self.assertFalse(self.backend.has_perm(user, 'dcim.delete_device'))
        self.assertFalse(self.backend.has_perm(user, 'users.add_user'))

    def test_explicit_inventory_delete_grant_is_honored(self):
        user = self.user('svc-openclaw')
        with patch.object(StockBackend, 'get_object_permissions', return_value={
            **DEFAULTS, 'dcim.delete_device': [None],
            'extras.change_configcontext': [None],
        }):
            self.assertTrue(self.backend.has_perm(user, 'dcim.delete_device'))
            self.assertTrue(self.backend.has_perm(user, 'extras.change_configcontext'))
            self.assertFalse(self.backend.has_perm(user, 'users.delete_user'))
            for permission in DEFAULTS:
                with self.assertRaises(PermissionDenied):
                    self.backend.has_perm(user, permission)

    def test_platform_has_only_the_discovery_envelope(self):
        user = self.user('svc-platform')
        for permission in (*DEFAULTS, 'dcim.delete_device', 'dcim.add_device', 'extras.change_configcontext'):
            with self.assertRaises(PermissionDenied):
                self.backend.has_perm(user, permission)
        for permission in ('dcim.change_device', 'dcim.add_module', 'dcim.view_moduletypeprofile', 'ipam.add_ipaddress'):
            self.assertTrue(self.backend.has_perm(user, permission))
        user.is_superuser = True
        self.assertEqual(self.backend.get_object_permissions(user), {})

    def test_human_self_service_is_preserved(self):
        user = self.user('human')
        for permission in DEFAULTS:
            self.assertTrue(self.backend.has_perm(user, permission))
        self.assertEqual(self.backend.get_object_permissions(user), StockBackend().get_object_permissions(user))


if __name__ == '__main__':
    unittest.main()

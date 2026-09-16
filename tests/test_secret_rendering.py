"""Regression checks for credential formatting sent to container runtimes."""
from pathlib import Path
import json
import tomllib
import unittest
from urllib.parse import unquote, urlparse, parse_qs
import yaml
from jinja2 import Template, Environment


class SecretRenderingTests(unittest.TestCase):
    def test_lldap_database_password_preserves_url_delimiters(self):
        environment = Environment()
        environment.filters['to_json'] = json.dumps
        template = Path('roles/lldap/templates/lldap.toml.j2').read_text()
        password = 'test/@:#?% &"\\secret'
        rendered = environment.from_string(template).render(
            lldap_database_password=password, lldap_admin_password=password,
            lldap_jwt_secret='synthetic', lldap_key_seed='synthetic',
            lldap_base_dn='dc=example,dc=com', lldap_admin_username='svc-admin',
            infrabox_domain='infrabox.example.com', infrabox_internal_domain='infrabox.internal',
        )
        config = tomllib.loads(rendered)
        address = urlparse(config['database_url'])
        self.assertEqual(unquote(address.password), password)
        self.assertEqual(address.hostname, 'postgresql.infrabox.internal')
        self.assertEqual(config['ldap_user_pass'], password)
        self.assertEqual(parse_qs(address.query)['sslmode'], ['verify-full'])
        self.assertFalse(config['force_ldap_user_pass_reset'])

    def test_hsm_environment_preserves_pin_exactly(self):
        tasks = yaml.safe_load(Path('roles/openbao/tasks/configure.yml').read_text())
        task = next(t for t in tasks if t['name'] == 'Protect persistent HSM runtime PIN')
        rendered = Template(task['ansible.builtin.copy']['content']).render(tpm2_pkcs11_user_pin='test-pin')
        # Jinja removes a final newline by default; either framing is safe, spaces are not.
        self.assertEqual(rendered.rstrip('\n'), 'BAO_HSM_PIN=test-pin')
        self.assertNotIn('test-pin ', rendered)
        self.assertEqual(task['ansible.builtin.copy']['mode'], '0600')
        self.assertTrue(task['no_log'])


if __name__ == '__main__':
    unittest.main()

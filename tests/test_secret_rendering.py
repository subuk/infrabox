"""Regression checks for credential formatting sent to container runtimes."""
from pathlib import Path
import unittest
import yaml
from jinja2 import Template


class SecretRenderingTests(unittest.TestCase):
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

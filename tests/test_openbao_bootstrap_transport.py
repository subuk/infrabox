"""The documented key=value override must select loopback-only bootstrap HTTP."""
from pathlib import Path
import unittest
from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment


class BootstrapTransportTests(unittest.TestCase):
    def test_boolean_and_cli_string_overrides_select_the_same_transport(self):
        root = Path(__file__).resolve().parents[1] / 'roles/openbao/templates'
        environment = Environment()
        environment.filters['bool'] = boolean
        values = {
            'infrabox_internal_domain': 'infrabox.internal',
            'openbao_tpm_device': {'stat': {'gid': 59}},
        }
        for flag in [False, 'false', True, 'true']:
            with self.subTest(flag=flag):
                values['openbao_tls_enabled'] = flag
                config = environment.from_string((root / 'config.hcl.j2').read_text()).render(values)
                quadlet = environment.from_string((root / 'openbao.container.j2').read_text()).render(values)
                if boolean(flag):
                    self.assertIn('address = "0.0.0.0:8200"', config)
                    self.assertIn('tls_disable = false', config)
                    self.assertIn('tls_cert_file', config)
                    self.assertIn('Network=infrabox.network', quadlet)
                else:
                    self.assertIn('address = "127.0.0.1:8200"', config)
                    self.assertIn('tls_disable = true', config)
                    self.assertNotIn('tls_cert_file', config)
                    self.assertIn('Network=host', quadlet)
                    self.assertNotIn('PublishPort=', quadlet)

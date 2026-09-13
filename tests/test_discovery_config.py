import json
from pathlib import Path
import unittest
from jinja2 import Environment, StrictUndefined


class DiscoveryConfigTests(unittest.TestCase):
    def test_enabled_discovery_is_fixed_and_retains_execution_denials(self):
        env = Environment(undefined=StrictUndefined)
        env.filters.update(bool=bool, to_json=json.dumps, from_json=json.loads)
        template = env.from_string(Path('roles/openclaw/templates/openclaw.json.j2').read_text())
        for enabled in (False, True):
            c = json.loads(template.render(openclaw_discovery_enabled=enabled,
                openclaw_web_search_enabled=True, openclaw_netbox_enabled=True,
                openclaw_subnet_scan_enabled=True, openclaw_port=18789,
                openclaw_hostname='claw.example.com', openclaw_netbox_url='https://netbox.example.com',
                openclaw_backend_network={'stdout': '[{"subnets":[{"gateway":"192.0.2.1"}]}]'},
                openclaw_model_providers={}))
            expected = {'infrabox_discovery_start', 'infrabox_discovery_status', 'infrabox_discovery_result'}
            self.assertEqual(set(c['tools']['alsoAllow']) & expected, expected if enabled else set())
            self.assertEqual('infrabox-discovery' in c['plugins']['allow'], enabled)
            self.assertEqual('/opt/infrabox/plugins/discovery' in c['plugins']['load']['paths'], enabled)
            self.assertTrue({'exec', 'process', 'browser', 'nodes', 'terminal', 'write', 'sessions_spawn'} <= set(c['tools']['deny']))
            self.assertEqual(c['mcp']['servers']['netbox']['transport'], 'stdio')

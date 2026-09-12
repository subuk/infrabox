"""Search is independent of onboarding and can be explicitly disabled."""
import itertools
import json
from pathlib import Path
import unittest
from jinja2 import Environment, StrictUndefined


class WebSearchConfigurationTests(unittest.TestCase):
    def test_independent_search_switch_preserves_existing_tools(self):
        env = Environment(undefined=StrictUndefined)
        env.filters.update(bool=bool, to_json=json.dumps, from_json=json.loads)
        template = env.from_string(Path('roles/openclaw/templates/openclaw.json.j2').read_text())
        for web, netbox, scanner, openai in itertools.product([True, False], repeat=4):
            with self.subTest(web=web, netbox=netbox, scanner=scanner, openai=openai):
                config = json.loads(template.render(
                    openclaw_web_search_enabled=web, openclaw_netbox_enabled=netbox,
                    openclaw_subnet_scan_enabled=scanner, openclaw_port=18789,
                    openclaw_hostname='claw.infrabox.example.com',
                    openclaw_backend_network={'stdout': '[{"subnets":[{"gateway":"192.0.2.1"}]}]'},
                    openclaw_netbox_url='https://netbox.infrabox.example.com',
                    openclaw_model_providers={'openai': {'api': 'openai-responses'}} if openai else {}))
                tools = config['tools']
                self.assertEqual(tools['web']['search']['enabled'], web)
                self.assertEqual('web_search' in tools['alsoAllow'], web)
                self.assertEqual('openai' in config['plugins']['allow'], web or openai)
                if openai:
                    self.assertTrue(config['plugins']['entries']['openai']['enabled'])
                self.assertNotIn('provider', tools['web']['search'])
                self.assertEqual('read' in tools['alsoAllow'], netbox)
                self.assertEqual('infrabox_scan_subnet' in tools['alsoAllow'], scanner)
                self.assertTrue({'exec', 'browser', 'nodes', 'terminal', 'process'} <= set(tools['deny']))


if __name__ == '__main__':
    unittest.main()

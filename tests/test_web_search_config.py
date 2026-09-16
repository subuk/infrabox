"""Search is independent of onboarding and can be explicitly disabled."""
import itertools
import json
import re
import yaml
from pathlib import Path
import unittest
from jinja2 import Environment, StrictUndefined


class WebSearchConfigurationTests(unittest.TestCase):
    def test_independent_search_switch_preserves_existing_tools(self):
        env = Environment(undefined=StrictUndefined)
        env.filters.update(bool=bool, to_json=json.dumps, from_json=json.loads)
        template = env.from_string(Path('roles/openclaw/templates/openclaw.json.j2').read_text())
        for web, netbox, scanner, openai, ollama in itertools.product([True, False], repeat=5):
            with self.subTest(web=web, netbox=netbox, scanner=scanner, openai=openai):
                config = json.loads(template.render(
                    openclaw_web_search_enabled=web, openclaw_netbox_enabled=netbox,
                    openclaw_subnet_scan_enabled=scanner, openclaw_port=18789,
                    openclaw_hostname='claw.infrabox.example.com',
                    openclaw_backend_network={'stdout': '[{"subnets":[{"gateway":"192.0.2.1"}]}]'},
                    openclaw_netbox_url='https://netbox.infrabox.example.com',
                    openclaw_model_providers={**({'openai': {'api': 'openai-responses'}} if openai else {}),
                        **({'ollama': {'api': 'ollama', 'apiKey': 'ollama-local'}} if ollama else {})}))
                self.assertEqual('ollama' in config['plugins']['allow'], ollama)
                self.assertEqual(config['plugins']['entries'].get('ollama', {}).get('enabled', False), ollama)
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



    def test_only_native_ollama_marker_bypasses_vault_requirement(self):
        tasks = yaml.safe_load(Path('roles/openclaw/tasks/install.yml').read_text())
        rule = next(t for t in tasks if t['name'].startswith('Require Vault credentials'))
        env = Environment(undefined=StrictUndefined)
        env.tests['match'] = lambda value, pattern: bool(re.match(pattern, value))
        check = env.compile_expression(rule['ansible.builtin.assert']['that'][0])
        ref = {'source': 'exec', 'provider': 'vault', 'id': 'openclaw/providers/test/apiKey'}
        cases = [
            ('ollama', {'api': 'ollama', 'apiKey': 'ollama-local'}, True),
            ('openai', {'apiKey': ref}, True),
            ('ollama', {'api': 'ollama', 'apiKey': ref}, True),
            ('openai', {'apiKey': 'ollama-local'}, False),
            ('ollama', {'api': 'openai-completions', 'apiKey': 'ollama-local'}, False),
            ('ollama', {'api': 'ollama', 'apiKey': 'real-plaintext-key'}, False),
            ('ollama', {'api': 'ollama'}, False),
            ('openai', {'apiKey': {**ref, 'id': 'unrelated/key'}}, False),
        ]
        for provider, value, expected in cases:
            with self.subTest(provider=provider, value=value):
                self.assertEqual(check(item={'key': provider, 'value': value}), expected)


if __name__ == '__main__':
    unittest.main()

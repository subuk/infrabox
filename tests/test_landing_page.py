"""Render the home page against nginx's real domain configuration."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

from jinja2 import Environment, StrictUndefined
import yaml


ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cards = {}
        self.assets = []
        self.scripts = 0
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'a' and 'card' in attrs.get('class', '').split():
            self.cards[attrs['aria-labelledby']] = attrs['href']
        if tag == 'link':
            self.assets.append(attrs.get('href', ''))
        if 'src' in attrs:
            self.assets.append(attrs['src'])
        if tag == 'script':
            self.scripts += 1


def render_page(**overrides):
    env = Environment(undefined=StrictUndefined)
    defaults = yaml.safe_load((ROOT / 'roles/nginx/defaults/main.yml').read_text())
    context = {'infrabox_domain': 'infrabox.example.com', **defaults, **overrides}
    # Resolve nested role-default expressions as Ansible does before rendering.
    context['nginx_upstreams'] = [
        {key: env.from_string(value).render(context) for key, value in upstream.items()}
        for upstream in context['nginx_upstreams']
    ]
    template = (ROOT / 'roles/nginx/templates/index.html.j2').read_text()
    return Page(env.from_string(template).render(context))


class LandingPageTests(unittest.TestCase):
    def test_five_services_use_the_configured_base_domain(self):
        page = render_page(infrabox_domain='appliance.example.net')
        self.assertEqual(page.cards, {
            'title-' + name: f'https://{name}.appliance.example.net/'
            for name in ['git', 'netbox', 'grafana', 'vault', 'claw']
        })

    def test_upstream_hostname_overrides_match_the_nginx_routes(self):
        upstreams = [
            {'name': name, 'hostname': f'custom-{name}.example.net', 'address': 'http://127.0.0.1:9000'}
            for name in ['git', 'netbox', 'grafana', 'vault', 'claw']
        ]
        page = render_page(nginx_upstreams=upstreams)
        self.assertEqual(page.cards, {
            'title-' + item['name']: 'https://' + item['hostname'] + '/'
            for item in upstreams
        })

    def test_openclaw_uses_its_existing_hostname_variable(self):
        page = render_page(openclaw_hostname='assistant.example.net', nginx_verify_openclaw=False)
        self.assertEqual(page.cards['title-claw'], 'https://assistant.example.net/')
        self.assertEqual(len(page.cards), 5)

    def test_page_requires_no_remote_assets_or_scripts(self):
        page = render_page()
        self.assertEqual(page.scripts, 0)
        self.assertTrue(all(asset.startswith('data:') for asset in page.assets))


if __name__ == '__main__':
    unittest.main()

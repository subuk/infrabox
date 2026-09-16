import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('gitea_identity', Path('roles/gitea/files/identity.py'))
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class NativeForms(unittest.TestCase):
    def test_native_checkbox_value_and_html_escaping(self):
        form = identity.Form('''<input name="two_factor_policy" type="checkbox" value="skip" checked>
            <input name="is_active" type="checkbox" checked>
            <input name="skip_verify" type="checkbox">
            <input name="filter" value="(&amp;(uid=%s)(infraboxIdentityType=service))">
            <textarea name="group_team_map">{&quot;role&quot;:{&quot;org&quot;:[&quot;Readers&quot;]}}</textarea>''')
        self.assertEqual(form.values['two_factor_policy'], 'skip')
        self.assertEqual(form.values['is_active'], 'on')
        self.assertEqual(form.values['skip_verify'], '')
        self.assertEqual(form.values['filter'], '(&(uid=%s)(infraboxIdentityType=service))')
        self.assertEqual(form.values['group_team_map'], '{"role":{"org":["Readers"]}}')

    def test_creation_submits_field_consumed_by_native_handler(self):
        manager = identity.Manager.__new__(identity.Manager)
        manager.changed = False
        sources, posted = {}, []
        manager.sources = lambda: sources.copy()
        def page(path, data=None):
            if data is not None:
                posted.append(data)
                sources['openbao'] = '3'
            return path, '<input name="name" value="openbao"><input name="two_factor_policy" type="checkbox" value="skip" checked>'
        manager.page = page
        manager.ensure_source('openbao', {'name': 'openbao', 'type': '6', 'two_factor_policy': 'skip'})
        self.assertEqual(posted[0]['two_factor_policy'], 'skip')
        self.assertTrue(manager.changed)
        manager.changed = False
        manager.ensure_source('openbao', {'name': 'openbao', 'type': '6', 'two_factor_policy': 'skip'})
        self.assertFalse(manager.changed)
        self.assertEqual(len(posted), 1)

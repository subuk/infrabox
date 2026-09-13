import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('platform_management', ROOT / 'roles/platform/files/manage.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SyncTests(unittest.TestCase):
    def manager(self, directory, old, new, generation='new'):
        m = module.Manager.__new__(module.Manager)
        m.directory = Path(directory)
        m.changed, m.paused = False, False
        m.repo, m.git_base = '/repos/fixture/automation', 'https://git.example.com'
        m.c = {'directory': directory, 'storage': directory, 'branch': 'master',
               'revision': new, 'generation': generation, 'source_dir': directory,
               'provisioner': 'provisioner', 'ca': '/public/ca.crt',
               'organization': 'fixture', 'repository': 'automation'}
        m.api = lambda *args, **kwargs: {'commit': {'id': old}} if old else None
        return m

    def test_forced_update_uses_expected_old_sha_and_records_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            m = self.manager(temp, 'a' * 40, 'b' * 40)
            with patch.object(module, 'command', return_value='') as run:
                m.synchronize('fixture-token')
            argv = run.call_args.args[0]
            self.assertIn('--force-with-lease=refs/heads/master:' + 'a' * 40, argv)
            self.assertIn('b' * 40 + ':refs/heads/master', argv)
            self.assertNotIn('fixture-token', ' '.join(argv))
            self.assertEqual(json.loads((Path(temp) / 'pending.json').read_text())['revision'], 'b' * 40)
            self.assertFalse((Path(temp) / 'deployed.json').exists())

    def test_failed_push_does_not_report_deployed_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            m = self.manager(temp, 'a' * 40, 'b' * 40)
            with patch.object(module, 'command', side_effect=module.ManagementError('failed')):
                with self.assertRaises(module.ManagementError):
                    m.synchronize('fixture-token')
            self.assertFalse((Path(temp) / 'deployed.json').exists())
            self.assertFalse((Path(temp) / 'pending.json').exists())

    def test_healthy_revision_is_a_noop(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'deployed.json').write_text(json.dumps({'generation': 'same'}))
            m = self.manager(temp, 'a' * 40, 'a' * 40, 'same')
            with patch.object(module, 'command') as run:
                m.synchronize('fixture-token')
            run.assert_not_called()
            self.assertFalse(m.changed)


class VariableTests(unittest.TestCase):
    def test_existing_gitea_data_is_preserved(self):
        m = module.Manager.__new__(module.Manager)
        m.c = {'variables': {'NETBOX_API': 'https://netbox.example.com'}}
        m.repo, m.changed = '/repos/fixture/automation', False
        m.api = Mock(return_value={'name': 'NETBOX_API', 'data': 'https://netbox.example.com'})
        m.variables()
        self.assertEqual(m.api.call_count, 1)
        self.assertFalse(m.changed)

    def test_changed_gitea_data_uses_write_value_field(self):
        m = module.Manager.__new__(module.Manager)
        m.c = {'variables': {'NETBOX_API': 'https://new.example.com'}}
        m.repo, m.changed = '/repos/fixture/automation', False
        m.api = Mock(return_value={'name': 'NETBOX_API', 'data': 'https://old.example.com'})
        m.variables()
        m.api.assert_called_with('/repos/fixture/automation/actions/variables/NETBOX_API',
                                 {'value': 'https://new.example.com'}, 'PUT')
        self.assertTrue(m.changed)


class RepositoryTests(unittest.TestCase):
    def test_granular_permissions_are_stable_and_code_write_is_repaired(self):
        for code_permission in ('read', 'write'):
            with self.subTest(code_permission=code_permission):
                m = module.Manager.__new__(module.Manager)
                m.changed = False
                m.repo = '/repos/fixture/automation'
                m.c = {'organization': 'fixture', 'repository': 'automation',
                       'branch': 'master', 'provisioner': 'provisioner', 'operators': []}
                writes = []
                def api(path, data=None, method='GET', **kwargs):
                    if method != 'GET':
                        writes.append((path, data, method))
                        return {'id': 3}
                    if path == '/orgs/fixture/teams?limit=50':
                        return [{'id': 3, 'name': 'Operators', 'permission': 'none',
                                 'units_map': {'repo.code': code_permission, 'repo.actions': 'write'},
                                 'can_create_org_repo': False, 'includes_all_repositories': False}]
                    if path == '/teams/3/members':
                        return []
                    if path == m.repo:
                        return {'private': True, 'has_actions': True, 'has_pull_requests': False,
                                'has_issues': False, 'has_wiki': False, 'default_branch': 'master'}
                    if path.endswith('/branch_protections/master'):
                        return {'rule_name': 'master', 'enable_push': True, 'enable_push_whitelist': True,
                                'push_whitelist_usernames': ['provisioner'], 'enable_force_push': True,
                                'enable_force_push_allowlist': True, 'force_push_allowlist_usernames': ['provisioner']}
                    return {}
                m.api = api
                m.repository()
                self.assertEqual(m.changed, code_permission == 'write')
                if code_permission == 'read':
                    self.assertEqual(writes, [])
                else:
                    self.assertEqual(len(writes), 1)
                    self.assertEqual(writes[0][0], '/teams/3')
                    self.assertEqual(writes[0][1]['units_map'], {'repo.code': 'read', 'repo.actions': 'write'})
                    self.assertEqual(writes[0][2], 'PATCH')

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

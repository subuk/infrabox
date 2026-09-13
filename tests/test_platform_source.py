import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('platform_source', ROOT / 'scripts/platform-source.py')
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class SourceTests(unittest.TestCase):
    def test_bundle_preserves_commit_and_excludes_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); repo = root / 'repo'; repo.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
            git('init', '-q')
            for name in ['.gitea/workflows/discover.yml', 'playbooks/discover.yml', 'runtime/Containerfile', 'requirements.txt']:
                p = repo / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('committed\n')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.com', 'commit', '-qm', 'fixture')
            sha = git('rev-parse', 'HEAD')
            (repo / 'requirements.txt').write_text('uncommitted secret sentinel\n')
            result = source.prepare(str(repo), 'HEAD', os.path.relpath(root / 'bundles'))
            self.assertEqual(result['revision'], sha)
            self.assertFalse(source.prepare(str(repo), 'HEAD', str(root / 'bundles'))['changed'])
            clone = root / 'clone'
            subprocess.run(['git', 'clone', '-q', '--branch', 'platform-source', result['bundle'], str(clone)], check=True)
            self.assertEqual((clone / 'requirements.txt').read_text(), 'committed\n')
            with self.assertRaises(ValueError):
                source.prepare('https://token@github.com/example/repo', 'master', str(root / 'bad'))

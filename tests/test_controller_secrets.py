"""Protect per-appliance secret identity when preparing a fresh deployment."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ControllerSecretsTests(unittest.TestCase):
    def test_new_alias_does_not_replace_existing_appliance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'scripts' / 'create-controller-secrets.py'
            script.parent.mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'scripts' / script.name, script)
            old = root / '.secrets' / 'infrabox1' / 'inputs.json'
            old.parent.mkdir(parents=True)
            old.write_text('{"existing": "preserve"}\n')
            command = [sys.executable, str(script), '--inventory-hostname', 'fresh']
            subprocess.run(command, check=True, capture_output=True)
            new = root / '.secrets' / 'fresh' / 'inputs.json'
            first = new.read_bytes()
            values = json.loads(first)
            self.assertIn('tpm2_pkcs11_user_pin', values)
            self.assertNotIn('gitea_admin_password', values)
            self.assertNotIn('netbox_admin_password', values)
            self.assertNotIn('grafana_admin_password', values)
            self.assertEqual(new.stat().st_mode & 0o777, 0o600)
            self.assertEqual(new.parent.stat().st_mode & 0o777, 0o700)
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(new.read_bytes(), first)
            self.assertEqual(old.read_text(), '{"existing": "preserve"}\n')
            rejected = subprocess.run([sys.executable, str(script), '--inventory-hostname', '../outside'], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse((root / 'outside').exists())

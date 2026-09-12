import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path('roles/integration_checks/files').resolve()))
spec=importlib.util.spec_from_file_location('gate','scripts/verify-monitoring.py');gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class VerificationWindowTests(unittest.TestCase):
    def test_old_or_duplicate_success_never_passes(self):
        self.assertFalse(gate.stable([100,100,100],99))
        self.assertFalse(gate.stable([1,61,121],200))
        self.assertFalse(gate.stable([201,202,203],200))
    def test_three_distinct_after_change_across_window(self):
        self.assertTrue(gate.stable([201,261,321],200))
        self.assertFalse(gate.stable([200,260,320],200))
if __name__=='__main__':unittest.main()

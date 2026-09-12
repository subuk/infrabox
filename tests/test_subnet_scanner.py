import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock

PATH = Path(__file__).resolve().parents[1] / 'roles/openclaw/files/subnet-scan/scanner.py'
spec = importlib.util.spec_from_file_location('scanner', PATH)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ScannerTests(unittest.TestCase):
    def test_size_and_canonical_address(self):
        for value in ['192.0.2.0/24', '192.0.2.128/25', '192.0.2.9/32', '8.8.8.8/32']:
            self.assertEqual(scanner.target(value), value)
        for value in ['0.0.0.0/0', '192.0.2.0/23', '192.0.2.1/24', '::/120',
                      'example.com/24', '192.0.2.1', '192.0.2.0/255.255.255.0',
                      '192.0.2.0/24 -A', '192.0.2.1/32,192.0.2.2/32', None, 24]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                scanner.target(value)

    def test_injection_never_launches_process(self):
        with patch.object(scanner.subprocess, 'Popen') as launch:
            with self.assertRaises(ValueError):
                scanner.scan('192.0.2.1/32; touch /tmp/unsafe')
            launch.assert_not_called()

    def test_busy_does_not_launch_second_scan(self):
        scanner.SCAN_LOCK.acquire()
        try:
            with patch.object(scanner.subprocess, 'Popen') as launch:
                with self.assertRaises(RuntimeError):
                    scanner.scan('192.0.2.1/32')
                launch.assert_not_called()
        finally:
            scanner.SCAN_LOCK.release()

    def test_timeout_kills_process_group_and_releases_lock(self):
        process = Mock(pid=123)
        process.wait.side_effect = [subprocess.TimeoutExpired('nmap', 180), 0]
        with patch.object(scanner.subprocess, 'Popen', return_value=process), patch.object(scanner.os, 'killpg') as kill:
            result = scanner.scan('192.0.2.1/32')
            self.assertEqual(result['status'], 'timed_out')
            kill.assert_called_once_with(123, scanner.signal.SIGKILL)
            self.assertFalse(scanner.SCAN_LOCK.locked())

    def test_native_os_matches_remain_heuristic(self):
        xml = '''<nmaprun><host><status state="up" reason="syn-ack"/>
          <address addr="192.0.2.1" addrtype="ipv4"/>
          <ports><port protocol="tcp" portid="22"><state state="open"/></port>
          <port protocol="tcp" portid="80"><state state="filtered"/></port></ports>
          <os><osmatch name="Linux 5.x" accuracy="96"/></os></host>
          <runstats><finished exit="success"/></runstats></nmaprun>'''
        host = scanner.parse_result(xml, '192.0.2.0/24')['hosts'][0]
        self.assertEqual(host['open_tcp_ports'], [22])
        self.assertEqual(host['os_detection'], 'heuristic')
        self.assertEqual(host['os_guesses'][0]['accuracy_percent'], 96)
        with self.assertRaises(ValueError):
            scanner.parse_result(xml, '198.51.100.0/24')
        with self.assertRaises(ValueError):
            scanner.parse_result(xml.replace('exit="success"', 'exit="error"'), '192.0.2.0/24')

    def test_no_os_match_is_inconclusive(self):
        result = scanner.parse_result('<nmaprun><host><status state="up"/><address addr="192.0.2.1" addrtype="ipv4"/></host><runstats><finished exit="success"/></runstats></nmaprun>', '192.0.2.1/32')
        self.assertEqual(result['hosts'][0]['os_detection'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()

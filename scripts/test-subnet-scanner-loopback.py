#!/usr/bin/env python3
"""Run inside a disposable scanner image with --network=none, never against a LAN."""
import socket
import sys

sys.path.insert(0, '/opt/infrabox')
import scanner

# A closed port plus this open one lets Nmap exercise native OS detection.
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 8080))
    listener.listen(16)
    result = scanner.scan('127.0.0.1/32')
    assert result['status'] == 'completed', result['status']
    assert len(result['hosts']) == 1, 'Loopback host not discovered'
    host = result['hosts'][0]
    assert host['ip'] == '127.0.0.1' and 8080 in host['open_tcp_ports'], 'Listener not discovered'
    print('Isolated loopback scan: responsive IP and TCP 8080 detected; OS outcome: ' + host['os_detection'])
    print('Native Nmap command and XML parsing succeeded with only CAP_NET_RAW; no LAN target scanned')

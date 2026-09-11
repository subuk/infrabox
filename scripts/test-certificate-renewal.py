#!/usr/bin/python3
"""Observe short-lived certificate replacement and actual TLS listeners."""
import hashlib
import json
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import time

registry = json.loads(Path('/etc/infrabox/openbao-agent/certificates.json').read_text())
context = ssl.create_default_context(cafile=registry['root'] + '/root-ca.crt')
def leaf(spec):
    return Path(registry['root'], spec['name'], 'server.crt').read_text()
def fingerprint(pem):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
def served(spec):
    name = spec['name']
    address, port = '127.0.0.1', {'openbao': 8200, 'nginx': 443, 'redis': 6379, 'postgresql': 5432}[name]
    if name in ['redis', 'postgresql']:
        info = json.loads(subprocess.check_output(['podman', 'inspect', name], stderr=subprocess.PIPE))[0]
        address = info['NetworkSettings']['Networks']['infrabox']['IPAddress']
    with socket.create_connection((address, port), timeout=10) as connection:
        if name == 'postgresql':
            connection.sendall(struct.pack('!II', 8, 80877103))
            assert connection.recv(1) == b'S'
        with context.wrap_socket(connection, server_hostname=spec['common_name']) as secured:
            return hashlib.sha256(secured.getpeercert(binary_form=True)).hexdigest()

initial = {s['name']: fingerprint(leaf(s)) for s in registry['certificates']}
netbox_invocation = subprocess.check_output(['systemctl', 'show', 'netbox', '-p', 'InvocationID', '--value'], text=True)
expirations = {}
for spec in registry['certificates']:
    end = subprocess.check_output(['openssl', 'x509', '-in', registry['root'] + '/' + spec['name'] + '/server.crt', '-noout', '-enddate'], text=True).strip().split('=', 1)[1]
    expirations[spec['name']] = ssl.cert_time_to_seconds(end)
pending = {s['name'] for s in registry['certificates']}
deadline = time.monotonic() + 420
while pending and time.monotonic() < deadline:
    for spec in registry['certificates']:
        name = spec['name']
        current = fingerprint(leaf(spec))
        if name in pending and current != initial[name]:
            assert time.time() < expirations[name], name + ': replacement was observed after old certificate expiry'
            try:
                observed = served(spec)
            except (OSError, subprocess.CalledProcessError):
                # Redis uses a controlled container restart for its certificate.
                # Retry the transition, still bounded by the old leaf's expiry.
                continue
            if observed == current:
                print(name + ': renewed certificate observed on verified TLS connection', flush=True)
                pending.remove(name)
    if pending:
        time.sleep(3)
assert not pending, 'Certificates not renewed: ' + ', '.join(sorted(pending))
assert subprocess.check_output(['systemctl', 'show', 'netbox', '-p', 'InvocationID', '--value'], text=True) == netbox_invocation, 'Backend certificate renewal restarted NetBox'

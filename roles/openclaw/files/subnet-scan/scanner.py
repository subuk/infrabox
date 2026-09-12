#!/usr/bin/env python3
"""Bounded Nmap worker. Only the Gateway can connect to the private Unix socket."""
import http.server
import ipaddress
import json
import os
import signal
import socketserver
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET

SOCKET = '/run/infrabox-scanner/api.sock'
PORTS = '21,22,23,25,53,80,110,111,135,139,143,389,443,445,465,587,636,993,995,1433,2049,3306,3389,5432,5900,8000,8080,8443'
TIMEOUT = 180
MAX_OUTPUT = 2 * 1024 * 1024
SCAN_LOCK = threading.Lock()


def target(value):
    if not isinstance(value, str) or '/' not in value or len(value) > 18:
        raise ValueError('Use one canonical IPv4 CIDR, /24 through /32.')
    network = ipaddress.ip_network(value, strict=True)
    if network.version != 4 or network.prefixlen < 24 or str(network) != value:
        raise ValueError('Use one canonical IPv4 CIDR, /24 through /32 (at most 256 addresses).')
    return str(network)


def command(cidr):
    return ['/usr/bin/nmap', '--privileged', '-n', '-sS', '-O', '--osscan-guess',
            '--osscan-limit', '--max-os-tries', '1', '--max-retries', '1',
            '--max-rate', '100', '--max-parallelism', '16', '--host-timeout', '20s',
            '-p', PORTS, '-oX', '-', target(cidr)]


def parse_result(xml, cidr):
    root = ET.fromstring(xml)
    finished = root.find('runstats/finished')
    if root.tag != 'nmaprun' or finished is None or finished.get('exit') != 'success':
        raise ValueError('Nmap did not report a successful completion.')
    hosts = []
    for host in root.findall('host'):
        status = host.find('status')
        address = host.find("address[@addrtype='ipv4']")
        if status is None or status.get('state') != 'up' or address is None:
            continue
        ip = str(ipaddress.IPv4Address(address.get('addr')))
        if ipaddress.ip_address(ip) not in ipaddress.ip_network(cidr):
            raise ValueError('Nmap returned an address outside the approved target.')
        ports = []
        for port in host.findall('ports/port'):
            state = port.find('state')
            if state is not None and state.get('state') == 'open':
                ports.append(int(port.get('portid')))
        guesses = [{'name': match.get('name', '')[:256],
                    'accuracy_percent': int(match.get('accuracy', '0'))}
                   for match in host.findall('os/osmatch')[:5]]
        hosts.append({'ip': ip, 'response_reason': status.get('reason'),
                      'open_tcp_ports': ports, 'os_guesses': guesses,
                      'os_detection': 'heuristic' if guesses else 'inconclusive',
                      'host_timed_out': host.get('timedout') == 'true'})
    return {'subnet': cidr, 'status': 'completed', 'hosts': hosts,
            'tested_tcp_ports': [int(p) for p in PORTS.split(',')],
            'limitations': 'Only responsive hosts and selected TCP ports are reported. '
            'Filtered or timed-out hosts may be missing. OS matches and Nmap accuracy '
            'scores are heuristics, not verified identities or calibrated probabilities. '
            'Scanning runs through a routed container bridge; MAC discovery and OS accuracy may be limited.'}


def scan(cidr):
    argv = command(cidr)
    if not SCAN_LOCK.acquire(blocking=False):
        raise RuntimeError('Another scan is running; no scan was started.')
    try:
        # Disk output is capped by the container /tmp size; no unbounded pipes.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(argv, stdout=output, stderr=errors, start_new_session=True)
            try:
                process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return {'subnet': cidr, 'status': 'timed_out', 'hosts': [],
                        'limitations': 'Scan stopped after 180 seconds. Results are incomplete; no absence can be inferred. A retry needs new approval.'}
            if process.returncode:
                raise RuntimeError('Nmap failed; no reliable discovery result is available.')
            output.seek(0)
            xml = output.read(MAX_OUTPUT + 1)
            if len(xml) > MAX_OUTPUT:
                raise RuntimeError('Nmap output exceeded the result limit.')
            return parse_result(xml, cidr)
    finally:
        SCAN_LOCK.release()


class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args):
        pass

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == '/health' else 404,
                   {'service': 'infrabox-subnet-scanner', 'max_addresses': 256})

    def do_POST(self):
        if self.path != '/scan':
            self.reply(404, {'error': 'Unknown endpoint'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 128 or self.headers.get('Transfer-Encoding'):
                raise ValueError('Invalid request length')
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or set(request) != {'subnet'}:
                raise ValueError('Only subnet is accepted')
            cidr = target(request['subnet'])
        except (ValueError, TypeError):
            self.reply(400, {'error': 'Use one canonical IPv4 CIDR, /24 through /32; no options or ranges.'})
            return
        try:
            self.reply(200, scan(cidr))
        except (RuntimeError, ValueError, OSError, ET.ParseError):
            self.reply(503, {'error': 'Scanner busy or failed; no reliable result. A retry needs new approval.'})


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 4


if __name__ == '__main__':
    if os.path.exists(SOCKET):
        os.unlink(SOCKET)
    with Server(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.serve_forever()

#!/usr/bin/python3
"""Bounded read-only Prometheus health API. No probe execution or raw query interface."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import socketserver
import time
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import urlopen

STATES = ('healthy', 'warning', 'critical', 'unknown')
ORDER = {'critical': 0, 'unknown': 1, 'warning': 2, 'healthy': 3}
MAX_BYTES = 8192
MAX_ISSUES = 20

def stamp(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace('+00:00', 'Z')

def overall(states):
    return min(states, key=lambda s: ORDER[s]) if states else 'unknown'

def api(base, path, params=None):
    with urlopen(base + path + ('?' + urlencode(params) if params else ''), timeout=3) as r:
        data = r.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('response_limit')
    d = json.loads(data)
    if d.get('status') != 'success' or d.get('warnings'):
        raise ValueError('query_failed')
    return d['data']

def snapshot(catalog, fetch, now=None, component=None):
    now = time.time() if now is None else now
    checks = catalog['checks']
    if component is not None and component not in {c['component'] for c in checks}:
        raise ValueError('invalid_component')
    selected = [c for c in checks if component is None or c['component'] == component]
    faults, rows = [], {}
    try:
        rules = fetch('/api/v1/rules', {})['groups']
        required = set(catalog['rule_groups'])
        seen = set()
        for group in rules:
            if group['name'] not in required:
                continue
            seen.add(group['name'])
            if catalog.get('rule_counts',{}).get(group['name'],len(group['rules']))!=len(group['rules']):
                faults.append('missing_rules')
            evaluated = datetime.fromisoformat(group['lastEvaluation'].replace('Z', '+00:00')).timestamp()
            if not -5 <= now - evaluated <= 90 or any(r.get('health') != 'ok' or r.get('lastError') for r in group['rules']):
                faults.append('rule_evaluation')
        if seen != required:
            faults.append('missing_rules')
        result = fetch('/api/v1/query', {'query': '{__name__=~"infrabox:check_state|infrabox:raw_failure|infrabox:observation|infrabox:coverage_ok|infrabox_catalog_info|infrabox:rules_generation|infrabox_probe_failure|ALERTS"}', 'time': now})
        if result['resultType'] != 'vector':
            raise ValueError('invalid_response')
        generations, rule_generations, coverage = set(), set(), False
        for sample in result['result']:
            metric = sample['metric']; name = metric['__name__']
            value = float(sample['value'][1]); sample_time = float(sample['value'][0])
            if not math.isfinite(value) or not -5 <= now - sample_time <= 90:
                faults.append('stale_series'); continue
            if name == 'infrabox_catalog_info' and value == 1:
                generations.add(metric.get('generation'))
            elif name == 'infrabox:rules_generation' and value == 1:
                rule_generations.add(metric.get('generation'))
            elif name == 'infrabox:coverage_ok' and value == 1:
                coverage = True
            elif 'check_id' in metric:
                row = rows.setdefault(metric['check_id'], {'states': []})
                if name == 'ALERTS' and value == 1:
                    if row.get('alert_state')!='firing':
                        row['alert_state']=metric.get('alertstate')
                elif name == 'infrabox:check_state' and value == 1:
                    row['states'].append(metric.get('state'))
                elif name == 'infrabox:raw_failure':
                    row['raw_failure'] = value
                elif name == 'infrabox:observation':
                    row['observed'] = value
                elif name == 'infrabox_probe_failure' and value == 1:
                    row['reason'] = metric.get('reason') if metric.get('reason') in {'auth','permission','tls','dns','connect','timeout','unavailable','invalid_response','tool_unavailable','internal'} else 'internal'
        if catalog['generation'] not in generations or ('rule_counts' in catalog and catalog['generation'] not in rule_generations):
            faults.append('catalog_mismatch')
        if not coverage:
            faults.append('monitoring_coverage')
    except Exception:
        faults.append('prometheus_unavailable')
    counts = dict.fromkeys(STATES, 0); issues = []; observations = {}; raw = []
    for check in selected:
        cid = check['id']; row = rows.get(cid, {}); observation = row.get('observed', 0)
        states = row.get('states', [])
        valid = len(states) == 1 and states[0] in STATES and -5 <= now - observation <= check['max_age']
        state = states[0] if valid else 'unknown'
        if state == 'healthy' and row.get('raw_failure', 0) > 0:
            state = 'warning'
        counts[state] += 1
        if valid:
            observations[cid] = observation
        if row.get('raw_failure', 0) > 0:
            raw.append(cid)
        if state != 'healthy' or cid in raw:
            issues.append({'id': cid, 'component': check['component'], 'integration': check.get('integration', ''),
                           'state': state if state != 'healthy' else 'warning',
                           'alert_state': row.get('alert_state', 'pending' if cid in raw else 'firing' if state in ('critical','warning') else 'unknown'),
                           'reason': row.get('reason', 'unavailable') if valid else 'missing_or_stale',
                           'summary': check['summary'], 'last_observed_at': stamp(observation) if valid else None,
                           'runbook_id': check['runbook']})
    if faults:
        issues.append({'id': 'monitoring_coverage', 'component': 'prometheus', 'integration': '', 'state': 'unknown',
                       'alert_state': 'unknown', 'reason': sorted(set(faults))[0], 'summary': 'Monitoring evidence is incomplete',
                       'last_observed_at': None, 'runbook_id': 'monitoring'})
    issues.sort(key=lambda i: (ORDER[i['state']], i['id']))
    status = overall([s for s in STATES if counts[s]] + (['unknown'] if faults else []))
    result = {'schema_version': 1, 'status': status, 'coverage_complete': not faults and counts['unknown'] == 0,
              'generated_at': stamp(now), 'generation': catalog['generation'],
              'checks': {'expected': len(selected), **counts}, 'issues_total': len(issues), 'truncated': len(issues) > MAX_ISSUES,
              'issues': issues[:MAX_ISSUES]}
    while len(json.dumps(result).encode()) > MAX_BYTES and result['issues']:
        result['issues'].pop(); result['truncated'] = True
    return result, observations, sorted(raw)

def load_snapshot(config, component=None):
    catalog = json.loads(Path(config).read_text())
    return snapshot(catalog, lambda path, params: api('http://127.0.0.1:9090', path, params), component=component)

class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 4
    slots = threading.BoundedSemaphore(4)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            request.settimeout(10)
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def do_GET(self):
        parsed = urlsplit(self.path); params = parse_qs(parsed.query)
        if parsed.path != '/health' or set(params) - {'component'} or any(len(v) != 1 for v in params.values()):
            self.send_error(400); return
        try:
            result, _, _ = load_snapshot(self.server.config, params.get('component', [None])[0])
            body = json.dumps(result).encode()
        except ValueError:
            self.send_error(400); return
        except Exception:
            self.send_error(503); return
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)

def main():
    p = argparse.ArgumentParser(); p.add_argument('--config', default='/etc/infrabox/monitoring/catalog.json')
    p.add_argument('--socket'); p.add_argument('--component'); args = p.parse_args()
    if not args.socket:
        print(json.dumps(load_snapshot(args.config, args.component)[0])); return
    Path(args.socket).unlink(missing_ok=True)
    with Server(args.socket, Handler) as server:
        server.config = args.config; os.chmod(args.socket, 0o660); server.serve_forever()

if __name__ == '__main__':
    main()

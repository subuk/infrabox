#!/usr/bin/python3
"""Disruptive monitoring acceptance on an explicitly authorized appliance."""
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, '/usr/local/libexec/infrabox-monitoring')
import health

CONFIG='/etc/infrabox/monitoring/catalog.json'
def call(*args):
    subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90)
def wait(predicate, label, timeout=240):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        d=health.load_snapshot(CONFIG)[0]
        if predicate(d):
            print(json.dumps({'test':label,'status':'passed','health':d['status'],'coverage':d['coverage_complete']}),flush=True)
            return d
        time.sleep(5)
    raise RuntimeError(label+' timed out')
def issue(d,cid,state=None):
    return any(i['id']==cid and (state is None or i['state']==state) for i in d['issues'])
def healthy(d):return d['status']=='healthy' and d['coverage_complete']
def main():
    wait(healthy,'initial healthy')
    # Reachability and functioning Gateway integration must both detect loss.
    try:
        call('systemctl','stop','netbox.service')
        wait(lambda d:issue(d,'openclaw_netbox') and issue(d,'unit_netbox'),'NetBox failure visible')
        wait(lambda d:issue(d,'unit_netbox','critical'),'pending becomes critical')
    finally:call('systemctl','start','netbox.service','netbox-worker.service')
    wait(healthy,'NetBox recovery',300)
    try:
        call('systemctl','stop','infrabox-checks.timer')
        call('systemctl','stop','infrabox-checks.service')
        wait(lambda d:d['status']=='unknown' and not d['coverage_complete'],'frozen success is unknown',240)
    finally:call('systemctl','start','infrabox-checks.timer')
    wait(healthy,'probe scheduling recovery',300)
    try:
        call('systemctl','stop','prometheus.service')
        wait(lambda d:d['status']=='unknown' and not d['coverage_complete'],'Prometheus failure is unknown',30)
        time.sleep(45) # Allow one Grafana refresh to observe the unavailable datasource.
    finally:call('systemctl','start','prometheus.service')
    wait(healthy,'Prometheus recovery',300)
    # Prometheus is queried through the OpenClaw plugin's real Unix socket boundary.
    call('podman','exec','openclaw','node','--input-type=module','-e',
         "import {readHealth} from '/opt/infrabox/plugins/health/index.mjs';const r=await readHealth();if(r.status!=='healthy'||!r.coverage_complete)process.exit(1)")
    print(json.dumps({'test':'Gateway read-only health socket','status':'passed'}),flush=True)
    call('podman','exec','openclaw','node','--input-type=module','-e',
         "const r=await fetch('http://127.0.0.1:18789/tools/invoke',{method:'POST',headers:{Authorization:'Bearer '+process.env.OPENCLAW_GATEWAY_TOKEN,'Content-Type':'application/json'},body:JSON.stringify({tool:'infrabox_health',args:{}}),signal:AbortSignal.timeout(20000)});const d=await r.json();if(!r.ok||!d.ok||d.result?.details?.status!=='healthy'||!d.result.details.coverage_complete)process.exit(1)")
    print(json.dumps({'test':'Gateway registered health tool invocation','status':'passed'}),flush=True)

if __name__=='__main__':main()

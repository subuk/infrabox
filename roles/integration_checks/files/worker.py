#!/usr/bin/python3
"""Fixed deterministic probes. Host privilege never becomes an invocation API."""
import argparse
import configparser
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

BASE=Path('/etc/infrabox/monitoring')
STATE=Path('/var/lib/infrabox-monitoring')
TEXT=Path('/var/lib/infrabox-node-exporter')
REASONS={'auth','permission','tls','dns','connect','timeout','unavailable','invalid_response','tool_unavailable','internal'}

class ProbeError(Exception): pass
class ProbeDeferred(Exception): pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*_): raise ProbeError('invalid_response')

def request(url,ca,token=None,data=None,method=None,limit=1024*1024):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']=token
    opener=build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=ca)),NoRedirect())
    try:
        with opener.open(Request(url,None if data is None else json.dumps(data).encode(),headers,method=method),timeout=10) as r:
            b=r.read(limit+1)
            if len(b)>limit:raise ProbeError('invalid_response')
            return b
    except HTTPError as e:raise ProbeError('auth' if e.code==401 else 'permission' if e.code==403 else 'unavailable') from None
    except URLError as e:raise ProbeError('tls' if isinstance(e.reason,ssl.SSLError) else 'dns' if isinstance(e.reason,socket.gaierror) else 'connect') from None

def run(argv,stdin=None,timeout=15):
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        p=subprocess.Popen(argv,stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
        try:p.communicate(stdin.encode() if stdin else None,timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGKILL);p.wait()
            # Keep only fixed diagnostic fields, never command arguments or raw output.
            out.seek(0);body=out.read(4096)
            try:reported=json.loads(body)
            except ValueError:reported={}
            if not isinstance(reported,dict):reported={}
            mode=argv[-1] if '/opt/infrabox/monitoring/openclaw-probe.mjs' in argv and argv[-1] in ('mcp','vault','ready','diagnostics') else 'fixed_command'
            atomic(STATE/'last-command-timeout.json',json.dumps({'mode':mode,'timeout_seconds':timeout,
                'result_reported':bool(reported),'reported_success':reported.get('success') is True,
                'stderr_bytes':err.seek(0,2),'observed_at':time.time()}),0o600)
            raise ProbeError('timeout') from None
        out.seek(0);body=out.read(1024*1024+1)
        if len(body)>1024*1024:raise ProbeError('invalid_response')
        if p.returncode:
            try:raise ProbeError(json.loads(body).get('reason','unavailable'))
            except (ValueError,AttributeError):raise ProbeError('unavailable') from None
        return body.decode()

def atomic(path,value,mode=0o644):
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.snapshot-')
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'w') as f:f.write(value);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def parse_time(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def retention_candidates(runs,now,keep=12,max_age=3600):
    completed=sorted([r for r in runs if r.get('status')=='completed'],key=lambda r:int(r['id']),reverse=True)
    return [int(r['id']) for i,r in enumerate(completed) if i>=keep or now-parse_time(r.get('completed_at',r.get('updated_at')))>max_age]

def gitea(c,path='',data=None,method=None):
    token=(BASE/'secrets/gitea-token').read_text().strip()
    b=request('https://git.'+c['domain']+'/api/v1/repos/infrabox-monitor/canary'+path,c['ca'],'token '+token,data,method)
    return json.loads(b) if b else {}

def canary(c,cleanup=False):
    record=STATE/'canary-active.json'
    if cleanup:
        # Bounded sweep; deletion is restricted to completed runs in the canary repo.
        data=gitea(c,'/actions/runs?limit=50&page=1')
        runs=data.get('workflow_runs',data.get('runs',[]))
        active=json.loads(record.read_text()).get('id') if record.exists() else None
        runs=[r for r in runs if r['id']!=active]
        for rid in retention_candidates(runs,time.time(),c['canary_keep'],c['canary_max_age']):
            gitea(c,'/actions/runs/'+str(rid),method='DELETE')
        return []
    if record.exists():
        old=json.loads(record.read_text());existing=gitea(c,'/actions/runs/'+str(old['id']))
        if existing.get('status')!='completed':
            if time.time()-old['scheduled']>c['canary_queue_timeout']:
                raise ProbeError('timeout')
            raise ProbeDeferred()
        record.unlink()
        if existing.get('conclusion')!='success':raise ProbeError('unavailable')
        return [f'infrabox_canary_last_scheduled_timestamp_seconds {old["scheduled"]}',f'infrabox_canary_last_completed_timestamp_seconds {parse_time(existing['completed_at'])}']
    dispatched=gitea(c,'/actions/workflows/canary.yml/dispatches?return_run_details=true',{'ref':'main'},'POST')
    rid=dispatched.get('workflow_run_id')
    if not isinstance(rid,int):raise ProbeError('invalid_response')
    scheduled=time.time();atomic(record,json.dumps({'id':rid,'scheduled':scheduled}),0o600)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        result=gitea(c,'/actions/runs/'+str(rid))
        if result.get('status')=='completed':
            record.unlink()
            if result.get('conclusion')!='success':raise ProbeError('unavailable')
            return [f'infrabox_canary_last_scheduled_timestamp_seconds {scheduled}',f'infrabox_canary_last_completed_timestamp_seconds {time.time()}']
        time.sleep(3)
    # A queued capacity-one runner is not a failed job. Keep its correlated ID.
    raise ProbeDeferred()

def netbox_dependencies():
    script=Path('/usr/local/libexec/infrabox-monitoring/netbox-probe.py').read_text()
    return json.loads(run(['podman','exec','-i','netbox-worker','/opt/netbox/venv/bin/python','-'],stdin=script,timeout=30))

def probe(ch,c):
    adapter=ch['adapter']; metrics=[]
    if adapter=='unit':
        run(['systemctl','is-active',ch['unit']])
        if ch['unit']=='infrabox-scanner.service':
            connection=http.client.HTTPConnection('localhost',timeout=5)
            connection.sock=socket.socket(socket.AF_UNIX);connection.sock.settimeout(5)
            try:
                connection.sock.connect('/run/infrabox-scanner/api.sock')
                connection.request('GET','/health');response=connection.getresponse()
                body=json.loads(response.read(4096))
                if response.status!=200 or body.get('service')!='infrabox-subnet-scanner':raise ProbeError('invalid_response')
            finally:connection.close()
    elif adapter=='https':
        svc=ch['service'];host=c['claw_host'] if svc=='claw' else svc+'.'+c['domain']
        paths={'git':'/user/login','netbox':'/login/','grafana':'/login','claw':'/','vault':'/ui/'}
        markers={'git':('gitea','infrabox git'),'netbox':('netbox',),'grafana':('grafana',),'claw':('openclaw',),'vault':('openbao',)}
        b=request('https://'+host+paths[svc],c['ca'],limit=2*1024*1024).decode(errors='replace').lower()
        if not any(m in b for m in markers[svc]):raise ProbeError('invalid_response')
        with socket.create_connection((host,443),timeout=10) as sock:
            with ssl.create_default_context(cafile=c['ca']).wrap_socket(sock,server_hostname=host) as tls:
                expiry=ssl.cert_time_to_seconds(tls.getpeercert()['notAfter'])
        metrics=[f'infrabox_certificate_remaining_seconds{{service="{svc}"}} {expiry-time.time()}']
    elif adapter in ('mcp','vault','diagnostics','ready'):
        # MCP has its own 20s runtime deadline and a 10s read deadline. Allow
        # bounded Podman process-start/teardown overhead outside that budget.
        d=json.loads(run(['podman','exec','openclaw','node','/opt/infrabox/monitoring/openclaw-probe.mjs',adapter],timeout=40 if adapter=='mcp' else 25))
        if d.get('success') is not True:raise ProbeError(d.get('reason','invalid_response'))
        metrics=d.get('metrics',[])
    elif adapter=='runner':run(['podman','exec','gitea-runner','wget','-q','-O','-','http://127.0.0.1:9101/readyz'])
    elif adapter=='bao_metrics':
        token=(BASE/'secrets/bao-token').read_text().strip()
        # Renew only this read-only telemetry identity; never rotate on a probe.
        request('https://vault.'+c['domain']+'/v1/auth/token/renew-self',c['ca'],'Bearer '+token,{},'POST')
        text=request('https://vault.'+c['domain']+'/v1/sys/metrics?format=prometheus',c['ca'],'Bearer '+token).decode()
        metrics=[line for line in text.splitlines() if re.match(r'^vault_(core_unsealed|raft_commitTime|raft_apply|runtime_alloc_bytes)([{_ ]|$)',line)]
        if not metrics:raise ProbeError('invalid_response')
    elif adapter=='gitea_metrics':
        raw=Path('/etc/infrabox/gitea/app.ini').read_text();conf=configparser.ConfigParser(interpolation=None);conf.read_string('[root]\n'+raw)
        token=conf.get('metrics','TOKEN')
        text=request('http://127.0.0.1:3000/metrics',c['ca'],'Bearer '+token).decode()
        metrics=[line for line in text.splitlines() if re.match(r'^(gitea_(users|repositories|actions_runners)|go_goroutines|process_resident_memory_bytes) ',line)]
        metrics=[line.replace('go_goroutines','infrabox_gitea_goroutines').replace('process_resident_memory_bytes','infrabox_gitea_memory_bytes') for line in metrics]
        if not metrics:raise ProbeError('invalid_response')
    elif adapter=='openbao':
        d=json.loads(request('https://vault.'+c['domain']+'/v1/sys/health',c['ca']))
        if not d.get('initialized') or d.get('sealed') or d.get('standby'):raise ProbeError('unavailable')
        token=Path('/run/infrabox-openbao-agent/token').read_text().strip()
        identity=json.loads(request(c['certificate_agent_address']+'/v1/auth/token/lookup-self',c['ca'],'Bearer '+token))['data']
        if 'infrabox-openbao-agent' not in identity.get('policies',[]) or identity.get('ttl',0)<=0:raise ProbeError('auth')
    elif adapter in ('postgresql','redis','netbox'):
        result=c['_netbox_future'].result() if '_netbox_future' in c else netbox_dependencies()
        data=result.get(adapter,{})
        if not data.get('success'):raise ProbeError(data.get('reason','unavailable'))
        metrics=data.get('metrics',[])
        if adapter=='postgresql':
            sql="""SET ROLE infrabox_monitor;
SELECT 'infrabox_postgresql_connection_ratio ' || (count(*)::float / current_setting('max_connections')::float)::text FROM pg_stat_activity;
SELECT 'infrabox_postgresql_lock_wait_seconds ' || coalesce(max(extract(epoch FROM now()-query_start)),0)::text FROM pg_stat_activity WHERE wait_event_type='Lock';
"""
            text=run(['podman','exec','-i','--user','postgres','postgresql','psql','-X','-v','ON_ERROR_STOP=1','-At','-U','postgres'],stdin=sql)
            metrics=[x for x in text.splitlines() if x.startswith('infrabox_')]
    elif adapter=='grafana':
        token=(BASE/'secrets/grafana-token').read_text().strip()
        d=json.loads(request('http://127.0.0.1:3001/api/datasources/proxy/uid/infrabox-prometheus/api/v1/query?query=up%7Bjob%3D%22prometheus%22%7D',c['ca'],'Bearer '+token))
        if d.get('status')!='success' or not d['data']['result'] or float(d['data']['result'][0]['value'][1])!=1:raise ProbeError('invalid_response')
    elif adapter=='host':
        if run(['getenforce']).strip()!='Enforcing':raise ProbeError('unavailable')
        run(['systemctl','is-active','chronyd','firewalld','openbao-agent-secret-id.timer','openclaw-token-renew.timer'])
        mount=json.loads(run(['findmnt','-J','-T',c['storage'],'-o','SOURCE,TARGET,OPTIONS']))['filesystems'][0]
        if mount['source']!=c['storage_source'] or mount['target']!=c['storage_mount'] or 'ro' in mount['options'].split(','):raise ProbeError('unavailable')
        if 'Leap status     : Normal' not in run(['chronyc','tracking']):raise ProbeError('unavailable')
    elif adapter in ('canary','retention'):return canary(c,adapter=='retention')
    else:raise ProbeError('internal')
    return metrics

def execute(ch,c,now):
    cid=ch['id']; statefile=STATE/(cid+'.json'); old={}
    if statefile.exists():
        try:old=json.loads(statefile.read_text())
        except ValueError:pass
    if old.get('generation')!=c['generation']:old={}
    start=time.time(); reason=None;metrics=[]
    try:metrics=probe(ch,c)
    except ProbeDeferred:return cid,None
    except ProbeError as e:reason=str(e) if str(e) in REASONS else 'internal'
    except (TimeoutError,subprocess.TimeoutExpired):reason='timeout'
    except Exception:reason='internal'
    end=time.time(); state={'generation':c['generation'],'completed':end,'last_success':old.get('last_success',0) if reason else end}
    atomic(statefile,json.dumps(state),0o600)
    labels='check_id="'+cid+'",component="'+ch['component']+'",integration="'+ch['integration']+'"'
    values={'success':int(reason is None),'duration_seconds':end-start,'last_attempt_timestamp_seconds':start,'last_completed_timestamp_seconds':end,'last_success_timestamp_seconds':state['last_success']}
    lines=[f'infrabox_probe_{k}{{{labels}}} {v}' for k,v in values.items()]
    lines.append(f'infrabox_probe_generation{{{labels},generation="{c["generation"]}"}} 1')
    if reason:lines.append(f'infrabox_probe_failure{{{labels},reason="{reason}"}} 1')
    else:lines.extend(metrics)
    atomic(TEXT/(cid+'.prom'),'\n'.join(lines)+'\n')
    return cid,reason

def main():
    p=argparse.ArgumentParser();p.add_argument('--force',action='append',default=[]);p.add_argument('--lane',choices=['core','canary'],default='core');args=p.parse_args()
    catalog=json.loads((BASE/'catalog.json').read_text());c={**catalog['settings'],'generation':catalog['generation']}
    known={x['id'] for x in catalog['checks']}
    if set(args.force)-known:raise ValueError('Unknown fixed check')
    with (STATE/(args.lane+'.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        now=time.time();due=[]
        for ch in catalog['checks']:
            if ch['adapter'] in ('native','derived'):continue
            if (ch['adapter'] in ('canary','retention')) != (args.lane=='canary'):continue
            statefile=STATE/(ch['id']+'.json')
            try:last=json.loads(statefile.read_text())
            except (OSError,ValueError):last={}
            age=now-last.get('completed',0)
            if ch['id'] in args.force or last.get('generation')!=catalog['generation'] or age<0 or age>=ch['interval']-5:due.append(ch)
        # Canary runs independently: a queued workflow must not stall basic checks.
        with ThreadPoolExecutor(max_workers=1 if args.lane=='canary' else 4) as pool:
            if any(ch['adapter'] in ('postgresql','redis','netbox') for ch in due):
                # Share one runtime startup within this cycle, never cached across observations.
                c['_netbox_future']=pool.submit(netbox_dependencies)
            for result in as_completed([pool.submit(execute,ch,c,now) for ch in due]):
                result.result()
                atomic(TEXT/(args.lane+'.prom'),f'infrabox_{"worker" if args.lane=="core" else "canary_worker"}_heartbeat_timestamp_seconds {time.time()}\n')
        atomic(TEXT/(args.lane+'.prom'),f'infrabox_{"worker" if args.lane=="core" else "canary_worker"}_heartbeat_timestamp_seconds {time.time()}\n')

if __name__=='__main__':main()

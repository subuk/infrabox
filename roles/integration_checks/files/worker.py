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
import selectors
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

def check_lane(check):
    adapter=check['adapter']
    if adapter in ('native','derived'):return None
    if adapter in ('canary','retention'):return 'canary'
    if adapter=='mcp':return 'mcp'
    return 'core'

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

def capture_command(argv,stdin=None,timeout=15,limit=1024*1024):
    """Drain both pipes concurrently, bounding output, input writes and exit time."""
    data=memoryview(stdin.encode() if stdin is not None else b'');offset=0
    output={'stdout':bytearray(),'stderr':bytearray()};finished=False
    p=subprocess.Popen(argv,stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,bufsize=0)
    deadline=time.monotonic()+timeout
    try:
        with selectors.DefaultSelector() as selector:
            for name,stream in [('stdout',p.stdout),('stderr',p.stderr)]:
                os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ,name)
            if p.stdin:
                if data:
                    os.set_blocking(p.stdin.fileno(),False);selector.register(p.stdin,selectors.EVENT_WRITE,'stdin')
                else:p.stdin.close()
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise subprocess.TimeoutExpired(argv,timeout)
                for key,_ in selector.select(remaining):
                    if key.data=='stdin':
                        try:offset+=os.write(key.fd,data[offset:offset+4096])
                        except BrokenPipeError:offset=len(data)
                        except BlockingIOError:continue
                        if offset==len(data):selector.unregister(key.fileobj);key.fileobj.close()
                    else:
                        try:chunk=os.read(key.fd,65536)
                        except BlockingIOError:continue
                        if not chunk:selector.unregister(key.fileobj);key.fileobj.close();continue
                        if len(output[key.data])+len(chunk)>limit:raise ProbeError('invalid_response')
                        output[key.data].extend(chunk)
            p.wait(timeout=max(0,deadline-time.monotonic()))
            finished=True
        return p.returncode,bytes(output['stdout']),bytes(output['stderr'])
    except subprocess.TimeoutExpired as error:
        error.output=bytes(output['stdout']);error.stderr=bytes(output['stderr'])
        raise
    finally:
        if not finished:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            p.wait(timeout=5)
        for stream in (p.stdin,p.stdout,p.stderr):
            if stream and not stream.closed:stream.close()

def run(argv,stdin=None,timeout=15):
    # Pinned Podman supports attached exec without database session bookkeeping.
    # Frequent concurrent probes need no session API; retain the same container
    # user, stdin, exit status and runtime confinement while avoiding lock churn.
    if argv[:2]==['podman','exec']:
        argv=[*argv[:2],'--no-session',*argv[2:]]
    try:rc,body,stderr=capture_command(argv,stdin,timeout)
    except subprocess.TimeoutExpired as error:
        # Keep only fixed diagnostic fields, never command arguments or raw output.
        try:reported=json.loads(error.output[:4096])
        except ValueError:reported={}
        if not isinstance(reported,dict):reported={}
        mode=argv[-1] if '/opt/infrabox/monitoring/openclaw-probe.mjs' in argv and argv[-1] in ('mcp','vault','ready','diagnostics') else 'fixed_command'
        phase=probe_phase(error.stderr[:4096]) if mode=='mcp' else None
        atomic(STATE/'last-command-timeout.json',json.dumps({'mode':mode,'timeout_seconds':timeout,
            'result_reported':bool(reported),'reported_success':reported.get('success') is True,
            'probe_phase':phase,'stderr_bytes':len(error.stderr),'observed_at':time.time()}),0o600)
        raise ProbeError('timeout') from None
    if rc:
        if '/opt/infrabox/monitoring/openclaw-probe.mjs' in argv and argv[-1]=='mcp':
            atomic(STATE/'last-mcp-failure.json',json.dumps({'probe_phase':probe_phase(stderr),
                'observed_at':time.time()}),0o600)
        try:raise ProbeError(json.loads(body).get('reason','unavailable'))
        except (ValueError,AttributeError):raise ProbeError('unavailable') from None
    return body.decode()

def probe_phase(stderr):
    """Retain only the fixed phase/timing protocol, never native diagnostic text."""
    last=None
    for line in stderr.decode(errors='replace').splitlines():
        try:value=json.loads(line)
        except ValueError:continue
        if not isinstance(value,dict) or set(value)!={'infrabox_probe_phase','elapsed_ms'}:continue
        if value['infrabox_probe_phase'] not in ('import_runtime','create_runtime','load_policy','read','dispose'):continue
        elapsed=value['elapsed_ms']
        if type(elapsed) is not int or not 0<=elapsed<=120000:continue
        last=value
    return last

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
    b=request('https://git.'+c['domain']+'/api/v1/repos/svc-monitor/canary'+path,c['ca'],'token '+token,data,method)
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
    if adapter=='discovery':
        d=json.loads(run(['podman','exec','platform-runner','cat','/data/discovery-health.json']))
        if 'workflow_success' not in d and time.time()-d['started']<=1500:raise ProbeDeferred
        success = not (d.get('running') and time.time()-d['started']>1500) and d.get('workflow_success',False)
        values={'workflow_success':int(success),'running':int(d.get('running',False)),
                'last_run_timestamp_seconds':d['started'],'last_completed_timestamp_seconds':d.get('finished',0),'last_successful_reconciliation_timestamp_seconds':d.get('last_success',0),
                'warning_hosts':d.get('counts',{}).get('warning',0),'failed_hosts':d.get('counts',{}).get('failed',0),'unreachable_hosts':d.get('counts',{}).get('unreachable',0),
                'reconciliation_failures':d.get('reconciliation_failures',0),'api_failures':d.get('api_failures',0),
                'auth_failures':d.get('auth_failures',0)}
        if not all(isinstance(v,(int,float)) for v in values.values()):raise ProbeError('invalid_response')
        return [f'infrabox_discovery_{k} {v}' for k,v in values.items()]
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
        paths={'git':'/user/login','netbox':'/login/','grafana':'/login','claw':'/','vault':'/ui/','ldap':'/'}
        markers={'git':('gitea','infrabox git'),'netbox':('netbox',),'grafana':('grafana',),'claw':('openclaw',),'vault':('openbao',),'ldap':('lldap',)}
        b=request('https://'+host+paths[svc],c['ca'],limit=2*1024*1024).decode(errors='replace').lower()
        if not any(m in b for m in markers[svc]):raise ProbeError('invalid_response')
        with socket.create_connection((host,443),timeout=10) as sock:
            with ssl.create_default_context(cafile=c['ca']).wrap_socket(sock,server_hostname=host) as tls:
                expiry=ssl.cert_time_to_seconds(tls.getpeercert()['notAfter'])
        metrics=[f'infrabox_certificate_remaining_seconds{{service="{svc}"}} {expiry-time.time()}']
    elif adapter in ('mcp','vault','diagnostics','ready'):
        # MCP has its own 60s runtime deadline and a 10s read deadline. Allow
        # bounded Podman process-start/teardown overhead outside that budget.
        # Cache only Node's compiled immutable modules in the container tmpfs.
        # Every invocation still loads current policy and performs a real read.
        cache=['--env','NODE_COMPILE_CACHE=/tmp/infrabox-monitoring-compile-cache'] if adapter=='mcp' else []
        d=json.loads(run(['podman','exec',*cache,'openclaw','node','/opt/infrabox/monitoring/openclaw-probe.mjs',adapter],timeout=75 if adapter=='mcp' else 25))
        if d.get('success') is not True:raise ProbeError(d.get('reason','invalid_response'))
        metrics=d.get('metrics',[])
    elif adapter=='runner':run(['podman','exec','gitea-runner','wget','-q','-O','-','http://127.0.0.1:9101/readyz'])
    elif adapter=='bao_metrics':
        credential=json.loads((BASE/'secrets/ldap.json').read_text())
        base='https://vault.'+c['domain']+'/v1/'
        login=json.loads(request(base+'auth/ldap-service/login/'+credential['username'],c['ca'],data={'password':credential['password']},method='POST'))['auth']
        token=login['client_token']
        try:
            if set(login['policies'])!={'infrabox-service','infrabox-monitoring'}:raise ProbeError('permission')
            text=request(base+'sys/metrics?format=prometheus',c['ca'],'Bearer '+token).decode()
        finally:
            request(base+'auth/token/revoke-self',c['ca'],'Bearer '+token,{},'POST')
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
    elif adapter=='identity_ldap':
        run(['podman','exec','lldap','/app/lldap','healthcheck','--config-file','/etc/lldap/lldap.toml'])
        sql="SELECT count(*)>0 AND bool_and(s.ssl) FROM pg_stat_activity a JOIN pg_stat_ssl s USING(pid) WHERE a.usename='lldap' AND a.datname='lldap';"
        if run(['podman','exec','--user','postgres','postgresql','psql','-XAt','-U','postgres','-c',sql]).strip()!='t':raise ProbeError('tls')
        run(['openssl','s_client','-connect','127.0.0.1:16360','-servername','lldap.'+c['internal_domain'],
             '-verify_hostname','lldap.'+c['internal_domain'],'-verify_return_error','-CAfile',c['ca']])
    elif adapter=='identity_oidc':
        issuer='https://vault.'+c['domain']+'/v1/identity/oidc/provider/infrabox'
        d=json.loads(request(issuer+'/.well-known/openid-configuration',c['ca']))
        if d.get('issuer')!=issuer or d.get('token_endpoint')!=issuer+'/token' or d.get('jwks_uri')!=issuer+'/.well-known/keys':raise ProbeError('invalid_response')
        if not json.loads(request(d['jwks_uri'],c['ca'])).get('keys'):raise ProbeError('invalid_response')
    elif adapter=='identity_clients':
        for host,path,marker in [('git','/user/login','/user/oauth2/openbao'),('netbox','/login/','/oauth/login/oidc/'),('grafana','/login','generic_oauth')]:
            html=request('https://'+host+'.'+c['domain']+path,c['ca'],limit=2*1024*1024).decode()
            if marker not in html:raise ProbeError('invalid_response')
    elif adapter=='identity_files':
        files=['openclaw/secrets/vault-token','monitoring/secrets/grafana-token','monitoring/secrets/ldap.json']
        if c['netbox']:files.append('openclaw/secrets/netbox-token')
        if c.get('discovery'):files.append('openclaw/secrets/discovery-token')
        if c.get('platform'):files.append('platform/secrets/bao-token')
        if c['canary']:files.append('monitoring/secrets/gitea-token')
        for name in files:
            file=Path('/etc/infrabox')/name
            if not file.is_file() or file.stat().st_size==0 or file.stat().st_mode & 0o077:raise ProbeError('permission')
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
    p=argparse.ArgumentParser();p.add_argument('--force',action='append',default=[]);p.add_argument('--lane',choices=['core','canary','mcp'],default='core');args=p.parse_args()
    catalog=json.loads((BASE/'catalog.json').read_text());c={**catalog['settings'],'generation':catalog['generation']}
    known={x['id'] for x in catalog['checks']}
    if set(args.force)-known:raise ValueError('Unknown fixed check')
    with (STATE/(args.lane+'.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        now=time.time();due=[]
        for ch in catalog['checks']:
            if check_lane(ch)!=args.lane:continue
            statefile=STATE/(ch['id']+'.json')
            try:last=json.loads(statefile.read_text())
            except (OSError,ValueError):last={}
            age=now-last.get('completed',0)
            if ch['id'] in args.force or last.get('generation')!=catalog['generation'] or age<0 or age>=ch['interval']-5:due.append(ch)
        # Slow MCP materialization and queued workflows cannot hold the core lock.
        heartbeat='worker' if args.lane=='core' else args.lane+'_worker'
        with ThreadPoolExecutor(max_workers=4 if args.lane=='core' else 1) as pool:
            if any(ch['adapter'] in ('postgresql','redis','netbox') for ch in due):
                # Share one runtime startup within this cycle, never cached across observations.
                c['_netbox_future']=pool.submit(netbox_dependencies)
            for result in as_completed([pool.submit(execute,ch,c,now) for ch in due]):
                result.result()
                atomic(TEXT/(args.lane+'.prom'),f'infrabox_{heartbeat}_heartbeat_timestamp_seconds {time.time()}\n')
        atomic(TEXT/(args.lane+'.prom'),f'infrabox_{heartbeat}_heartbeat_timestamp_seconds {time.time()}\n')

if __name__=='__main__':main()

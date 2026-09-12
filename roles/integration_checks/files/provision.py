#!/usr/bin/python3
"""Controller-authorized monitoring identities. Administrative credentials only on stdin."""
import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def atomic(path, value):
    path=Path(path)
    if path.exists() and path.read_text()==value: return False
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.monitoring-')
    try:
        with os.fdopen(fd,'w') as f: f.write(value); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)
    return True

def basic(user,password): return 'Basic '+base64.b64encode((user+':'+password).encode()).decode()

def main(c):
    ctx=ssl.create_default_context(cafile=c['ca']); changed=False
    # NOLOGIN monitoring role; the fixed host worker selects it over local peer auth.
    sql="""SELECT count(*) FROM pg_roles WHERE rolname='infrabox_monitor'"""
    command=['podman','exec','-i','--user','postgres','postgresql','psql','-X','-v','ON_ERROR_STOP=1','-At','-U','postgres']
    def pg(query):
        p=subprocess.run(command,input=query,text=True,capture_output=True,timeout=15)
        if p.returncode:raise RuntimeError('PostgreSQL monitoring role reconciliation failed')
        return p.stdout.strip()
    if pg(sql)!='1':
        pg('CREATE ROLE infrabox_monitor NOLOGIN INHERIT');changed=True
    if pg("SELECT pg_has_role('infrabox_monitor','pg_monitor','MEMBER')")!='t':
        pg('GRANT pg_monitor TO infrabox_monitor');changed=True
    def api(base,path,auth,method='GET',data=None,missing=False):
        req=Request(base+path,json.dumps(data).encode() if data is not None else None,{'Authorization':auth,'Content-Type':'application/json'},method=method)
        try:
            with urlopen(req,context=ctx,timeout=15) as r:
                b=r.read(1024*1024); return json.loads(b) if b else {}
        except HTTPError as e:
            if missing and e.code==404:return None
            raise RuntimeError('Monitoring provisioning '+method+' '+path.split('?')[0]+' HTTP '+str(e.code)) from None
    class Bao(http.client.HTTPConnection):
        def connect(self):
            self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(15);self.sock.connect('/run/infrabox-openbao/api.sock')
    def bao(path,data=None):
        conn=Bao('localhost',timeout=15)
        try:
            conn.request('GET' if data is None else 'POST','/v1/kv/'+path,None if data is None else json.dumps({'data':data}),{'X-Vault-Token':c['root_token'],'Content-Type':'application/json'})
            r=conn.getresponse(); b=r.read(65536)
            if r.status==404:return None
            if r.status>=300:raise RuntimeError('OpenBao provisioning failed')
            return json.loads(b) if b else {}
        finally:conn.close()
    def management(path,data=None,method=None,token=None):
        conn=Bao('localhost',timeout=15)
        try:
            conn.request(method or ('GET' if data is None else 'POST'),'/v1/'+path,None if data is None else json.dumps(data),{'X-Vault-Token':token or c['root_token'],'Content-Type':'application/json'})
            r=conn.getresponse();b=r.read(65536)
            if r.status in (400,403,404):return None
            if r.status>=300:raise RuntimeError('OpenBao monitoring management failed')
            return json.loads(b) if b else {}
        finally:conn.close()
    policy='path "sys/metrics" { capabilities = ["read", "list"] }\npath "auth/token/lookup-self" { capabilities = ["read"] }\npath "auth/token/renew-self" { capabilities = ["update"] }\n'
    existing=management('sys/policies/acl/infrabox-monitoring')
    if existing is None or existing['data']['policy']!=policy:
        management('sys/policies/acl/infrabox-monitoring',{'policy':policy});changed=True
    directory=Path(c['secrets_dir']);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    tokenfile=directory/'bao-token';old=tokenfile.read_text().strip() if tokenfile.exists() else None
    info=management('auth/token/lookup-self',token=old) if old else None
    if info and 'root' in info['data'].get('policies',[]):raise RuntimeError('Refusing unexpected root token')
    valid=info and set(info['data'].get('policies',[]))=={'infrabox-monitoring'} and info['data'].get('period')==604800 and info['data'].get('ttl',0)>0
    if not valid:
        token=management('auth/token/create-orphan',{'policies':['infrabox-monitoring'],'no_default_policy':True,'period':'168h','renewable':True,'display_name':'infrabox-monitoring'})['auth']['client_token']
        if not management('sys/metrics',token=token):
            management('auth/token/revoke',{'token':token})
            raise RuntimeError('Monitoring token verification failed')
        changed=atomic(tokenfile,token+'\n') or changed
        if info:management('auth/token/revoke-accessor',{'accessor':info['data']['accessor']})
    if bao('data/openclaw/monitoring/probe') is None:
        bao('data/openclaw/monitoring/probe',{'value':secrets.token_hex(16)});changed=True
    directory=Path(c['secrets_dir']);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if c['canary']:
        base='https://git.'+c['domain']; admin=basic('admin',c['gitea_password']); user='infrabox-monitor'; repo='canary'
        found=api(base,'/api/v1/users/'+user,admin,missing=True)
        if found is None:
            api(base,'/api/v1/admin/users',admin,'POST',{'username':user,'email':'monitor@'+c['domain'],'password':secrets.token_urlsafe(40),'must_change_password':False});changed=True
        record=bao('data/monitoring/gitea'); token=record['data']['data']['token'] if record else None
        valid=False
        if token:
            try:valid=api(base,'/api/v1/user','token '+token).get('login')==user
            except RuntimeError:pass
        if not valid:
            password=secrets.token_urlsafe(40)
            api(base,'/api/v1/admin/users/'+user,admin,'PATCH',{'source_id':0,'login_name':user,'password':password,'must_change_password':False,'admin':False,'allow_create_organization':False,'allow_git_hook':False,'allow_import_local':False,'max_repo_creation':1})
            token=api(base,'/api/v1/users/'+user+'/tokens',basic(user,password),'POST',{'name':'infrabox-monitor-'+secrets.token_hex(4),'scopes':['read:user','write:repository']})['sha1']
            if api(base,'/api/v1/user','token '+token).get('login')!=user:raise RuntimeError('Gitea monitoring identity mismatch')
            bao('data/monitoring/gitea',{'token':token});changed=True
        auth='token '+token; path='/api/v1/repos/'+user+'/'+repo
        r=api(base,path,auth,missing=True)
        if r is None:
            api(base,'/api/v1/admin/users/'+user+'/repos',admin,'POST',{'name':repo,'private':True,'auto_init':True,'default_branch':'main','description':'InfraBox bounded monitoring canary'});changed=True
            r=api(base,path,auth)
        if not r.get('has_actions'):
            api(base,path,auth,'PATCH',{'has_actions':True});changed=True
        workflow=Path(c['workflow']).read_bytes(); content=api(base,path+'/contents/.gitea/workflows/canary.yml',auth,missing=True)
        if content is None or base64.b64decode(content['content'])!=workflow:
            body={'content':base64.b64encode(workflow).decode(),'message':'Configure fixed InfraBox canary','branch':'main'}
            if content:body['sha']=content['sha']
            api(base,path+'/contents/.gitea/workflows/canary.yml',auth,'PUT' if content else 'POST',body);changed=True
        changed=atomic(directory/'gitea-token',token+'\n') or changed
    base='http://127.0.0.1:3001'; admin=basic('admin',c['grafana_password'])
    record=bao('data/monitoring/grafana'); token=record['data']['data']['token'] if record else None
    valid=False
    if token:
        try:valid=bool(api(base,'/api/datasources/uid/infrabox-prometheus','Bearer '+token))
        except RuntimeError:pass
    if not valid:
        accounts=api(base,'/api/serviceaccounts/search?query=infrabox-monitor',admin)['serviceAccounts']
        account=next((x for x in accounts if x['name']=='infrabox-monitor'),None)
        if account is None:account=api(base,'/api/serviceaccounts',admin,'POST',{'name':'infrabox-monitor','role':'Viewer'})
        if account.get('role')!='Viewer':raise RuntimeError('Unexpected Grafana monitoring privilege')
        token=api(base,'/api/serviceaccounts/'+str(account['id'])+'/tokens',admin,'POST',{'name':'monitor-'+secrets.token_hex(4),'secondsToLive':0})['key']
        api(base,'/api/datasources/uid/infrabox-prometheus','Bearer '+token)
        bao('data/monitoring/grafana',{'token':token});changed=True
    changed=atomic(directory/'grafana-token',token+'\n') or changed
    print(json.dumps({'changed':changed}))

if __name__=='__main__':
    try:main(json.load(sys.stdin))
    except Exception as e:
        safe=str(e) if isinstance(e,RuntimeError) else type(e).__name__
        print('Monitoring identity provisioning failed: '+safe,file=sys.stderr);sys.exit(1)

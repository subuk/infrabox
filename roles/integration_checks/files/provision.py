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
import grafana_service
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
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

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        raise RuntimeError('Monitoring credential request refused redirect')

def main(c):
    ctx=ssl.create_default_context(cafile=c['ca']); changed=False
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=ctx),NoRedirect())
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
            with opener.open(req,timeout=15) as r:
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
    directory=Path(c['secrets_dir']);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    changed=atomic(directory/'ldap.json',json.dumps({'username':'svc-monitor','password':c['monitor_password']})+'\n') or changed
    if bao('data/openclaw/monitoring/probe') is None:
        bao('data/openclaw/monitoring/probe',{'value':secrets.token_hex(16)});changed=True
    directory=Path(c['secrets_dir']);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if c['canary']:
        base='https://git.'+c['domain']; admin=basic(c['admin_username'],c['gitea_password']); user='svc-monitor'; repo='canary'
        own=basic(user,c['monitor_password'])
        found=api(base,'/api/v1/user',own)
        if found.get('login')!=user or found.get('is_admin'):raise RuntimeError('Native monitoring LDAP identity mismatch')
        result=subprocess.run(command+['-d','gitea'],input='SELECT max_repo_creation,allow_create_organization,allow_git_hook,allow_import_local FROM "user" WHERE id='+str(int(found['id']))+';',capture_output=True,text=True,timeout=15)
        if result.returncode:raise RuntimeError('Monitoring native permission inspection failed')
        if result.stdout.strip()!='1|f|f|f':
            api(base,'/api/v1/admin/users/'+user,admin,'PATCH',{'login_name':user,'max_repo_creation':1,'allow_create_organization':False,'allow_git_hook':False,'allow_import_local':False});changed=True
        if api(base,'/api/v1/user/teams?limit=2',own):raise RuntimeError('Monitoring identity has unrelated Gitea teams')
        path='/api/v1/repos/'+user+'/'+repo
        r=api(base,path,own,missing=True)
        if r is None:
            api(base,'/api/v1/admin/users/'+user+'/repos',admin,'POST',{'name':repo,'private':True,'auto_init':True,'default_branch':'main','description':'InfraBox bounded monitoring canary'});changed=True
            r=api(base,path,own)
        if not r['private'] or r['full_name']!=user+'/'+repo:raise RuntimeError('Monitoring canary ownership or privacy differs')
        repositories=api(base,'/api/v1/user/repos?limit=2',own)
        if {r['full_name'] for r in repositories}!={user+'/'+repo}:raise RuntimeError('Monitoring identity has unrelated repository access')
        record=bao('data/monitoring/gitea'); fields=record['data']['data'] if record else {}
        token,token_id=fields.get('token'),fields.get('tokenId')
        tokens=api(base,'/api/v1/users/'+user+'/tokens?limit=50',own)
        if len(tokens)>=50:raise RuntimeError('Monitoring token inventory exceeds the bounded management limit')
        current=next((t for t in tokens if t['id']==token_id),None)
        valid=False
        if token and current and current['name'].startswith('infrabox-monitor-') and set(current['scopes'])=={'read:user','write:repository'}:
            try:valid=api(base,'/api/v1/user','token '+token).get('login')==user
            except RuntimeError:pass
        replacement=not valid
        if replacement:
            created=api(base,'/api/v1/users/'+user+'/tokens',own,'POST',{'name':'infrabox-monitor-'+secrets.token_hex(4),'scopes':['read:user','write:repository']})
            token,token_id=created['sha1'],created['id']
            if api(base,'/api/v1/user','token '+token).get('login')!=user:raise RuntimeError('Gitea monitoring identity mismatch')
            changed=True
        auth='token '+token
        r=api(base,path,auth)
        if not r['permissions'].get('push') or {r['full_name'] for r in api(base,'/api/v1/user/repos?limit=2',auth)}!={user+'/'+repo}:
            raise RuntimeError('Monitoring PAT does not match its canary authorization boundary')
        if not r.get('has_actions'):
            api(base,path,auth,'PATCH',{'has_actions':True});changed=True
        workflow=Path(c['workflow']).read_bytes(); content=api(base,path+'/contents/.gitea/workflows/canary.yml',auth,missing=True)
        if content is None or base64.b64decode(content['content'])!=workflow:
            body={'content':base64.b64encode(workflow).decode(),'message':'Configure fixed InfraBox canary','branch':'main'}
            if content:body['sha']=content['sha']
            api(base,path+'/contents/.gitea/workflows/canary.yml',auth,'PUT' if content else 'POST',body);changed=True
        if replacement:
            bao('data/monitoring/gitea',{'token':token,'tokenId':token_id});changed=True
        changed=atomic(directory/'gitea-token',token+'\n') or changed
        # Publish a positively verified replacement before retiring managed predecessors.
        for old in tokens:
            if old['id']!=token_id and old['name'].startswith('infrabox-monitor-'):
                api(base,'/api/v1/users/'+user+'/tokens/'+str(old['id']),own,'DELETE');changed=True
    base='https://grafana.'+c['domain']
    admin=basic(c['admin_username'],c['gitea_password'])
    me=api(base,'/api/user',admin)
    if me.get('login')!=c['admin_username'] or not me.get('isGrafanaAdmin'):raise RuntimeError('Central Grafana technical identity mismatch')
    monitor=grafana_service.Monitor(api,base,admin)
    record=bao('data/monitoring/grafana'); token=record['data']['data']['token'] if record else None
    token_id=record['data']['data'].get('tokenId') if record else None
    valid=False
    if token:
        try:valid=monitor.valid(token,token_id)
        except RuntimeError:pass
    if not valid:
        token,token_id=monitor.create()
        bao('data/monitoring/grafana',{'token':token,'tokenId':token_id});changed=True
        changed=atomic(directory/'grafana-token',token+'\n') or changed
    changed=atomic(directory/'grafana-token',token+'\n') or changed
    if token_id is None:raise RuntimeError('Native Grafana monitoring token identifier missing')
    changed=monitor.retire_except(token_id) or changed
    print(json.dumps({'changed':changed}))

if __name__=='__main__':
    try:main(json.load(sys.stdin))
    except Exception as e:
        safe=str(e) if isinstance(e,RuntimeError) else type(e).__name__
        print('Monitoring identity provisioning failed: '+safe,file=sys.stderr);sys.exit(1)

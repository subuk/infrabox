#!/usr/bin/env python3
"""Controlled configure acceptance through Gitea; credentials supplied on stdin.

One recorded request per dispatch/PR. An uncertain request is never retried.
Poll/download are read-only and resume from the persistent report.
"""
import base64
import io
import json
from pathlib import Path
import re
import ssl
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
import zipfile

class AcceptanceError(RuntimeError): pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if request.get_method() != 'GET' or urlsplit(request.full_url)[:2] != urlsplit(newurl)[:2]:
            raise AcceptanceError('Redirect left the read-only local Gitea origin')
        return super().redirect_request(request, fp, code, msg, headers, newurl)

class Acceptance:
    def __init__(self,c):
        self.c=c
        self.base=c['url'].rstrip('/')
        if urlsplit(self.base).scheme!='https': raise AcceptanceError('Verified HTTPS required')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',c['repository']): raise AcceptanceError('Invalid repository')
        self.repo='/api/v1/repos/'+c['repository']
        self.auth='Basic '+base64.b64encode((c['username']+':'+c['password']).encode()).decode()
        self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=c['ca'])))
        self.path=Path(c['report'])
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {}
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(json.dumps(self.state,indent=2)+'\n')
    def api(self,path,data=None,method='GET',binary=False):
        url=self.base+path if path.startswith('/') else path
        if urlsplit(url)[:2]!=urlsplit(self.base)[:2]: raise AcceptanceError('API URL left local Gitea')
        try:
            with self.opener.open(Request(url,data=json.dumps(data).encode() if data is not None else None,
                    headers={'Authorization':self.auth,'Content-Type':'application/json'},method=method),timeout=45) as response:
                payload=response.read(8*1024*1024+1)
                if len(payload)>8*1024*1024: raise AcceptanceError('Oversized acceptance response')
                return payload if binary else (json.loads(payload) if payload else {})
        except HTTPError as error:
            raise AcceptanceError('Gitea '+method+' HTTP '+str(error.code)) from None
    def dispatch(self):
        if self.state: raise AcceptanceError('Request already recorded; inspect/poll instead of dispatching again')
        if self.c.get('limit')!='testbox.net.krglv.com': raise AcceptanceError('KRG-10 acceptance is restricted to testbox')
        if type(self.c.get('check',True)) is not bool: raise AcceptanceError('check must be boolean')
        branch=self.api(self.repo+'/branches/master')
        self.state={'kind':'manual','revision':branch['commit']['id'],'dispatch':'uncertain','check':self.c.get('check',True)}
        self.save()
        result=self.api(self.repo+'/actions/workflows/configure.yml/dispatches?return_run_details=true',
            {'ref':'master','inputs':{'limit':self.c['limit'],'check':str(self.state['check']).lower(),'diff':'true'}},'POST')
        self.state.update(dispatch='confirmed',run_id=result['workflow_run_id'],url=result['html_url']);self.save()
    def create_pr(self):
        if self.state: raise AcceptanceError('PR request already recorded; inspect instead of recreating')
        name=self.c['branch']
        if not re.fullmatch(r'krg10-acceptance-[a-z0-9-]+',name): raise AcceptanceError('Invalid acceptance branch')
        base=self.api(self.repo+'/branches/master')['commit']['id']
        self.state={'kind':'pr','base':base,'branch':name,'dispatch':'uncertain'};self.save()
        self.api(self.repo+'/branches',{'new_branch_name':name,'old_ref_name':base},'POST')
        for role in self.c.get('roles',['packages','chrony','sshd']):
            if role not in ('packages','chrony','sshd'): raise AcceptanceError('Invalid acceptance role')
            path='roles/'+role+'/defaults/main.yml'
            current=self.api(self.repo+'/contents/'+path+'?ref='+base)
            content=base64.b64decode(current['content']).decode()+'\n# KRG-10 role-scope acceptance: no desired-state changes.\n'
            self.api(self.repo+'/contents/'+path,{'branch':name,'sha':current['sha'],'content':base64.b64encode(content.encode()).decode(),
                 'message':'Exercise configure role scope for '+role},'PUT')
        result=self.api(self.repo+'/pulls',{'base':'master','head':name,'title':'KRG-10 configure role-scope acceptance',
                    'body':'Temporary acceptance PR: comments only in role defaults. Validate exact PR checkout, impact scope and check-only execution on assigned NetBox hosts. Do not merge.'},'POST')
        self.state.update(dispatch='confirmed',pr=result['number'],revision=result['head']['sha'],url=result['html_url']);self.save()
    def poll(self):
        if self.state.get('dispatch')!='confirmed': raise AcceptanceError('Dispatch is uncertain; inspect Gitea before any retry')
        if not self.state.get('run_id'):
            runs=self.api(self.repo+'/actions/runs?limit=100')['workflow_runs']
            matches=[r for r in runs if r['head_sha']==self.state['revision'] and r.get('event')=='pull_request']
            if len(matches)!=1: return {'stage':'waiting_for_unique_pr_run','matches':len(matches),**self.state}
            self.state['run_id']=matches[0]['id']
        result=self.api(self.repo+'/actions/runs/'+str(self.state['run_id']))
        self.state.update(status=result['status'],conclusion=result.get('conclusion'),run_url=result['html_url'])
        if result['head_sha']!=self.state['revision']: raise AcceptanceError('Run revision mismatch')
        if result['status']=='completed':
            artifacts=self.api(self.repo+'/actions/runs/'+str(self.state['run_id'])+'/artifacts')['artifacts']
            matches=[a for a in artifacts if a['name'].startswith('configure-'+str(self.state['run_id'])+'-') and not a['expired']]
            if len(matches)==1:
                payload=self.api(self.repo+'/actions/artifacts/'+str(matches[0]['id'])+'/zip',binary=True)
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    if sum(i.file_size for i in archive.infolist())>8*1024*1024: raise AcceptanceError('Oversized artifact')
                    if 'run.json' not in archive.namelist(): raise AcceptanceError('Configure manifest missing')
                    manifest=json.loads(archive.read('run.json'))
                    if manifest.get('revision') and manifest['revision']!=self.state['revision']: raise AcceptanceError('Artifact revision mismatch')
                    if str(manifest['run_id'])!=str(self.state['run_id']): raise AcceptanceError('Artifact run mismatch')
                    self.state['configure']=manifest
                    if 'ansible.log' in archive.namelist():
                        self.path.with_suffix('.ansible.log').write_bytes(archive.read('ansible.log'))
                    if manifest.get('hosts') and manifest['hosts']!=['testbox.net.krglv.com']:
                        raise AcceptanceError('Acceptance scope exceeded testbox')
            else:self.state['artifact_count']=len(matches)
        self.save();return self.state
    def close_pr(self):
        if self.state.get('kind')!='pr' or not self.state.get('pr'):raise AcceptanceError('Not an acceptance PR')
        self.api(self.repo+'/pulls/'+str(self.state['pr']),{'state':'closed'},'PATCH')
        self.state['closed']=True;self.save()

if __name__=='__main__':
    try:
        c=json.load(sys.stdin);a=Acceptance(c)
        action=c['action']
        if action=='dispatch':a.dispatch()
        elif action=='create_pr':a.create_pr()
        elif action=='poll':a.poll()
        elif action=='close_pr':a.close_pr()
        else:raise AcceptanceError('Unsupported acceptance action')
        print(json.dumps(a.state))
    except Exception as e:
        print(json.dumps({'error':str(e) if isinstance(e,AcceptanceError) else type(e).__name__}))
        sys.exit(1)

#!/usr/bin/env python3
"""Publish a validated certificate generation, then invoke an allowlisted reload."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

os.umask(0o077)
name=sys.argv[1]
config=json.loads(Path('/etc/infrabox/openbao-agent/certificates.json').read_text())
spec=next(x for x in config['certificates'] if x['name']==name)
if name not in ['openbao','postgresql','redis','nginx']: raise RuntimeError('Unknown certificate consumer')
root=Path(config['root']);dest=root/name
data=json.loads(Path('/etc/infrabox/openbao-agent/rendered',name+'.json').read_text())
serial=hashlib.sha256(data['certificate'].encode()).hexdigest()
generation=dest/'generations'/serial
uid,gid=int(spec['uid']),int(spec['gid'])
def run(args):
    return subprocess.run(args,check=True,capture_output=True).stdout
for directory in [dest,dest/'generations',generation]:
    directory.mkdir(exist_ok=True,parents=True);directory.chmod(0o700);os.chown(directory,uid,gid)
chain='\n'.join(data['ca_chain'])+'\n'
files={'server.crt':data['certificate']+'\n','server.key':data['private_key']+'\n',
       'server-chain.crt':data['certificate']+'\n'+chain,'ca-chain.crt':chain}
for filename,contents in files.items():
    path=generation/filename;path.write_text(contents);path.chmod(0o600 if filename=='server.key' else 0o644);os.chown(path,uid,gid)
    run(['chcon','--reference='+str(dest),str(path)])
run(['chcon','--reference='+str(dest),str(dest/'generations'),str(generation)])
run(['openssl','verify','-purpose','sslserver','-verify_hostname',spec['common_name'],
     '-CAfile',str(root/'root-ca.crt'),'-untrusted',str(generation/'ca-chain.crt'),str(generation/'server.crt')])
for hostname in spec.get('alt_names',[]):
    run(['openssl','x509','-in',str(generation/'server.crt'),'-noout','-checkhost',hostname])
cert_public=run(['openssl','x509','-in',str(generation/'server.crt'),'-pubkey','-noout'])
key_public=run(['openssl','pkey','-in',str(generation/'server.key'),'-pubout'])
if cert_public!=key_public: raise RuntimeError('Private key does not match certificate')
for filename in files:
    link=dest/filename
    if not link.is_symlink(): link.symlink_to('current/'+filename)
temp=dest/'current.new'
if temp.is_symlink(): temp.unlink()
temp.symlink_to('generations/'+serial);os.replace(temp,dest/'current')
unit=name+'.service'
if subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0:
    if name=='nginx':
        run(['nginx','-t']);run(['systemctl','reload',unit])
    elif name=='redis': run(['systemctl','restart',unit])
    else: run(['podman','kill','--signal','HUP',name])

#!/usr/bin/env python3
"""Reconcile fixed application databases without resetting valid passwords."""
import base64
import hashlib
import hmac
import json
import subprocess
import sys

def sql(query, database='postgres'):
    p=subprocess.run(['podman','exec','-i','--user','postgres','postgresql','psql',
                      '-X','-v','ON_ERROR_STOP=1','-At','-U','postgres','-d',database],
                     input=query,text=True,capture_output=True)
    if p.returncode: raise RuntimeError('Database reconciliation query failed')
    return p.stdout.strip()
def quote(value): return "'"+value.replace("'","''")+"'"
def password_matches(password, stored):
    if not stored.startswith('SCRAM-SHA-256$'): return False
    _, parameters, keys=stored.split('$')
    iterations,salt=parameters.split(':');stored_key,_=keys.split(':')
    salted=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.b64decode(salt),int(iterations))
    key=hashlib.sha256(hmac.new(salted,b'Client Key',hashlib.sha256).digest()).digest()
    return hmac.compare_digest(key,base64.b64decode(stored_key))
changed=False
for name,password in json.load(sys.stdin).items():
    if name not in ['gitea','netbox','grafana','lldap']: raise ValueError('Unknown application database')
    exists=sql('SELECT count(*) FROM pg_roles WHERE rolname='+quote(name))=='1'
    if not exists:
        sql('CREATE ROLE '+name+' LOGIN PASSWORD '+quote(password));changed=True
    else:
        stored=sql('SELECT rolpassword FROM pg_authid WHERE rolname='+quote(name))
        if not password_matches(password,stored):
            sql('ALTER ROLE '+name+' PASSWORD '+quote(password));changed=True
    if sql('SELECT count(*) FROM pg_database WHERE datname='+quote(name))!='1':
        sql('CREATE DATABASE '+name+' OWNER '+name);changed=True
    if sql('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='+quote(name))!=name:
        sql('ALTER DATABASE '+name+' OWNER TO '+name);changed=True
    if name=='netbox' and sql("SELECT count(*) FROM pg_extension WHERE extname='ltree'",name)!='1':
        sql('CREATE EXTENSION ltree',name);changed=True
print(json.dumps({'changed':changed}))

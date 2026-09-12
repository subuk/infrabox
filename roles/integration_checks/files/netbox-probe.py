#!/usr/bin/python3
"""Fixed dependency reads inside the NetBox worker; never emits config or secrets."""
import json
import runpy
from datetime import datetime, timezone
import psycopg
import redis
from rq import Worker, Queue

cfg=runpy.run_path('/etc/netbox/config/configuration.py')
results={}
def client(kind):
    d=cfg['REDIS'][kind]
    return redis.Redis(host=d['HOST'],port=d['PORT'],password=d['PASSWORD'],db=d['DATABASE'],
                       ssl=d['SSL'],ssl_ca_certs=d['CA_CERT_PATH'],ssl_cert_reqs='required',
                       ssl_check_hostname=True,socket_connect_timeout=5,socket_timeout=5)
for adapter in ['postgresql','redis','netbox']:
    metrics=[]
    try:
        if adapter=='postgresql':
            d=cfg['DATABASES']['default']
            with psycopg.connect(dbname=d['NAME'],user=d['USER'],password=d['PASSWORD'],host=d['HOST'],
                                  port=d['PORT'],connect_timeout=5,**d['OPTIONS']) as connection:
                with connection.cursor() as cur:
                    cur.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')
                    assert cur.fetchone()[0]
        elif adapter=='redis':
            for kind in ['tasks','caching']:assert client(kind).ping()
            r=client('tasks').info()
            for key in ['rejected_connections','evicted_keys']:
                metrics.append('infrabox_redis_'+key+'_total '+str(r[key]))
            metrics.extend(['infrabox_redis_used_memory_bytes '+str(r['used_memory']),
                            'infrabox_redis_maxmemory_bytes '+str(r['maxmemory'])])
        else:
            connection=client('tasks');workers=Worker.all(connection=connection);queues=['high','default','low']
            assert any(w.last_heartbeat and connection.ttl(w.key)>0 and set(queues)<=set(w.queue_names()) for w in workers)
            oldest=0;length=0
            for name in queues:
                q=Queue(name,connection=connection);jobs=q.get_jobs(0,1);length+=q.count
                if jobs:oldest=max(oldest,(datetime.now(timezone.utc)-jobs[0].enqueued_at).total_seconds())
            metrics.extend(['infrabox_netbox_oldest_job_seconds '+str(oldest),'infrabox_netbox_queue_length '+str(length)])
        results[adapter]={'success':True,'metrics':metrics}
    except Exception:
        results[adapter]={'success':False,'reason':'unavailable'}
print(json.dumps(results))

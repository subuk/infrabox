#!/usr/bin/python3
"""Generate one catalog/rules generation from explicit appliance configuration."""
import hashlib
import json
from pathlib import Path
import sys


def build(c):
    checks = []
    def add(cid, component, adapter, summary, interval=30, severity='critical', integration='', expr=None, warn=None, crit=None, hold='2m'):
        checks.append(dict(id=cid, component=component, adapter=adapter, summary=summary, interval=interval,
                           max_age=interval * 3 + (200 if adapter == 'canary' else 20), severity=severity,
                           integration=integration, runbook=component if component in ('host', 'runner', 'openclaw') else 'services',
                           expr=expr, warn=warn, crit=crit, hold=hold))
    units = ['openbao','openbao-agent','postgresql','redis','gitea','netbox','netbox-worker','nginx','prometheus','grafana','gitea-runner','openclaw']
    if c['scanner']:
        units.append('infrabox-scanner')
    for u in units:
        add('unit_' + u.replace('-', '_'), 'runner' if u == 'gitea-runner' else 'openclaw' if u == 'infrabox-scanner' else u.split('-')[0], 'unit', 'Required service is not active: ' + u)
        checks[-1]['unit'] = u + '.service'
    for svc in ['git', 'netbox', 'vault', 'grafana', 'claw']:
        add('https_' + svc, {'git':'gitea','vault':'openbao','claw':'openclaw'}.get(svc,svc), 'https', 'Verified HTTPS interface failed: ' + svc)
        checks[-1]['service'] = svc
    for cid,comp,adapter,summary,integ in [
        ('postgresql_query','postgresql','postgresql','PostgreSQL authenticated query failed',''),
        ('redis_ping','redis','redis','Redis authenticated TLS PING failed',''),
        ('netbox_worker','netbox','netbox','NetBox worker or application dependency failed','dependencies'),
        ('runner_ready','runner','runner','Runner readiness failed','gitea'),
        ('openclaw_ready','openclaw','ready','Gateway readiness failed',''),
        ('openclaw_vault','openclaw','vault','OpenClaw Vault secret resolution failed','openbao'),
        ('openclaw_diagnostics','openclaw','diagnostics','Native Gateway diagnostics unavailable',''),
        ('openbao_metrics','openbao','bao_metrics','OpenBao native telemetry or token renewal failed',''),
        ('gitea_metrics','gitea','gitea_metrics','Gitea native metrics unavailable',''),
        ('openbao_health','openbao','openbao','OpenBao is sealed, uninitialized or unavailable',''),
        ('grafana_datasource','grafana','grafana','Grafana cannot query its Prometheus datasource','prometheus'),
        ('host_contract','host','host','Host storage, security or clock contract failed',''),
    ]:
        add(cid, comp, adapter, summary, interval=60, integration=integ)
    if c['netbox']:
        add('openclaw_netbox','openclaw','mcp','OpenClaw cannot read NetBox through its MCP runtime',60,integration='netbox')
    if c['canary']:
        add('runner_canary','runner','canary','Runner canary failed or did not complete',300,severity='warning',integration='gitea')
        add('canary_retention','runner','retention','Canary history cleanup failed',300,severity='warning')
    mounts = '|'.join(sorted({'/', c.get('storage_mount', '/')}))
    filesystem = '{mountpoint=~'+json.dumps(mounts)+'}'
    add('host_disk','host','native','Required filesystem capacity is low',expr='min(node_filesystem_avail_bytes'+filesystem+' / node_filesystem_size_bytes'+filesystem+')',warn='< 0.15',crit='< 0.05',hold='5m')
    add('host_inodes','host','native','Required filesystem inodes are low',expr='min(node_filesystem_files_free'+filesystem+' / node_filesystem_files'+filesystem+')',warn='< 0.15',crit='< 0.05',hold='5m')
    add('host_memory','host','native','Available host memory is low',expr='node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes',warn='< 0.1',hold='10m')
    add('host_cpu','host','native','Sustained CPU utilization is high',expr='1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))',warn='> 0.9',hold='10m')
    for cid, comp, metric, warn, crit in [
        ('postgresql_connections','postgresql','infrabox_postgresql_connection_ratio','> 0.8','> 0.95'),
        ('postgresql_lock_wait','postgresql','infrabox_postgresql_lock_wait_seconds','> 60','> 300'),
        ('redis_rejections','redis','increase(infrabox_redis_rejected_connections_total[5m])','> 0',None),
        ('redis_evictions','redis','increase(infrabox_redis_evicted_keys_total[5m])','> 0',None),
        ('netbox_queue','netbox','infrabox_netbox_oldest_job_seconds','> 300','> 900'),
    ]:
        add(cid,comp,'derived',cid.replace('_',' '),interval=60,expr=metric,warn=warn,crit=crit,hold='5m')
    for service in ['git','netbox','vault','grafana','claw']:
        add('certificate_'+service,'openbao','derived','Served certificate renewal is overdue: '+service,expr='infrabox_certificate_remaining_seconds{service="'+service+'"}',warn='< '+str(c['cert_warn']),crit='< '+str(c['cert_critical']),hold='0s')
    generation = hashlib.sha256(json.dumps({'settings':c,'checks':checks,'implementation':Path(__file__).read_text()},sort_keys=True).encode()).hexdigest()[:16]
    catalog = {'generation':generation,'checks':checks,'rule_groups':['infrabox-observations','infrabox-health'],'settings':c}
    obs, rules = [], []
    for ch in checks:
        cid=ch['id']; labels={'check_id':cid,'component':ch['component'],'integration':ch['integration']}
        if ch['adapter'] in ('native','derived'):
            expr=ch['expr']; source = expr
            if ch['adapter']=='native':
                metric = 'node_filesystem_avail_bytes' if cid=='host_disk' else 'node_filesystem_files_free' if cid=='host_inodes' else 'node_memory_MemAvailable_bytes' if cid=='host_memory' else 'node_cpu_seconds_total'
                freshness='min(timestamp('+metric+'))'
            else:
                parent='postgresql_query' if cid.startswith('postgresql_') else 'redis_ping' if cid.startswith('redis_') else 'netbox_worker' if cid=='netbox_queue' else 'https_'+cid.removeprefix('certificate_')
                freshness='infrabox_probe_last_completed_timestamp_seconds{check_id="'+parent+'"}'
            fail='(' + expr + ') ' + (ch['warn'] or ch['crit'])
            obs.append({'record':'infrabox:raw_failure','expr':'(count('+fail+') or vector(0))','labels':labels})
            obs.append({'record':'infrabox:observation','expr':'min('+freshness+') and (count('+source+') > 0)','labels':labels})
        else:
            fail='infrabox_probe_success{check_id="'+cid+'"} == 0'
            obs.append({'record':'infrabox:raw_failure','expr':'(count('+fail+') or vector(0))','labels':labels})
            obs.append({'record':'infrabox:observation','expr':'infrabox_probe_last_completed_timestamp_seconds{check_id="'+cid+'"}','labels':labels})
        for severity, condition in [('warning',ch['warn']),('critical',ch['crit'])] if ch['expr'] else [(ch['severity'],None)]:
            if ch['expr'] and not condition: continue
            alert_expr='('+ch['expr']+') '+condition if ch['expr'] else fail
            rules.append({'alert':'InfraBoxCheckFailed','expr':alert_expr,'for':ch['hold'],
                          'labels':{**labels,'severity':severity},'annotations':{'summary':ch['summary'],'runbook_id':ch['runbook'],'runbook_path':'docs/runbooks/'+ch['runbook']+'.md','impact':ch['summary']}})
    for rule in obs:
        if rule['record']!='infrabox:observation':continue
        check=next(ch for ch in checks if ch['id']==rule['labels']['check_id'])
        if check['adapter']=='native':continue
        cid=check['id']
        if check['adapter']=='derived':
            cid='postgresql_query' if cid.startswith('postgresql_') else 'redis_ping' if cid.startswith('redis_') else 'netbox_worker' if cid=='netbox_queue' else 'https_'+cid.removeprefix('certificate_')
        rule['expr']+=' and on() (count(infrabox_probe_generation{check_id="'+cid+'",generation="'+generation+'"}) > 0)'
    expected='infrabox_check_expected' 
    fresh='(time() - infrabox:observation <= on(check_id) infrabox_check_max_age_seconds) and on(check_id) (time() - infrabox:observation >= -5)'
    rules.extend([
        {'record':'infrabox:check_fresh','expr':fresh},
        {'record':'infrabox:check_state','expr':expected+' unless on(check_id) infrabox:check_fresh','labels':{'state':'unknown'}},
        {'record':'infrabox:check_state','expr':expected+' and on(check_id) infrabox:check_fresh and on(check_id) ALERTS{alertname="InfraBoxCheckFailed",severity="critical",alertstate="firing"}','labels':{'state':'critical'}},
        {'record':'infrabox:check_state','expr':expected+' and on(check_id) infrabox:check_fresh and on(check_id) (infrabox:raw_failure > 0) unless on(check_id) ALERTS{alertname="InfraBoxCheckFailed",severity="critical",alertstate="firing"}','labels':{'state':'warning'}},
        {'record':'infrabox:check_state','expr':expected+' and on(check_id) infrabox:check_fresh unless on(check_id) (infrabox:raw_failure > 0)','labels':{'state':'healthy'}},
        {'record':'infrabox:coverage_ok','expr':f'(count(infrabox_check_expected) == bool {len(checks)}) * (count(infrabox:check_fresh) == bool {len(checks)}) * (count(up{{job=~"prometheus|node"}}) == bool 2) * (min(up{{job=~"prometheus|node"}}) == bool 1) * (min(prometheus_config_last_reload_successful) == bool 1) * (sum(increase(prometheus_rule_evaluation_failures_total[2m])) == bool 0) * (time() - min(infrabox_worker_heartbeat_timestamp_seconds) < bool 90)'},
        {'alert':'MonitoringCoverageIncomplete','expr':'infrabox:coverage_ok != 1 or absent(infrabox:coverage_ok)','for':'1m','labels':{'severity':'warning','component':'prometheus','check_id':'monitoring_coverage'},'annotations':{'summary':'Monitoring evidence is incomplete','runbook_id':'monitoring','runbook_path':'docs/runbooks/monitoring.md'}},
    ])
    rules.append({'record':'infrabox:rules_generation','expr':'vector(1)','labels':{'generation':generation}})
    catalog['rule_counts']={'infrabox-observations':len(obs),'infrabox-health':len(rules)}
    # All JSON documents are valid YAML; no runtime PyYAML dependency required.
    return catalog, {'groups':[{'name':'infrabox-observations','rules':obs},{'name':'infrabox-health','rules':rules}]}

if __name__=='__main__':
    c=json.load(sys.stdin); out=Path(c.pop('output')); out.mkdir(parents=True,exist_ok=True)
    catalog,rules=build(c)
    changed=False
    for name,value in [('catalog.json',catalog),('rules.json',rules)]:
        body=json.dumps(value,indent=2)+'\n'
        if not (out/name).exists() or (out/name).read_text()!=body:
            (out/name).write_text(body);changed=True
    text=[]
    for ch in catalog['checks']:
        labels='check_id="'+ch['id']+'",component="'+ch['component']+'",integration="'+ch['integration']+'"'
        text.extend([f'infrabox_check_expected{{{labels}}} 1', f'infrabox_check_max_age_seconds{{{labels}}} {ch["max_age"]}'])
    text.append('infrabox_catalog_info{generation="'+catalog['generation']+'"} 1')
    body='\n'.join(text)+'\n'
    if not (out/'catalog.prom').exists() or (out/'catalog.prom').read_text()!=body:
        (out/'catalog.prom').write_text(body);changed=True
    print(json.dumps({'changed':changed}))

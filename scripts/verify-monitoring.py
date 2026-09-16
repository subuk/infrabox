#!/usr/bin/python3
"""Trusted deployment gate: fresh distinct observations, no model polling."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,'/usr/local/libexec/infrabox-monitoring')
import health

DEPENDENCIES={
 'openclaw':{'openclaw'},'netbox':{'netbox','openclaw'},'gitea':{'gitea','runner'},
 'runner':{'runner'},'postgresql':{'postgresql','netbox','gitea','grafana','openclaw','runner'},
 'redis':{'redis','netbox','openclaw'},'nginx':{'nginx','netbox','gitea','openbao','grafana','openclaw'},
 'openbao':{'openbao','openclaw','postgresql','redis','netbox','gitea','grafana'},
 'monitoring':None,'host':None,
}

def stable(samples,completion,window=120):
    times=sorted(set(t for t in samples if t>completion))
    return len(times)>=3 and times[-1]-times[0]>=window

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',action='store_true');p.add_argument('--component',choices=sorted(DEPENDENCIES),default='monitoring')
    p.add_argument('--revision',default='unspecified');p.add_argument('--timeout',type=int,default=300)
    args=p.parse_args();config='/etc/infrabox/monitoring/catalog.json';baseline=Path('/var/lib/infrabox-monitoring/deploy-baseline.json')
    if args.baseline:
        if Path(config).exists():data=health.load_snapshot(config)[0]
        else:data={'status':'unknown','coverage_complete':False,'issues':[],'bootstrap':True}
        baseline.parent.mkdir(parents=True,exist_ok=True,mode=0o700);baseline.write_text(json.dumps(data));baseline.chmod(0o600);return
    from worker import check_lane
    before=json.loads(baseline.read_text()) if baseline.exists() else {'bootstrap':True,'issues':[]}
    catalog=json.loads(Path(config).read_text());components=DEPENDENCIES[args.component]
    affected=[c for c in catalog['checks'] if components is None or c['component'] in components]
    ids={c['id'] for c in affected};samples={cid:set() for cid in ids};observed_failures=set()
    completion=time.time();deadline=time.monotonic()+args.timeout;next_probe=0;attempts=0;reason='insufficient_fresh_observations';state='inconclusive';running=[]
    while time.monotonic()<deadline:
        if time.monotonic()>=next_probe and attempts<max(3, min(10, args.timeout // 60)):
            for lane in ['core','canary','mcp']:
                chosen=[c['id'] for c in affected if check_lane(c)==lane]
                if chosen:
                    command=['python3','/usr/local/libexec/infrabox-monitoring/worker.py','--lane',lane]
                    for cid in chosen:command+=['--force',cid]
                    running.append(subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            attempts+=1;next_probe=time.monotonic()+60
        current,observations,raw=health.load_snapshot(config)
        for cid in ids:
            if cid in observations and observations[cid]>completion:samples[cid].add(observations[cid])
        affected_issues=[i for i in current['issues'] if i['id'] in ids]
        observed_failures.update((set(raw)|{i['id'] for i in affected_issues})&ids)
        if not current['coverage_complete']:observed_failures.add('monitoring_coverage')
        if current['coverage_complete'] and not set(raw)&ids and not affected_issues:
            if all(stable(samples[cid],completion) for cid in ids):state='passed';reason='fresh_stable_observations';break
        else:
            # A recovered condition must establish a new successful stabilization window.
            invalid=ids if not current['coverage_complete'] else (set(raw)|{i['id'] for i in affected_issues})&ids
            for cid in invalid:samples[cid].clear()
            if any(i['state']=='critical' for i in affected_issues):reason='affected_failure'
        time.sleep(5)
    for process in running:
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:pass # Native worker remains bounded by its own deadlines.
    preexisting={i['id'] for i in before.get('issues',[])}
    if preexisting & ids and not before.get('bootstrap'):
        state='inconclusive';reason='preexisting_affected_issue'
    elif reason=='affected_failure' and state!='passed':state='failed'
    result={'status':state,'reason':reason,'revision':args.revision,'generation':catalog['generation'],'completed_at':health.stamp(completion),
            'observed_until':health.stamp(time.time()),'baseline_issues':sorted(preexisting),'new_issues':sorted({i['id'] for i in current['issues']}-preexisting),
            'observed_failures':sorted(observed_failures),'unstable_checks':sorted(cid for cid in ids if not stable(samples[cid],completion)),
            'affected_checks':len(ids),'minimum_distinct_observations':min(map(len,samples.values()),default=0)}
    print(json.dumps(result));return 0 if state=='passed' else 1

if __name__=='__main__':sys.exit(main())

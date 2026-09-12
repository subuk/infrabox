#!/usr/bin/python3
"""Exercise deletion only in the explicitly disposable monitoring canary repo."""
import fcntl
import json
from pathlib import Path
import sys
sys.path.insert(0,'/usr/local/libexec/infrabox-monitoring')
import worker

c=json.loads((worker.BASE/'catalog.json').read_text())['settings']
with (worker.STATE/'canary.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before=worker.gitea(c,'/actions/runs?limit=50')['workflow_runs']
    if sum(r['status']=='completed' for r in before)<2:
        raise RuntimeError('Need two completed disposable canaries before retention acceptance')
    active={r['id'] for r in before if r['status']!='completed'}
    worker.canary({**c,'canary_keep':1},cleanup=True)
    after=worker.gitea(c,'/actions/runs?limit=50')['workflow_runs']
    assert active<={r['id'] for r in after}
    completed=sum(r['status']=='completed' for r in after)
    protected=json.loads((worker.STATE/'canary-active.json').read_text())['id'] if (worker.STATE/'canary-active.json').exists() else None
    assert completed<=1+int(protected is not None)
    assert len(after)<len(before)
    print(json.dumps({'test':'bounded disposable canary retention','status':'passed','runs_before':len(before),
                      'runs_after':len(after),'active_preserved':len(active),'configured_keep':c['canary_keep'],
                      'configured_max_age_seconds':c['canary_max_age']}))

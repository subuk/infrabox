#!/usr/bin/env python3
"""Generate promtool semantic fixtures against the actual rule generator."""
import importlib.util
import json
from pathlib import Path
import sys
spec=importlib.util.spec_from_file_location('configure',Path(__file__).resolve().parents[1]/'roles/integration_checks/files/configure.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c,r=m.build({'scanner':True,'netbox':True,'canary':True,'cert_warn':86400,'cert_critical':21600})
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
(out/'rules.json').write_text(json.dumps(r))
labels='check_id="unit_openbao",component="openbao",integration=""'
def series(name,values,extra=''):return {'series':name+'{'+labels+extra+'}','values':values}
def expected(state):return {'labels':'infrabox:check_state{'+labels+',state="'+state+'"}','value':1}
base=[series('infrabox_check_expected','1+0x30'),series('infrabox_check_max_age_seconds','110+0x30'),series('infrabox_probe_generation','1+0x30',',generation="'+c['generation']+'"')]
tests=[
 {'name':'Failure is visible while pending, then fires, then recovers','interval':'30s','input_series':base+[series('infrabox_probe_success','1 1 0 0 0 0 0 0 1+0x22'),series('infrabox_probe_last_completed_timestamp_seconds','0+30x30')],
 'promql_expr_test':[{'expr':'infrabox:check_state{check_id="unit_openbao"}','eval_time':t,'exp_samples':[expected(s)]} for t,s in [('30s','healthy'),('90s','warning'),('210s','critical'),('270s','healthy')]]},
 {'name':'Missing completion is unknown','interval':'30s','input_series':base,'promql_expr_test':[{'expr':'infrabox:check_state{check_id="unit_openbao"}','eval_time':'60s','exp_samples':[expected('unknown')]}]},
 {'name':'Fresh scrapes of frozen success are unknown','interval':'30s','input_series':base+[series('infrabox_probe_success','1+0x30'),series('infrabox_probe_last_completed_timestamp_seconds','1+0x30')],'promql_expr_test':[{'expr':'infrabox:check_state{check_id="unit_openbao"}','eval_time':'180s','exp_samples':[expected('unknown')]}]},
 {'name':'Future observation is unknown','interval':'30s','input_series':base+[series('infrabox_probe_success','1+0x30'),series('infrabox_probe_last_completed_timestamp_seconds','9999+0x30')],'promql_expr_test':[{'expr':'infrabox:check_state{check_id="unit_openbao"}','eval_time':'30s','exp_samples':[expected('unknown')]}]},
 {'name':'Old configuration generation cannot pass','interval':'30s','input_series':base[:2]+[series('infrabox_probe_generation','1+0x30',',generation="old"'),series('infrabox_probe_success','1+0x30'),series('infrabox_probe_last_completed_timestamp_seconds','0+30x30')],'promql_expr_test':[{'expr':'infrabox:check_state{check_id="unit_openbao"}','eval_time':'60s','exp_samples':[expected('unknown')]}]},
]
(out/'test.json').write_text(json.dumps({'rule_files':['rules.json'],'evaluation_interval':'30s','tests':tests}))

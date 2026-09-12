import importlib.util
import itertools
import json
from pathlib import Path
import unittest

def module(name):
    spec=importlib.util.spec_from_file_location('monitor_'+name,Path('roles/integration_checks/files')/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
health=module('health');worker=module('worker');configure=module('configure')

class HealthTests(unittest.TestCase):
    def catalog(self,n=1):
        return {'generation':'test','rule_groups':['observations','health'],'checks':[{'id':'c'+str(i),'component':'netbox','max_age':90,'summary':'Test check','runbook':'services'} for i in range(n)]}
    def fetcher(self,states=('healthy',),observed=995,raw=0,groups=('observations','health'),coverage=1,generation='test'):
        values=[]
        def add(name,value,**labels):values.append({'metric':{'__name__':name,**labels},'value':[1000,str(value)]})
        add('infrabox_catalog_info',1,generation=generation);add('infrabox:coverage_ok',coverage)
        for i,state in enumerate(states):
            add('infrabox:check_state',1,check_id='c'+str(i),state=state)
            add('infrabox:observation',observed,check_id='c'+str(i));add('infrabox:raw_failure',raw,check_id='c'+str(i))
        def fetch(path,params):
            if path.endswith('rules'):return {'groups':[{'name':g,'lastEvaluation':health.stamp(995),'rules':[{'health':'ok'}]} for g in groups]}
            return {'resultType':'vector','result':values}
        return fetch
    def test_precedence_truth_table(self):
        for states in itertools.product(health.STATES,repeat=3):
            expected='critical' if 'critical' in states else 'unknown' if 'unknown' in states else 'warning' if 'warning' in states else 'healthy'
            self.assertEqual(health.overall(states),expected)
    def test_healthy_requires_complete_fresh_evidence(self):
        r,obs,_=health.snapshot(self.catalog(),self.fetcher(),1000)
        self.assertEqual(r['status'],'healthy');self.assertTrue(r['coverage_complete']);self.assertEqual(obs,{'c0':995})
        for kwargs in [{'observed':1},{'observed':1100},{'groups':('observations',)},{'generation':'other'},{'coverage':0},{'states':()}]:
            with self.subTest(kwargs=kwargs):
                r,_,_=health.snapshot(self.catalog(),self.fetcher(**kwargs),1000)
                self.assertEqual(r['status'],'unknown');self.assertFalse(r['coverage_complete'])
    def test_previous_generation_in_prometheus_lookback_does_not_hide_current(self):
        fetch=self.fetcher()
        def overlap(path,params):
            d=fetch(path,params)
            if path.endswith('query'):
                d['result'].append({'metric':{'__name__':'infrabox_catalog_info','generation':'previous'},'value':[1000,'1']})
            return d
        r,_,_=health.snapshot(self.catalog(),overlap,1000)
        self.assertEqual(r['status'],'healthy');self.assertTrue(r['coverage_complete'])
    def test_outage_returns_structured_unknown(self):
        def broken(*_):raise TimeoutError()
        r,_,_=health.snapshot(self.catalog(),broken,1000)
        self.assertEqual(r['status'],'unknown');self.assertFalse(r['coverage_complete'])
    def test_critical_survives_partial_coverage_and_truncation(self):
        r,_,_=health.snapshot(self.catalog(80),self.fetcher(states=('critical',)*80,coverage=0),1000)
        self.assertEqual(r['status'],'critical');self.assertFalse(r['coverage_complete']);self.assertTrue(r['truncated'])
        self.assertLessEqual(len(json.dumps(r).encode()),8192);self.assertLessEqual(len(r['issues']),20)
        self.assertEqual(r['issues_total'],81)
    def test_pending_failure_cannot_hide_from_verifier(self):
        r,_,raw=health.snapshot(self.catalog(),self.fetcher(raw=1),1000)
        self.assertEqual(r['status'],'warning');self.assertEqual(raw,['c0']);self.assertEqual(r['issues'][0]['alert_state'],'pending')
    def test_invalid_component_rejected(self):
        with self.assertRaises(ValueError):health.snapshot(self.catalog(),self.fetcher(),1000,component='http://example.com')

class CanaryRetentionTests(unittest.TestCase):
    def test_count_and_age_do_not_delete_active_runs(self):
        runs=[{'id':i,'status':'completed','updated_at':health.stamp(9990)} for i in range(1,16)]
        runs.append({'id':99,'status':'in_progress','updated_at':health.stamp(1)})
        runs.append({'id':100,'status':'completed','updated_at':health.stamp(1)})
        delete=worker.retention_candidates(runs,10000,12,3600)
        self.assertIn(100,delete);self.assertNotIn(99,delete);self.assertIn(1,delete);self.assertNotIn(15,delete)
    def test_empty_history(self):self.assertEqual(worker.retention_candidates([],100),[])

class CatalogTests(unittest.TestCase):
    def settings(self):return {'scanner':True,'netbox':True,'canary':True,'cert_warn':86400,'cert_critical':21600}
    def test_disabled_features_removed_from_expected_contract(self):
        enabled,_=configure.build(self.settings());disabled,_=configure.build({**self.settings(),'netbox':False,'scanner':False,'canary':False})
        self.assertIn('openclaw_netbox',{c['id'] for c in enabled['checks']})
        for cid in ['openclaw_netbox','runner_canary','unit_infrabox_scanner']:
            self.assertNotIn(cid,{c['id'] for c in disabled['checks']})
        self.assertNotEqual(enabled['generation'],disabled['generation'])
    def test_unique_check_ids(self):
        c,_=configure.build(self.settings());ids=[x['id'] for x in c['checks']];self.assertEqual(len(ids),len(set(ids)))

if __name__=='__main__':unittest.main()

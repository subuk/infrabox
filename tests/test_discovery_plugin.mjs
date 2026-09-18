import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {deflateRawSync} from 'node:zlib';
import {Discovery,selection} from '../roles/openclaw/files/discovery/client.mjs';
import {crc32,readZip,validateArtifact} from '../roles/openclaw/files/discovery/archive.mjs';
const revision='a'.repeat(40), hosts=[{name:'testbox.example.com',object_type:'device',object_id:12}];
const record={run_id:178,revision,pattern:hosts[0].name,hosts};
function manifest(overrides={}) {return {schema_version:2,run_id:'178',attempt:'1',revision,pattern:record.pattern,started_at:'2026-09-13T12:00:00Z',finished_at:'2026-09-13T12:01:00Z',outcome:'success',collection_outcome:'success',ansible_return_code:0,hosts:[{...hosts[0],status:'succeeded',reconciliation_status:'succeeded',changes:[],warnings:[],errors:[]}],counts:{selected:1,collected:1,reconciled:1,changed:0,unchanged:1,warning:0,failed:0,unreachable:0},...overrides};}
function zip(entries) {
  const parts=[],central=[];let offset=0;
  for(const [name,value] of entries) {
    const n=Buffer.from(name),data=Buffer.from(value),compressed=deflateRawSync(data),crc=crc32(data);
    const local=Buffer.alloc(30);local.writeUInt32LE(0x04034b50);local.writeUInt16LE(8,8);local.writeUInt32LE(crc,14);local.writeUInt32LE(compressed.length,18);local.writeUInt32LE(data.length,22);local.writeUInt16LE(n.length,26);
    const c=Buffer.alloc(46);c.writeUInt32LE(0x02014b50);c.writeUInt16LE(8,10);c.writeUInt32LE(crc,16);c.writeUInt32LE(compressed.length,20);c.writeUInt32LE(data.length,24);c.writeUInt16LE(n.length,28);c.writeUInt32LE(offset,42);
    parts.push(local,n,compressed);central.push(c,n);offset+=local.length+n.length+compressed.length;
  }
  const dir=Buffer.concat(central),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(entries.length,8);end.writeUInt16LE(entries.length,10);end.writeUInt32LE(dir.length,12);end.writeUInt32LE(offset,16);
  return Buffer.concat([...parts,dir,end]);
}
function archive(m=manifest()) {return zip([['reconciliation-summary.json',JSON.stringify(m)]]);}
async function fixture(t,override) {
  const stateDir=await mkdtemp(join(tmpdir(),'discovery-'));t.after(()=>rm(stateDir,{recursive:true,force:true}));
  const c={giteaUrl:'https://git.example.com',netboxUrl:'https://netbox.example.com',organization:'platform',repository:'automation',branch:'master',managedTag:'infrabox-managed',stateDir,tokenFile:'gitea',netboxTokenFile:'netbox'};
  const calls=[];
  const deps={read:async()=> 'secret-fixture',transport:async(url,options)=>{
    calls.push([url,options]);
    const fallback=()=>{
      if(url.host==='netbox.example.com') {
        if(url.searchParams.has('name'))return {count:url.pathname.includes('virtualization')?0:1,results:url.pathname.includes('virtualization')?[]:[{id:12}]};
        return {id:12,name:hosts[0].name,tags:[{slug:c.managedTag}]};
      }
      if(url.pathname.endsWith('/branches/master'))return {commit:{id:revision}};
      if(url.pathname.endsWith('/dispatches'))return {workflow_run_id:178,html_url:'https://git.example.com/platform/automation/actions/runs/5'};
      if(url.pathname.endsWith('/runs/178'))return {id:178,head_sha:revision,status:'completed',conclusion:'success'};
      if(url.pathname.endsWith('/artifacts'))return {artifacts:[{id:5,name:'reconciliation-178-1',expired:false},{id:6,name:'reconciliation-178-2',expired:false}]};
      if(url.pathname.endsWith('/artifacts/5/zip'))return archive();
      if(url.pathname.endsWith('/artifacts/6/zip'))return archive(manifest({attempt:'2'}));
      throw Error('Unexpected route '+url.pathname);
    };
    const result=override?await override(url,options,fallback):fallback();
    return Buffer.isBuffer(result)?result:Buffer.from(JSON.stringify(result));
  }};
  return {c,deps,calls,client:new Discovery(c,deps)};
}
test('exact names reject patterns, empty sets and ambiguous identities',()=>{
  assert.deepEqual(selection(hosts),hosts);
  for(const name of ['all','ungrouped','is_virtual','site_lab','tag_managed','web*','a,b','a:!b','@file','foo\n','--limit=all'])assert.throws(()=>selection([{...hosts[0],name}]));
  assert.throws(()=>selection([]));assert.throws(()=>selection([...hosts,...hosts]));
});
test('dispatches once, persists ID through new client, rejects changed reuse',async t=>{
  const f=await fixture(t);const params={request_id:'request-0001',hosts};
  assert.equal((await f.client.start(params)).run_id,178);
  assert.equal((await new Discovery(f.c,f.deps).start(params)).run_id,178);
  assert.equal(f.calls.filter(([,o])=>o.method==='POST').length,1);
  assert.deepEqual(f.calls.find(([,o])=>o.method==='POST')[1].body,{ref:'master',inputs:{targets:hosts[0].name}});
  await assert.rejects(()=>f.client.start({...params,hosts:[{...hosts[0],name:'other'}]}));
  await assert.rejects(()=>f.client.start({...params,workflow:'other.yml'}));
  assert.equal((await f.client.status({request_id:params.request_id})).artifacts.length,2);
});
test('lost dispatch response never redispatches, even after restart',async t=>{
  const f=await fixture(t,(u,o,fallback)=>{if(o.method==='POST')throw Error('timeout with server possibly running');return fallback();});
  const p={request_id:'request-0002',hosts};assert.equal((await f.client.start(p)).state,'dispatch_unknown');
  assert.equal((await new Discovery(f.c,f.deps).start(p)).state,'dispatch_unknown');
  assert.equal(f.calls.filter(([,o])=>o.method==='POST').length,1);
});
test('preflight managed scope and name are validated before POST',async t=>{
  const f=await fixture(t,(u,o,fallback)=>u.host==='netbox.example.com'?{id:12,name:hosts[0].name,tags:[]}:fallback());
  await assert.rejects(()=>f.client.start({request_id:'request-0003',hosts}));
  assert.equal(f.calls.filter(([,o])=>o.method==='POST').length,0);
});
test('equal names across device and VM cannot silently target another identity',async t=>{
  const f=await fixture(t,(u,o,fallback)=>u.host==='netbox.example.com' && u.pathname.includes('virtualization')?{count:1,results:[{id:99}]}:fallback());
  await assert.rejects(()=>f.client.start({request_id:'duplicate-name',hosts}));
  assert.equal(f.calls.filter(([,o])=>o.method==='POST').length,0);
});
test('run revision races and changed deployment identities fail closed',async t=>{
  const f=await fixture(t,(u,o,fallback)=>u.pathname.endsWith('/runs/178')?{id:178,head_sha:'b'.repeat(40),status:'completed'}:fallback());
  await f.client.start({request_id:'request-0004',hosts});
  await assert.rejects(()=>f.client.status({request_id:'request-0004'}));
  await assert.rejects(()=>new Discovery({...f.c,repository:'another'},f.deps).status({request_id:'request-0004'}));
});
test('explicit attempts select different compact artifacts without exposing facts',async t=>{
  const f=await fixture(t);await f.client.start({request_id:'request-0005',hosts});
  const one=await f.client.result({request_id:'request-0005',host:'device-12'});
  const two=await f.client.result({request_id:'request-0005',attempt:2});
  assert.equal(one.artifact_id,5);assert.equal(two.artifact_id,6);assert.equal(one.host.reconciliation_status,'succeeded');assert.equal(one.facts,undefined);
  await assert.rejects(()=>f.client.result({request_id:'request-0005',attempt:3}));
  assert.equal(f.calls.filter(([,o])=>o.method==='POST').length,1);
});
test('native ZIP round trip rejects unsafe paths, duplicate files, CRC mismatch and excess expansion',()=>{
  assert.equal(validateArtifact(readZip(archive()),record,1).manifest.counts.reconciled,1);
  const disks=manifest();disks.hosts[0].changes=[{object:'virtual_disk',id:1,fields:['size']}];disks.counts.changed=1;disks.counts.unchanged=0;
  assert.equal(validateArtifact(readZip(archive(disks)),record,1).manifest.hosts[0].changes[0].object,'virtual_disk');
  for(const names of [['../run.json','summary.md'],['run.json','run.json','summary.md'],['/run.json','summary.md']])assert.throws(()=>readZip(zip(names.map(n=>[n,'{}']))));
  const b=archive();b[b.length-35]^=1;assert.throws(()=>readZip(b));
  assert.throws(()=>readZip(zip([['run.json','x'.repeat(9*1024*1024)],['summary.md','x']])));
});
test('artifact attribution checks IDs, attempt, source, counts and rejects raw files',()=>{
  for(const m of [manifest({attempt:'2'}),manifest({revision:'b'.repeat(40)}),manifest({pattern:'all'}),manifest({counts:{selected:2}}),manifest({hosts:[{...manifest().hosts[0],object_id:13}]})])assert.throws(()=>validateArtifact(readZip(archive(m)),record,1));
  assert.throws(()=>readZip(zip([['facts/device-12.json','{}']])));
  assert.throws(()=>validateArtifact(readZip(archive(manifest({hosts:[{...manifest().hosts[0],facts:{secret:'not-a-summary'}}]}))),record,1));
});
test('partial reconciliation failures remain explicit and missing selections are visible',()=>{
  const r={...record,hosts:[...hosts,{name:'host2',object_type:'vm',object_id:13}]};
  const m=manifest({outcome:'failed',hosts:[...manifest().hosts,{name:'host2',object_type:'vm',object_id:13,status:'succeeded',reconciliation_status:'failed',changes:[],warnings:[],errors:['netbox_api']}],counts:{selected:2,collected:2,reconciled:1,changed:0,unchanged:1,warning:0,failed:1,unreachable:0}});
  const parsed=validateArtifact(readZip(archive(m)),r,1);assert.equal(parsed.manifest.counts.failed,1);assert.equal(parsed.selectionComplete,true);
  const missing=validateArtifact(readZip(archive(manifest({outcome:'failed'}))),r,1);assert.equal(missing.selectionComplete,false);assert.equal(missing.missing[0].object_id,13);
});

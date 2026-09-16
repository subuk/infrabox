import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {serveProbe,requestProbe,reusableRuntime} from '../roles/integration_checks/files/mcp-probe-runtime.mjs';

test('configuration or credential replacement closes the old native transport before reuse',async()=>{
  const events=[];let id=0;
  const store=reusableRuntime(async()=>{const n=++id;events.push('open '+n);return {dispose:async()=>events.push('close '+n)};});
  const first=await store.get('config-a:token-a',{});
  assert.equal(await store.get('config-a:token-a',{}),first);
  await store.get('config-a:token-b',{});
  await store.get('config-b:token-b',{});
  await store.close();await store.close();
  assert.deepEqual(events,['open 1','close 1','open 2','close 2','open 3','close 3']);
});
test('an invalidated or failed transport cannot be returned on the next observation',async()=>{
  let fail=false,created=0,closed=0;
  const store=reusableRuntime(async()=>{if(fail)throw Error('failed');created++;return {dispose:async()=>{closed++;}};});
  const first=await store.get('a',{});await store.close();
  assert.notEqual(await store.get('a',{}),first);
  fail=true;await assert.rejects(store.get('b',{}),{message:'failed'});
  fail=false;await store.get('b',{});await store.close();
  assert.equal(created,3);assert.equal(closed,3);
});

async function fixture(t,probe,options){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'mcp-probe-'));
  const socket=path.join(dir,'probe.sock');
  const server=await serveProbe(socket,probe,options);
  t.after(async()=>{await new Promise(resolve=>server.close(resolve));await fs.rm(dir,{recursive:true,force:true});});
  return socket;
}
test('every observation executes again and sees access removal',async t=>{
  let calls=0,allowed=true;
  const socket=await fixture(t,async()=>{calls++;if(!allowed)throw Error('permission');});
  assert.equal((await fs.stat(socket)).mode&0o777,0o600);
  await requestProbe(socket);await requestProbe(socket);
  allowed=false;
  await assert.rejects(requestProbe(socket),{message:'permission'});
  allowed=true;await requestProbe(socket);
  assert.equal(calls,4);
});
test('private transport accepts only the exact fixed request and sanitizes failures',async t=>{
  let calls=0;
  const socket=await fixture(t,async()=>{calls++;throw Error('private credential contents');});
  for(const payload of ['other\n','probe\nextra','{"tool":"netbox_write"}\n']){
    await new Promise((resolve,reject)=>{
      const client=net.createConnection(socket,()=>client.write(payload));
      client.on('data',()=>reject(Error('Unexpected response to invalid request')));
      client.on('error',()=>{});client.on('close',resolve);
    });
  }
  assert.equal(calls,0);
  await assert.rejects(requestProbe(socket),{message:'internal'});
  assert.equal(calls,1);
});
test('concurrent requests cannot queue unbounded work',async t=>{
  let release,entered;
  const started=new Promise(resolve=>{entered=resolve;});
  const socket=await fixture(t,async()=>{entered();await new Promise(resolve=>{release=resolve;});});
  const first=requestProbe(socket);await started;
  await assert.rejects(requestProbe(socket),{message:'unavailable'});
  release();await first;
});
test('a disconnected runtime and an unresponsive runtime cannot pass or hang',async t=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'mcp-disconnect-'));
  const socket=path.join(dir,'probe.sock');
  const server=net.createServer(client=>client.destroy());
  await new Promise(resolve=>server.listen(socket,resolve));
  await assert.rejects(requestProbe(socket,100),{message:'unavailable'});
  await new Promise(resolve=>server.close(resolve));await fs.rm(dir,{recursive:true,force:true});
  let release,expired=false;
  const stuck=await fixture(t,()=>new Promise(resolve=>{release=resolve;}),{deadlineMs:30,onTimeout:()=>{expired=true;release();}});
  await assert.rejects(requestProbe(stuck,10),{message:'timeout'});
  await new Promise(resolve=>setTimeout(resolve,60));assert.equal(expired,true);
});

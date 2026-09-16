// Runs inside the pinned image. Inputs select fixed operations, never arbitrary tools.
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {serveProbe,requestProbe,socketPath,reusableRuntime} from './mcp-probe-runtime.mjs';
const request=async path=>{
  const r=await fetch('http://127.0.0.1:18789'+path,{headers:{Authorization:'Bearer '+process.env.OPENCLAW_GATEWAY_TOKEN},signal:AbortSignal.timeout(10000)});
  if(!r.ok) throw Error(r.status===401?'auth':r.status===403?'permission':'unavailable');
  const b=await r.text();if(Buffer.byteLength(b)>1024*1024)throw Error('invalid_response');return b;
};
export function validateRead(result){
  if(result.isError || result.details?.isError)throw Error('invalid_response');
  const texts=result.content?.filter(c=>c.type==='text').map(c=>c.text)??[];
  if(texts.some(t=>/401|unauthori[sz]ed|invalid token/i.test(t)))throw Error('auth');
  if(texts.some(t=>/403|permission denied|forbidden/i.test(t)))throw Error('permission');
  const values=[result.details?.structuredContent,...texts.flatMap(t=>{try{return [JSON.parse(t)]}catch{return []}})];
  if(!values.some(v=>v && Array.isArray(v.items) && Number.isInteger(v.total) && Number.isInteger(v.count) && v.count===v.items.length && v.items.length<=1))throw Error('invalid_response');
}
export async function main(mode){
// Bound the client independently from the helper's fixed-operation watchdog.
const deadline=setTimeout(()=>{console.log(JSON.stringify({success:false,reason:'timeout'}));process.exit(1)},mode==='mcp'?60000:20000);deadline.unref();
try{
  if(mode==='ready')await request('/readyz');
  else if(mode==='diagnostics'){
    const b=await request('/api/diagnostics/prometheus');
    if(!/^openclaw_gateway_build_info\{/m.test(b))throw Error('invalid_response');
    // Only bounded native operational series are forwarded; no arbitrary identifiers.
    const allowed=/^openclaw_(gateway_event_loop_observed_seconds_total|prometheus_series_dropped_total|diagnostic_async_queue_dropped_total|tool_execution_total|model_call_total|memory_bytes)(\{|\s)/;
    console.log(JSON.stringify({success:true,metrics:b.split('\n').filter(l=>allowed.test(l)).slice(0,300)}));process.exit(0);
  }else if(mode==='vault'){
    const id='openclaw/monitoring/probe/value';
    const r=spawnSync('node',['/app/dist/extensions/vault/vault-secret-ref-resolver.js'],{input:JSON.stringify({protocolVersion:1,ids:[id]}),encoding:'utf8',timeout:10000,maxBuffer:65536});
    if(r.status!==0)throw Error('auth');
    if(typeof JSON.parse(r.stdout).values?.[id]!=='string')throw Error('invalid_response');
  }else if(mode==='mcp'){
    await requestProbe();
  }else throw Error('invalid_response');
  console.log(JSON.stringify({success:true}));
}catch(e){console.log(JSON.stringify({success:false,reason:['auth','permission','invalid_response','tool_unavailable','unavailable','timeout'].includes(e.message)?e.message:'internal'}));process.exitCode=1;}
finally{clearTimeout(deadline);}
}
const nativeRuntime=reusableRuntime(async config=>{
    // This release's HTTP tools endpoint does not materialize MCP tools.
    // Use the same OpenClaw runtime/materialization as agent runs, never a copied API token.
    const {createBundleMcpToolRuntime}=await import('/app/dist/agent-bundle-mcp-tools-CXY_T3kf.mjs');
    return createBundleMcpToolRuntime({cfg:config,workspaceDir:config.agents.defaults.workspace});
});
export const closeNativeMcp=()=>nativeRuntime.close();
export async function nativeMcpRead(){
    try{
      const raw=fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH,'utf8');
      const config=JSON.parse(raw);
      if(!config.mcp?.servers?.netbox?.toolFilter?.include?.includes('netbox_read'))throw Error('tool_unavailable');
      const name='netbox__netbox_read';
      if((config.tools?.deny??[]).some(x=>[name,'netbox_read','group:mcp','*'].includes(x)))throw Error('permission');
      // Credential changes invalidate the transport before another request. Only
      // a digest is retained here; the native wrapper owns credential delivery.
      const key=createHash('sha256').update(raw).update('\0').update(fs.readFileSync('/run/openclaw-secrets/netbox-token')).digest('hex');
      const runtime=await nativeRuntime.get(key,config);
        const {n:resolveEffectiveToolPolicy}=await import('/app/dist/agent-tools.policy-BYQnd2Ij.mjs');
      const {t:applyToolPolicyPipeline,n:buildDefaultToolPolicyPipelineSteps}=await import('/app/dist/tool-policy-pipeline-M7HPpWrp.mjs');
      const {r:getPluginToolMeta}=await import('/app/dist/tool-metadata-DYFFWrkm.mjs');
      const policies=resolveEffectiveToolPolicy({config,agentId:'main'});
      const allowed=applyToolPolicyPipeline({tools:runtime.tools,toolMeta:getPluginToolMeta,
        steps:buildDefaultToolPolicyPipelineSteps(policies),warn:()=>{}});
      const tool=allowed.find(t=>t.name===name);
      if(!tool || runtime.diagnostics?.length)throw Error('tool_unavailable');
        validateRead(await tool.execute('infrabox-monitoring-read',{object_type:'dcim.site',operation:'list',limit:1,response_format:'json'},AbortSignal.timeout(10000)));
    }catch(e){await closeNativeMcp();throw e;}
}
export async function serveMcp(){
  process.once('SIGTERM',()=>{void closeNativeMcp().finally(()=>process.exit(0));});
  const dir=socketPath.slice(0,socketPath.lastIndexOf('/'));
  fs.mkdirSync(dir,{recursive:true,mode:0o700});
  const owner=fs.statSync(dir);
  if(owner.uid!==process.getuid() || (owner.mode&0o077))throw Error('permission');
  fs.writeFileSync(dir+'/pid',String(process.pid),{mode:0o600});
  // Retain code and the native transport; policy and API reads remain fresh.
  await Promise.all([
    import('/app/dist/agent-bundle-mcp-tools-CXY_T3kf.mjs'),
    import('/app/dist/agent-tools.policy-BYQnd2Ij.mjs'),
    import('/app/dist/tool-policy-pipeline-M7HPpWrp.mjs'),
    import('/app/dist/tool-metadata-DYFFWrkm.mjs'),
  ]);
  if(fs.existsSync(socketPath)){
    const old=fs.lstatSync(socketPath);
    if(!old.isSocket() || old.uid!==process.getuid())throw Error('permission');
    fs.unlinkSync(socketPath);
  }
  await serveProbe(socketPath,nativeMcpRead);
}
async function stopMcp(){
  const file=socketPath.slice(0,socketPath.lastIndexOf('/'))+'/pid';
  if(!fs.existsSync(file))return;
  const pid=Number(fs.readFileSync(file,'utf8'));
  if(!Number.isSafeInteger(pid) || pid<=1)throw Error('invalid_response');
  const matches=()=>{
    try{
      const args=fs.readFileSync('/proc/'+pid+'/cmdline','utf8').split('\0');
      return args.includes('/opt/infrabox/monitoring/openclaw-probe.mjs') && args.includes('mcp-server') && fs.statSync('/proc/'+pid).uid===process.getuid();
    }catch(e){if(e.code==='ENOENT')return false;throw e;}
  };
  if(!matches())return;
  process.kill(pid,'SIGTERM');
  for(let i=0;i<50 && matches();i++)await new Promise(resolve=>setTimeout(resolve,100));
  if(matches())process.kill(pid,'SIGKILL');
}
if(import.meta.filename===process.argv[1]){
  if(process.argv[2]==='mcp-server')await serveMcp();
  else if(process.argv[2]==='mcp-stop')await stopMcp();
  else await main(process.argv[2]);
}

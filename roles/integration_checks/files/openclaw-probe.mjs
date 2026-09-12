// Runs inside the pinned image. Inputs select fixed operations, never arbitrary tools.
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
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
const config=JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH,'utf8'));
const deadline=setTimeout(()=>{console.log(JSON.stringify({success:false,reason:'timeout'}));process.exit(1)},20000);deadline.unref();
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
    if(!config.mcp?.servers?.netbox?.toolFilter?.include?.includes('netbox_read'))throw Error('tool_unavailable');
    // This release's HTTP tools endpoint does not materialize MCP tools.
    // Use the same OpenClaw runtime/materialization as agent runs, never a copied API token.
    const {createBundleMcpToolRuntime}=await import('/app/dist/agent-bundle-mcp-tools-CXY_T3kf.mjs');
    const runtime=await createBundleMcpToolRuntime({cfg:config,workspaceDir:config.agents.defaults.workspace});
    try{
      const name='netbox__netbox_read';
      if((config.tools?.deny??[]).some(x=>[name,'netbox_read','group:mcp','*'].includes(x)))throw Error('permission');
      const {n:resolveEffectiveToolPolicy}=await import('/app/dist/agent-tools.policy-BYQnd2Ij.mjs');
      const {t:applyToolPolicyPipeline,n:buildDefaultToolPolicyPipelineSteps}=await import('/app/dist/tool-policy-pipeline-M7HPpWrp.mjs');
      const {r:getPluginToolMeta}=await import('/app/dist/tool-metadata-DYFFWrkm.mjs');
      const policies=resolveEffectiveToolPolicy({config,agentId:'main'});
      const allowed=applyToolPolicyPipeline({tools:runtime.tools,toolMeta:getPluginToolMeta,
        steps:buildDefaultToolPolicyPipelineSteps(policies),warn:()=>{}});
      const tool=allowed.find(t=>t.name===name);
      if(!tool || runtime.diagnostics?.length)throw Error('tool_unavailable');
      validateRead(await tool.execute('infrabox-monitoring-read',{object_type:'dcim.site',operation:'list',limit:1,response_format:'json'},AbortSignal.timeout(10000)));
    }finally{await runtime.dispose();}
  }else throw Error('invalid_response');
  console.log(JSON.stringify({success:true}));
}catch(e){console.log(JSON.stringify({success:false,reason:['auth','permission','invalid_response','tool_unavailable','unavailable'].includes(e.message)?e.message:'internal'}));process.exitCode=1;}
finally{clearTimeout(deadline);}
}
if(import.meta.filename===process.argv[1])await main(process.argv[2]);

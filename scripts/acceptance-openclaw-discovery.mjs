// Execute inside Gateway's container. Input contains only approved NetBox identities.
import {readFileSync} from 'node:fs';
const input=JSON.parse(process.argv[1]);
async function call(name,params) {
  const port=JSON.parse(readFileSync(process.env.OPENCLAW_CONFIG_PATH,'utf8')).gateway.port;
  if(!Number.isInteger(port) || port<1 || port>65535)throw Error('Invalid Gateway port');
  const response=await fetch(`http://127.0.0.1:${port}/tools/invoke`,{
    method:'POST',headers:{Authorization:'Bearer '+process.env.OPENCLAW_GATEWAY_TOKEN,'Content-Type':'application/json'},
    body:JSON.stringify({tool:name,args:params}),signal:AbortSignal.timeout(60000)});
  const data=await response.json();
  if(!response.ok || !data.ok || !data.result?.details)throw Error('Gateway tool invocation failed');
  return data.result.details;
}
const report={outcome:'failed',checks:[]};
try {
  if(!Array.isArray(input.hosts) || input.hosts.length<1 || input.hosts.length>2)throw Error('Acceptance requires one or two explicitly authorized hosts');
  const params={request_id:input.request_id,hosts:input.hosts};
  const started=input.resume_only
    ? await call('infrabox_discovery_status',{request_id:input.request_id})
    : await call('infrabox_discovery_start',params);
  Object.assign(report,{request_id:started.request_id,run_id:started.run_id,run_url:started.run_url,revision:started.revision});
  if(!started.run_id)throw Error('Dispatch did not return a run; inspect saved request before retrying');
  if(input.resume_only) {
    report.checks.push('persisted_request_read_without_dispatch');
  } else {
    const repeat=await call('infrabox_discovery_start',params);
    if(repeat.run_id!==started.run_id)throw Error('Repeated request created a different run');
    report.checks.push('fixed_workflow_dispatch','request_id_deduplication');
  }
  let state;const deadline=Date.now()+22*60*1000;
  do {
    state=await call('infrabox_discovery_status',{request_id:input.request_id,wait_seconds:30});
    if(state.state==='completed')break;
  } while(Date.now()<deadline);
  if(state.state!=='completed')throw Error('Workflow still pending; inspect retained run, do not redispatch');
  const summary=await call('infrabox_discovery_result',{request_id:input.request_id});
  if(summary.collection_outcome!=='success' || state.conclusion!=='success' || !summary.selection_complete || summary.counts.selected!==input.hosts.length || summary.counts.reconciled!==input.hosts.length || summary.reconciliation_outcome!=='success')throw Error('Selected-host discovery was not successful');
  const details=[];
  for(const host of input.hosts){
    const page=await call('infrabox_discovery_result',{request_id:input.request_id,host:`${host.object_type}-${host.object_id}`});
    if(page.host?.reconciliation_status!=='succeeded' || page.facts!==undefined)throw Error('Compact reconciliation did not succeed');
    details.push(page.host);
  }
  report.checks.push('workflow_completion','artifact_run_attempt_sha_identity','exact_selected_hosts','compact_reconciliation_result');
  Object.assign(report,{outcome:'passed',attempt:summary.attempt,artifact_id:summary.artifact_id,observed_at:summary.observed_at,counts:summary.counts,hosts:details,workflow_conclusion:state.conclusion});
} catch {report.reason='OpenClaw discovery acceptance failed; inspect the retained request and Gitea run. Discovery may have applied changes; inspect per-host reconciliation results.';}
console.log(JSON.stringify(report));process.exitCode=report.outcome==='passed'?0:1;

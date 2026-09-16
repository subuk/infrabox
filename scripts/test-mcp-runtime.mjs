// Disposable config only: production Gateway policy and credentials are unchanged.
import fs from 'node:fs';
import {nativeMcpRead,closeNativeMcp} from '/opt/infrabox/monitoring/openclaw-probe.mjs';
for(const name of ['log','info','warn','error','debug'])console[name]=()=>{};
const original=process.env.OPENCLAW_CONFIG_PATH;
const config=JSON.parse(fs.readFileSync(original,'utf8'));
const dir=fs.mkdtempSync('/tmp/infrabox-mcp-policy-');
const file=dir+'/config.json';
const save=value=>fs.writeFileSync(file,JSON.stringify(value),{mode:0o600});
const checks=[];
const deadline=setTimeout(()=>{fs.rmSync(dir,{recursive:true,force:true});process.exit(1);},180000);
try{
  process.env.OPENCLAW_CONFIG_PATH=file;save(config);
  await nativeMcpRead();checks.push('Native read succeeds');
  await nativeMcpRead();checks.push('Another real read succeeds using the retained native transport');
  const denied=structuredClone(config);
  denied.tools??={};denied.tools.deny=[...(denied.tools.deny??[]),'netbox__netbox_read'];save(denied);
  let rejected=false;
  try{await nativeMcpRead();}catch(e){if(e.message!=='permission')throw e;rejected=true;}
  if(!rejected)throw Error('Current policy did not reject the read');
  checks.push('Changed policy rejects the next read in the same process');
  save(config);await nativeMcpRead();checks.push('Restored policy permits a new read in the same process');
  process.stdout.write(JSON.stringify({status:'passed',checks})+'\n');
}finally{
  await closeNativeMcp();
  clearTimeout(deadline);process.env.OPENCLAW_CONFIG_PATH=original;
  fs.rmSync(dir,{recursive:true,force:true});
}

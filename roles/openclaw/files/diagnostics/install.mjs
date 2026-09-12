// Use the pinned release's official installer so its provenance guard remains intact.
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {i as readRecords} from '/app/dist/installed-plugin-index-record-reader-DW0j0ZVi.mjs';
const spec='@openclaw/diagnostics-prometheus@2026.9.4';
const lock=JSON.parse(fs.readFileSync('/opt/infrabox/diagnostics/package-lock.json','utf8'));
const expected=lock.packages['node_modules/@openclaw/diagnostics-prometheus'];
const record=readRecords()['diagnostics-prometheus'];
function valid(r){return r?.source==='npm' && r.spec===spec && r.version===expected.version && r.integrity===expected.integrity && fs.existsSync(r.installPath+'/openclaw.plugin.json');}
if(valid(record)){console.log(JSON.stringify({changed:false}));process.exit(0);}
if(process.argv.includes('--verify')){console.error('Diagnostics install record mismatch');process.exit(1);}
const configDir=fs.mkdtempSync('/tmp/infrabox-plugin-');
const install=spawnSync('node',['/app/openclaw.mjs','plugins','install',spec,'--pin','--force','--accept-capabilities'],{
 env:{...process.env,OPENCLAW_CONFIG_PATH:configDir+'/openclaw.json',npm_config_ignore_scripts:'true'},encoding:'utf8',timeout:180000,maxBuffer:1024*1024});
if(install.status!==0){console.error('Official diagnostics installation failed: '+(install.stdout+'\n'+install.stderr).split('\n').filter(l=>/error|failed|blocked|denied|EACCES|policy|refus/i.test(l)).join('\n').slice(-3000));process.exit(1);}
// Fresh process observes the committed SQLite install record rather than a reader cache.
const verify=spawnSync('node',[import.meta.filename,'--verify'],{env:process.env,encoding:'utf8',timeout:15000,maxBuffer:65536});
if(verify.status!==0){console.error('Diagnostics provenance or integrity verification failed');process.exit(1);}
console.log(JSON.stringify({changed:true}));

import {DiscoveryError} from './errors.mjs';
// Read bounded Gitea ZIP artifacts in memory. Never extract paths to disk.
import {inflateRawSync} from 'node:zlib';
export const MAX_ARCHIVE = 32 * 1024 * 1024;
const fail = () => { throw new DiscoveryError('Invalid or oversized discovery artifact'); };
export function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit=0; bit<8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
export function readZip(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length > MAX_ARCHIVE || buffer.length < 22) fail();
  let end=-1;
  for (let i=buffer.length-22; i>=Math.max(0,buffer.length-65557); i--) {
    if (buffer.readUInt32LE(i)===0x06054b50 && i+22+buffer.readUInt16LE(i+20)===buffer.length) {end=i;break;}
  }
  if (end<0 || buffer.readUInt16LE(end+4) || buffer.readUInt16LE(end+6)) fail();
  const count=buffer.readUInt16LE(end+10), size=buffer.readUInt32LE(end+12), start=buffer.readUInt32LE(end+16);
  if (count!==1 || count!==buffer.readUInt16LE(end+8) || start+size!==end) fail();
  let cursor=start, total=0;
  const files=new Map(), ranges=[];
  for (let i=0;i<count;i++) {
    if (cursor+46>end || buffer.readUInt32LE(cursor)!==0x02014b50) fail();
    const flags=buffer.readUInt16LE(cursor+8), method=buffer.readUInt16LE(cursor+10);
    const crc=buffer.readUInt32LE(cursor+16), compressed=buffer.readUInt32LE(cursor+20), length=buffer.readUInt32LE(cursor+24);
    const nameLength=buffer.readUInt16LE(cursor+28), extra=buffer.readUInt16LE(cursor+30), comment=buffer.readUInt16LE(cursor+32);
    const mode=buffer.readUInt32LE(cursor+38)>>>16, local=buffer.readUInt32LE(cursor+42);
    if (cursor+46+nameLength+extra+comment>end || flags & ~0x808 || ![0,8].includes(method) || (mode & 0xf000)===0xa000) fail();
    const name=buffer.subarray(cursor+46,cursor+46+nameLength).toString('utf8');
    if (!/^reconciliation-summary\.json$/.test(name) || files.has(name)) fail();
    total+=length;
    if (length>8*1024*1024 || total>MAX_ARCHIVE || local+30>start || buffer.readUInt32LE(local)!==0x04034b50) fail();
    const dataStart=local+30+buffer.readUInt16LE(local+26)+buffer.readUInt16LE(local+28), dataEnd=dataStart+compressed;
    if (dataEnd>start || dataStart>dataEnd || buffer.readUInt16LE(local+6)!==flags || buffer.readUInt16LE(local+8)!==method ||
        buffer.subarray(local+30,local+30+buffer.readUInt16LE(local+26)).toString('utf8')!==name) fail();
    if (ranges.some(([a,b])=>local<b && dataEnd>a)) fail();
    ranges.push([local,dataEnd]);
    const input=buffer.subarray(dataStart,dataEnd);
    const data=method===0 ? input : inflateRawSync(input,{maxOutputLength:Math.max(1,length)});
    if (data.length!==length || crc32(data)!==crc) fail();
    files.set(name,data);
    cursor+=46+nameLength+extra+comment;
  }
  if (cursor!==end || !files.has('reconciliation-summary.json')) fail();
  return files;
}
const statuses=['succeeded','failed','unreachable','not_completed'];
export function validateArtifact(files, record, attempt) {
  const m=JSON.parse(files.get('reconciliation-summary.json').toString('utf8'));
  if(m.schema_version!==2 || String(m.run_id)!==String(record.run_id) || String(m.attempt)!==String(attempt) ||
    m.revision!==record.revision || m.pattern!==record.pattern || !Array.isArray(m.hosts) || m.hosts.length>256 ||
    !['success','failed'].includes(m.outcome) || !Number.isFinite(Date.parse(m.started_at)) ||
    !Number.isFinite(Date.parse(m.finished_at)) || Date.parse(m.finished_at)<Date.parse(m.started_at) || !Number.isInteger(m.ansible_return_code))fail();
  const requested=new Map(record.hosts.map(h=>[`${h.object_type}-${h.object_id}`,h.name])), seen=new Set();
  const counts={selected:m.hosts.length,collected:0,reconciled:0,changed:0,unchanged:0,warning:0,failed:0,unreachable:0};
  for(const h of m.hosts){
    const key=`${h.object_type}-${h.object_id}`;
    if(!requested.has(key) || requested.get(key)!==h.name || seen.has(key) || !statuses.includes(h.status) ||
      !['succeeded','failed','skipped'].includes(h.reconciliation_status) ||
      !Array.isArray(h.changes) || !Array.isArray(h.warnings) || !Array.isArray(h.errors) ||
      (h.status!=='succeeded' && h.reconciliation_status!=='skipped') ||
      Object.keys(h).some(k=>!['name','object_type','object_id','status','reconciliation_status','changes','warnings','errors','provenance_changed'].includes(k)) ||
      h.changes.length>8192 || h.warnings.length>8192 || h.errors.length>32 ||
      h.warnings.some(v=>typeof v!=='string' || v.length>512) || h.errors.some(v=>typeof v!=='string' || v.length>128) ||
      h.changes.some(c=>!c || Object.keys(c).some(k=>!['object','id','fields','created'].includes(k)) ||
        !['device','vm','platform','manufacturer','interface','mac','ip','module_bay','module_type','module','virtual_disk'].includes(c.object) ||
        !Number.isSafeInteger(c.id) || c.id<1 || !Array.isArray(c.fields) || c.fields.length>32 ||
        c.fields.some(f=>typeof f!=='string' || !/^[a-z_]{1,64}$/.test(f))))fail();
    seen.add(key);
    counts.collected+=h.status==='succeeded'; counts.reconciled+=h.reconciliation_status==='succeeded';
    counts.changed+=h.changes.length>0; counts.unchanged+=h.reconciliation_status==='succeeded' && !h.changes.length;
    counts.warning+=h.warnings.length>0; counts.failed+=h.status!=='succeeded' || h.reconciliation_status==='failed';
    counts.unreachable+=h.status==='unreachable';
  }
  if(Object.keys(m.counts??{}).length!==8 || Object.entries(counts).some(([k,v])=>m.counts[k]!==v))fail();
  const selectionComplete=seen.size===requested.size;
  if(m.outcome==='success' && (!selectionComplete || !counts.selected || counts.failed || counts.reconciled!==counts.selected || m.ansible_return_code!==0))fail();
  return {manifest:m,selectionComplete,missing:record.hosts.filter(h=>!seen.has(`${h.object_type}-${h.object_id}`))};
}

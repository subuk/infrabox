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
  if (count<2 || count>258 || count!==buffer.readUInt16LE(end+8) || start+size!==end) fail();
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
    if (!/^(run\.json|summary\.md|facts\/(device|vm)-[1-9][0-9]*\.json)$/.test(name) || files.has(name)) fail();
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
  if (cursor!==end || !files.has('run.json') || !files.has('summary.md')) fail();
  return files;
}
const statuses=['succeeded','failed','unreachable','not_completed'];
export function validateArtifact(files, record, attempt) {
  const m=JSON.parse(files.get('run.json').toString('utf8'));
  if (String(m.run_id)!==String(record.run_id) || String(m.attempt)!==String(attempt) || m.revision!==record.revision ||
      m.pattern!==record.pattern || !Array.isArray(m.hosts) || m.hosts.length>256 ||
      !['success','partial_failure','collection_failed','no_targets','inventory_failed','dependency_failed','timeout','result_export_failed'].includes(m.outcome) ||
      !Number.isFinite(Date.parse(m.started_at)) || !Number.isFinite(Date.parse(m.finished_at)) || Date.parse(m.finished_at)<Date.parse(m.started_at) ||
      !Number.isInteger(m.ansible_return_code)) fail();
  const requested=new Map(record.hosts.map(h=>[`${h.object_type}-${h.object_id}`,h.name]));
  const seen=new Set(), facts=new Map(), expectedFiles=new Set(['run.json','summary.md']);
  const counts={selected:m.hosts.length,...Object.fromEntries(statuses.map(s=>[s,0]))};
  for (const host of m.hosts) {
    const key=`${host.object_type}-${host.object_id}`, file=`facts/${key}.json`;
    if (!['device','vm'].includes(host.object_type) || !Number.isSafeInteger(host.object_id) || host.object_id<1 ||
        !requested.has(key) || requested.get(key)!==host.name || seen.has(key) || host.file!==file || !statuses.includes(host.status)) fail();
    seen.add(key); counts[host.status]++;
    if (files.has(file)) {
      expectedFiles.add(file);
      const value=JSON.parse(files.get(file).toString('utf8'));
      if (!value || typeof value!=='object' || Array.isArray(value) || Object.keys(value).some(k=>/^(ansible_env|ansible_local|env|local|facter|ohai)$|^(facter_|ohai_)/.test(k))) fail();
      // Failed hosts may retain native facts, but never expose these as verified.
      if (host.status==='succeeded') facts.set(key,value);
    } else if (host.status==='succeeded') fail();
  }
  if (Object.keys(m.counts??{}).length!==5 || Object.entries(counts).some(([k,v])=>m.counts[k]!==v) ||
      [...files.keys()].some(f=>!expectedFiles.has(f))) fail();
  const selectionComplete=seen.size===requested.size;
  if (m.outcome==='success' && (!selectionComplete || !counts.selected || counts.succeeded!==counts.selected || m.ansible_return_code!==0)) fail();
  return {manifest:m,facts,selectionComplete,missing:record.hosts.filter(h=>!seen.has(`${h.object_type}-${h.object_id}`))};
}
export function factPage(facts, pointer='', offset=0) {
  if (typeof pointer!=='string' || pointer.length>1024 || (pointer && !pointer.startsWith('/')) || /~(?![01])/.test(pointer) || !Number.isSafeInteger(offset) || offset<0) throw new DiscoveryError('Invalid facts pointer or offset');
  let value=facts;
  for (const raw of pointer ? pointer.slice(1).split('/') : []) {
    const key=raw.replace(/~1/g,'/').replace(/~0/g,'~');
    if (!value || typeof value!=='object' || !Object.hasOwn(value,key)) throw new DiscoveryError('Facts pointer not found');
    value=value[key];
  }
  const preview=v=>{
    if (typeof v==='string' && v.length>4096) return {preview:v.slice(0,4096),truncated:true};
    if (v && typeof v==='object' && Buffer.byteLength(JSON.stringify(v))>4096) return {expand:true,type:Array.isArray(v)?'array':'object',count:Object.keys(v).length};
    return {value:v};
  };
  if (!value || typeof value!=='object') return {pointer,...preview(value),next_offset:null};
  const keys=Object.keys(value), entries=keys.slice(offset,offset+10).map(key=>{
    const child=pointer+'/'+key.replace(/~/g,'~0').replace(/\//g,'~1');
    if(child.length>1024)return {key_preview:key.slice(0,256),key_truncated:true,value_omitted:true};
    return {key,pointer:child,...preview(value[key])};
  });
  return {pointer,entries,total:keys.length,next_offset:offset+entries.length<keys.length?offset+entries.length:null};
}

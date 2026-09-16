// Private, fixed-operation transport. No tool names, arguments or credentials cross it.
import net from 'node:net';
import fs from 'node:fs';
export const socketPath='/tmp/infrabox-monitoring-runtime/mcp.sock';
const reasons=new Set(['auth','permission','invalid_response','tool_unavailable','unavailable','timeout','internal']);

// The caller serializes observations. Cache a transport, never a result or policy.
export function reusableRuntime(create){
  let current,key;
  const close=async()=>{const old=current;current=undefined;key=undefined;await old?.dispose();};
  return {
    close,
    async get(nextKey,config){
      if(current && key===nextKey)return current;
      await close();
      const next=await create(config);
      current=next;key=nextKey;return next;
    },
  };
}

export async function serveProbe(path,probe,{deadlineMs=60000,onTimeout=()=>process.exit(1)}={}){
  let busy=false;
  const server=net.createServer(socket=>{
    let input='',started=false;
    socket.on('error',()=>{});
    socket.setTimeout(deadlineMs,()=>socket.destroy());
    socket.on('data',async chunk=>{
      if(started){socket.destroy();return;}
      input+=chunk.toString('utf8');
      if(input.length>6 || !'probe\n'.startsWith(input)){socket.destroy();return;}
      if(input!=='probe\n')return;
      started=true;
      if(busy){socket.end('{"success":false,"reason":"unavailable"}\n');return;}
      busy=true;
      const deadline=setTimeout(onTimeout,deadlineMs);
      deadline.unref();
      try{await probe();socket.end('{"success":true}\n');}
      catch(e){socket.end(JSON.stringify({success:false,reason:reasons.has(e.message)?e.message:'internal'})+'\n');}
      finally{clearTimeout(deadline);busy=false;}
    });
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(path,resolve);});
  fs.chmodSync(path,0o600);
  return server;
}

export function requestProbe(path=socketPath,timeoutMs=60000){
  return new Promise((resolve,reject)=>{
    let body='',settled=false;const socket=net.createConnection(path);
    const fail=reason=>{if(settled)return;settled=true;socket.destroy();reject(Error(reason));};
    socket.setTimeout(timeoutMs,()=>fail('timeout'));
    socket.on('error',()=>fail('unavailable'));
    socket.on('close',()=>{if(!settled)fail('unavailable');});
    socket.on('connect',()=>socket.write('probe\n'));
    socket.on('data',chunk=>{body+=chunk;if(Buffer.byteLength(body)>256)fail('invalid_response');});
    socket.on('end',()=>{
      try{
        const result=JSON.parse(body);
        if(result.success!==true)throw Error(reasons.has(result.reason)?result.reason:'internal');
        settled=true;resolve();
      }catch(e){fail(reasons.has(e.message)?e.message:'invalid_response');}
    });
  });
}

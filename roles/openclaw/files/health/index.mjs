import http from 'node:http';
export function readHealth(params={},signal){
  if(Object.keys(params).some(k=>k!=='component') || (params.component!==undefined && !/^[a-z][a-z0-9_-]{0,40}$/.test(params.component)))throw Error('Provide only an optional component name.');
  return new Promise((resolve,reject)=>{
    const req=http.get({socketPath:'/run/infrabox-health/api.sock',path:'/health'+(params.component?'?component='+encodeURIComponent(params.component):''),signal},res=>{
      let body='';res.on('data',b=>{body+=b;if(Buffer.byteLength(body)>8192)req.destroy(Error('Health response limit exceeded'));});
      res.on('end',()=>{try{const d=JSON.parse(body);if(res.statusCode!==200 || d.schema_version!==1 || !['healthy','warning','critical','unknown'].includes(d.status) || typeof d.coverage_complete!=='boolean' || !Array.isArray(d.issues) || d.issues.length>20)throw Error('Invalid health response');resolve(d)}catch(e){reject(e)}});
      res.on('error',reject);
    });
    req.setTimeout(20000,()=>req.destroy(Error('Health unavailable; result is inconclusive.')));req.on('error',reject);
  });
}
export default {id:'infrabox-health',name:'InfraBox Health',register(api){
  api.registerTool({name:'infrabox_health',label:'InfraBox health',description:'Read continuous InfraBox health. Healthy with complete coverage needs no broad diagnostic sweep. Warning, critical or unknown requires targeted investigation. This read does not run probes or verify a deployment; mandatory feature tests remain separate.',parameters:{type:'object',additionalProperties:false,properties:{component:{type:'string'}}},async execute(_id,params,signal){const result=await readHealth(params,signal);return {content:[{type:'text',text:JSON.stringify(result)}],details:result}}},{optional:true});
}};

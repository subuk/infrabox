import test from 'node:test';
import assert from 'node:assert/strict';
import {validateRead} from '../roles/integration_checks/files/openclaw-probe.mjs';
import {readHealth} from '../roles/openclaw/files/health/index.mjs';
const read=body=>({content:[{type:'text',text:'NetBox read result'},{type:'text',text:JSON.stringify(body)}]});
test('MCP empty and one-item results are valid',()=>{
 for(const items of [[],[{id:1}]])assert.doesNotThrow(()=>validateRead(read({items,total:items.length,count:items.length})));
});
test('MCP failures and malformed responses cannot pass',()=>{
 for(const r of [{isError:true},{details:{isError:true}},read({items:[],total:1,count:1}),read({items:[{},{}],total:2,count:2}),{content:[{type:'text',text:'403 Forbidden'}]},{}])assert.throws(()=>validateRead(r));
});
test('health reader rejects command, URL and query inputs before transport',()=>{
 for(const p of [{command:'true'},{url:'https://example.com'},{query:'up'},{component:'../foo'}])assert.throws(()=>readHealth(p));
});

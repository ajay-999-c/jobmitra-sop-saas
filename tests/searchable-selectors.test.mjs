import test from 'node:test';
import assert from 'node:assert/strict';
import {matchingOptions} from '../src/jobmitra/static/ats_v2/searchable-select.mjs';
import {selectorSearch} from '../src/jobmitra/static/ats_v2/workspace-selectors.mjs';
import {searchRequest} from '../src/jobmitra/static/ats_v2/search-request.mjs';

test('complete company options match trimmed partial case-insensitive names anywhere',()=>{
 const rows=Array.from({length:85},(_,i)=>({value:'company-'+i,label:i===84?'Kedia Traders':'Company '+i}));
 rows.push({value:'suraj-uuid',label:'Suraj Trading'},{value:'nimar-uuid',label:'Nimar Motors'},{value:'axis-uuid',label:'Axis Bank'});
 assert.deepEqual(matchingOptions(rows,'  tRaD  ').map(r=>r.value),['company-84','suraj-uuid']);
 assert.equal(matchingOptions(rows,'nim')[0].value,'nimar-uuid');assert.equal(matchingOptions(rows,'bank')[0].value,'axis-uuid');assert.equal(matchingOptions(rows,'axis')[0].value,'axis-uuid');assert.equal(matchingOptions(rows,'nothing').length,0);
});
test('JD reference, company and title search retain canonical option IDs',()=>{
 const native={jobs:[{id:'426',title:'Retail Accountant',company:'Suraj Trading',code:'JD-00746'}]};
 const job={value:'426',label:'Retail Accountant',search:selectorSearch('job','426',native)};
 for(const query of ['acc','suraj','retail','00746'])assert.equal(matchingOptions([job],query)[0].value,'426');
 assert.equal(matchingOptions([{...job,disabled:true}],'suraj').length,0);
});
test('typing invalidates prior responses immediately, even before debounce fires',async()=>{
 const callbacks=new Map();let serial=0;
 const request=searchRequest({schedule:cb=>{callbacks.set(++serial,cb);return serial;},cancel:id=>callbacks.delete(id)});
 const first=request.begin();let queries=0;
 request.later(()=>{queries++;request.begin();});assert.equal(request.current(first),false);
 request.later(()=>{queries++;request.begin();});assert.equal(callbacks.size,1);
 for(const cb of callbacks.values()){callbacks.clear();cb();}assert.equal(queries,1);
 const newer=request.begin();let resolve;const older=new Promise(r=>resolve=r).then(()=>request.current(newer));
 request.invalidate();resolve();assert.equal(await older,false);
});
test('explicit search cancels its pending debounce and invalidates old failures',()=>{
 const callbacks=new Map();let serial=0;
 const request=searchRequest({schedule:cb=>{callbacks.set(++serial,cb);return serial;},cancel:id=>callbacks.delete(id)});
 request.later(()=>assert.fail('debounced request should be cancelled'));
 const current=request.begin();assert.equal(callbacks.size,0);assert.equal(request.current(current),true);
 request.invalidate();assert.equal(request.current(current),false);
});

import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source=fs.readFileSync('src/jobmitra/static/ats_v2/email-studio.mjs','utf8');
const fn=source.slice(source.indexOf('export async function copyEmailContent'),source.indexOf('function notice(')).replace('export ','');
function fixture(mode){
 const handlers=new Map(),clipboard={'text/plain':'Previous subject'},selection={rangeCount:0,removeAllRanges(){},addRange(){}};
 const win={getSelection:()=>selection,navigator:{}};
 const doc={defaultView:win,body:{append(){}},createElement:()=>({style:{},remove(){}}),createRange:()=>({selectNodeContents(){}}),addEventListener:(k,v)=>handlers.set(k,v),removeEventListener:k=>handlers.delete(k),execCommand:()=>{if(mode==='blocked')return false;if(mode!=='no-event')handlers.get('copy')({clipboardData:{setData:(k,v)=>clipboard[k]=v},preventDefault(){}});return true;}};
 if(mode==='modern'){doc.execCommand=()=>false;win.ClipboardItem=class{constructor(data){this.data=data;}};win.navigator.clipboard={write:async([item])=>{for(const [k,v] of Object.entries(item.data))clipboard[k]=await v.text();}};}
 const ctx=vm.createContext({Blob});vm.runInContext(fn,ctx);
 return{copy:ctx.copyEmailContent,doc,clipboard,handlers};
}
for(const mode of ['http','modern'])test('copies actual formatted body instead of a stale subject: '+mode,async()=>{
 const f=fixture(mode);assert.equal(await f.copy(f.doc,'<table>Approved body</table>','Approved body'),true);assert.equal(f.clipboard['text/plain'],'Approved body');assert.equal(f.clipboard['text/html'],'<table>Approved body</table>');assert.equal(f.handlers.size,0);
});
for(const mode of ['blocked','no-event'])test('never claims success without clipboard delivery: '+mode,async()=>{
 const f=fixture(mode);assert.equal(await f.copy(f.doc,'<table>Approved body</table>','Approved body'),false);assert.equal(f.clipboard['text/plain'],'Previous subject');assert.equal(f.handlers.size,0);
});
test('copies subject alone without adding email HTML',async()=>{const f=fixture('http');assert.equal(await f.copy(f.doc,null,'Approved subject'),true);assert.equal(f.clipboard['text/plain'],'Approved subject');assert.equal(f.clipboard['text/html'],undefined);});
test('contextual drafts distinguish historical stages sharing the same template',async()=>{
 const keys=[],node={querySelector:()=>({textContent:'Email Studio'}),addEventListener(){},shadowRoot:{addEventListener(){}}};
 const window={JobmitraUnified:{},addEventListener(){}},document={getElementById:()=>node,addEventListener(){}};
 const ctx=vm.createContext({window,document,loadCandidateEmail:async(...args)=>{keys.push(args[3]);return false;}});
 vm.runInContext(source.slice(source.indexOf('export function installContextualEmail')).replace('export ',''),ctx);
 ctx.installContextualEmail({run:fn=>fn()},'',async(_,value)=>({...value,status:'jobmitra_screening',candidateId:'1'}));
 for(const viewStage of ['CONTACT','SCREENING'])await window.JobmitraUnified.openEmailStudio({jobId:'1',viewStage,candidates:[{id:'1'}]});
 assert.equal(keys.length,2);assert.notEqual(keys[0],keys[1]);
});

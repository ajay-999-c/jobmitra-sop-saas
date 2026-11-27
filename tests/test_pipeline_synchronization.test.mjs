import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parse} from '@babel/parser';
import traverse from '@babel/traverse';
import {allocation,salaryLabel,experienceLabel} from '../src/jobmitra/static/ats_v2/jd-clean.mjs';

globalThis.window={addEventListener(){},dispatchEvent(){}};
globalThis.document={querySelector:()=>null};
const {native}=await import('../src/jobmitra/static/ats_v2/approved-api.mjs');
const snapshot=id=>({today:'2030-01-01',companies:[],candidates:[{id:7,full_name:'Synthetic Person',skills:[],preferred_cities:[]}],resumes:[],events:id===2?[{id:1,candidate_id:7,job_id:id,jd_candidate_id:31,event_type:'ADDED',to_stage:'POOL',created_at:'2030-01-01T10:00:00Z'}]:[],activities:[],placements:[],jobs:[{id,title:'Canonical JD',skills:[],workflow:{rounds:[]},pipeline:{items:id===2?[{id:31,candidate_id:7,stage_code:'POOL',next_stage:'CONTACT',added_at:'2030-01-01T10:00:00Z'}]:[]}}]});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
test('a late pre-mutation snapshot cannot erase a newer committed projection',async()=>{
 const old=deferred(),fresh=deferred();let calls=0;
 const store={...native,localDevelopment:true,api:()=>++calls===1?old.promise:fresh.promise};
 const first=store.refresh();store.readEpoch=1;const second=store.refresh();
 old.resolve(snapshot(1));await new Promise(r=>setImmediate(r));fresh.resolve(snapshot(2));await second;
 assert.equal((await first).jobs[0].id,2);assert.equal(store.snapshot.jobs[0].id,2);assert.equal(store.jobs[0].id,'2');
 assert.equal(store.jobs[0].candidates[0].nextStage,'CONTACT');
 const history=store.histories('7');assert.equal(history.length,1);assert.equal(history[0].stage,'POOL');assert.equal(history[0].journey[0].type,'ADDED');assert.equal(store.pools()['2']['7'].linkId,31);
});
test('an obsolete successful read cannot conceal a newer refresh failure',async()=>{
 const old=deferred(),fresh=deferred();let calls=0;
 const store={...native,localDevelopment:true,snapshot:null,api:()=>++calls===1?old.promise:fresh.promise};
 const first=store.refresh();store.readEpoch=1;const second=store.refresh(),results=Promise.allSettled([first,second]);
 old.resolve(snapshot(1));await new Promise(r=>setImmediate(r));fresh.reject(Error('Canonical read unavailable'));
 assert.deepEqual((await results).map(r=>r.status),['rejected','rejected']);assert.equal(store.snapshot,null);
});

const source=fs.readFileSync('src/jobmitra/static/ats_v2/jd-clean.mjs','utf8'),functions=[];
traverse(parse(source,{sourceType:'module'}),{FunctionDeclaration(p){if(['memberActions','tablePeople'].includes(p.node.id.name))functions.push(source.slice(p.node.start,p.node.end));}});
function render(stage,current,next,disabled=false){
 const member={id:'7',stage:current,next},ctx={stage,disabled,job:{id:'8',status:'ACTIVE',candidates:[member]},stageOf:c=>c.stage,label:c=>c.stage,next:c=>c.next,canEmail:()=>true};
 const context=vm.createContext({context:()=>ctx,closed:new Set(['NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED']),busy:new Set(),esc:String,allocation,salaryLabel,experienceLabel,options:{stageName:key=>key==='CONTACT'?'Candidate Contact':key}});
 vm.runInContext(functions.join('\n')+';globalThis.rendered={actions:memberActions(context().job.candidates[0]),search:tablePeople([{id:7,full_name:"Synthetic Person"}])};',context);
 return context.rendered;
}
test('Find Candidates uses canonical linked-member actions, including Pool to Contact',()=>{
 const {actions,search}=render('POOL','POOL','CONTACT');
 assert.ok(search.includes(actions));assert.match(search,/data-move-next="7" title="Next: Candidate Contact"/);assert.ok(!search.includes('data-clean-add'));
 for(const marker of ['data-clean-profile','data-compose-candidate-email','data-feedback-candidate','data-mark-not-selected'])assert.ok(search.includes(marker));
});
test('current interview, selection, joining and historical/closed action rules stay distinct',()=>{
 assert.match(render('ROUND:one','ROUND:one','ROUND:two').actions,/data-schedule-interview/);
 assert.match(render('ROUND:one','ROUND:one','ROUND:two').actions,/data-move-next/);
 assert.match(render('SELECTED','SELECTED',null).actions,/data-confirm-joined/);
 assert.match(render('JOINED','JOINED',null).actions,/data-goto-view="placement"/);
 for(const [selected,current] of [['POOL','CONTACT'],['CONTACT','ROUND:one'],['POOL','NOT_SELECTED'],['SELECTED','NOT_JOINED'],['SELECTED','SELECTION_CANCELLED'],['JOINED','JOINED']]){
  const html=render(selected,current,'CONTACT').actions;
  assert.ok(!/data-move-next|data-mark-not-selected|data-confirm-joined|data-schedule-interview/.test(html));
  if(['NOT_JOINED','SELECTION_CANCELLED'].includes(current)&&selected==='SELECTED')assert.ok(!html.includes('data-compose-candidate-email'));else assert.match(html,/data-compose-candidate-email/);assert.match(html,/data-feedback-candidate/);
 }
 assert.ok(!/data-move-next|data-mark-not-selected|data-feedback-candidate/.test(render('POOL','POOL','CONTACT',true).actions));
});
test('explicit JD History shortcut opens history while generic Profile keeps overview',()=>{
 const generated=fs.readFileSync('src/jobmitra/static/ats_v2/approved-candidate.mjs','utf8');let handler;
 traverse(parse(generated,{sourceType:'module'}),{CallExpression(p){const fn=p.node.arguments[1];if(p.node.arguments[0]?.value==='click'&&fn&&generated.slice(fn.start,fn.end).includes('history.dataset.openHistory'))handler=generated.slice(fn.start,fn.end);}});
 assert.ok(handler);assert.match(generated,/data-profile-section="history">Open full JD history/);
 const calls=[],context=vm.createContext({showCandidateHistory:(...args)=>calls.push(args)});
 vm.runInContext('globalThis.handler='+handler,context);
 for(const profileSection of ['history',undefined])context.handler({target:{closest:selector=>selector==='[data-open-history]'?{dataset:{openHistory:'7',profileSection}}:null}});
 assert.deepEqual(calls,[['7','history'],['7','overview']]);
});

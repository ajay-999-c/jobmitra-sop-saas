import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {parse} from '@babel/parser';
import traverse from '@babel/traverse';
import {linkedRows,feedbackAtStage,stagePresentation} from '../src/jobmitra/static/ats_v2/jd-clean.mjs';
import {pipelineEmailContext} from '../src/jobmitra/static/ats_v2/pipeline-email.mjs';

const context={stage:'CONTACT',stageOf:c=>c.stage,decision:c=>c.decision,label:c=>c.stage};
test('completed and closed statuses remain distinct, with current candidates first',()=>{
 const rows=[{stage:'ROUND:one',decision:'ADVANCED'},{stage:'NOT_SELECTED',decision:'ADVANCED'},{stage:'CONTACT',decision:'PENDING'},{stage:'JOINED',decision:'COMPLETED'},{stage:'NOT_JOINED',decision:'ADVANCED'},{stage:'SELECTION_CANCELLED',decision:'ADVANCED'}];
 const ctx={...context,reached:()=>rows};
 assert.deepEqual(linkedRows(ctx,'reached').map(c=>c.stage),['CONTACT','ROUND:one','JOINED','NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED']);
 assert.equal(linkedRows(ctx,'here').length,1);
 assert.deepEqual(stagePresentation(ctx,rows[0]),{tone:'green',label:'Stage completed'});
 assert.deepEqual(stagePresentation(ctx,rows[2]),{tone:'amber',label:'Awaiting action'});
 for(const c of [rows[1],rows[4],rows[5]])assert.equal(stagePresentation(ctx,c).tone,'red');
});
test('feedback is scoped by historical stage and stable round ID',()=>{
 const person={journey:[{feedback:'Current screening',toKey:'SCREENING'},{feedback:'Contact note',feedback_stage:{stage_code:'CONTACT',round_id:null}},{feedback:'Round one',feedback_stage:{stage_code:'ROUND',round_id:'one'}},{feedback:'Round two',feedback_stage:{stage_code:'ROUND',round_id:'two'}},{feedback:'Old label evidence',toKey:'ROUND',toName:'Retained Round'},{feedback:'Schedule notes',type:'INTERVIEW_SCHEDULED',round_id:'one'}]};
 assert.deepEqual(feedbackAtStage(person,'CONTACT','Candidate Contact').map(e=>e.feedback),['Contact note']);
 assert.deepEqual(feedbackAtStage(person,'ROUND:one','First round').map(e=>e.feedback),['Round one']);
 assert.deepEqual(feedbackAtStage(person,'ROUND:retained','Retained Round').map(e=>e.feedback),['Old label evidence']);
});
for(const [viewStage,stage,status,audience] of [['CONTACT','CONTACT','jobmitra_screening','CANDIDATE'],['COMPANY_SUBMISSION','COMPANY_SUBMISSION','candidate_submission','COMPANY'],['ROUND:one','ROUND','custom_round','CANDIDATE']])test('historical Email keeps '+viewStage,async()=>{
 const paths=[];
 const native={api:async path=>{paths.push(path);return{stage,current_stage:'JOINED',round_id:stage==='ROUND'?'one':null,round_name:'Round one',historical_context:true,selection_outcome:'JOINED_CONFIRMED',candidate_id:5,job_id:9,candidate_name:'Canonical Person',job_title:'Canonical JD',contacts:[],recipient_email:null};}};
 const result=await pipelineEmailContext(native,{jobId:'9',viewStage,status:stage==='COMPANY_SUBMISSION'?'candidate_submission':'interview_scheduled',roundId:stage==='ROUND'?'one':null,candidates:[{id:'5'}]});
 assert.equal(result.status,status);assert.equal(result.candidateStage,stage);
 const query=new URL('http://fixture'+paths[0]).searchParams;
 assert.equal(query.get('selected_stage'),stage);assert.equal(query.get('audience'),audience);
 if(stage==='ROUND')assert.equal(query.get('selected_round_id'),'one');
});
test('older/current-only email responses fail rather than substitute current stage',async()=>{
 await assert.rejects(()=>pipelineEmailContext({api:async()=>({stage:'JOINED',contacts:[]})},{viewStage:'CONTACT',jobId:'9',candidates:[{id:'5'}]}),/could not be verified/);
});
test('generated cumulative helpers retain rejected stable round IDs after renaming',()=>{
 const source=fs.readFileSync('src/jobmitra/static/ats_v2/approved.mjs','utf8'),names=new Set(['refStage','progression','lastReachedIndex','stageVisited','stageEventsAt','stageDecision','stageRows','stageCount','stagePending']);
 const helpers=[];traverse(parse(source,{sourceType:'module'}),{VariableDeclarator(p){if(names.has(p.node.id.name)){helpers.push('const '+source.slice(p.node.start,p.node.end)+';');names.delete(p.node.id.name);}}});assert.equal(names.size,0);
 const draft={rounds:[{id:'one',name:'Renamed Round 1'},{id:'two',name:'Round 2'}],candidates:[{stageKey:'NOT_SELECTED',rejection:{stageKey:'ROUND',stageName:'Original Round 1'},journey:[{type:'REJECTED',fromKey:'ROUND',fromName:'Original Round 1',fromRoundId:'one',toKey:'NOT_SELECTED',at:'2030-01-01T00:00:00Z'}]},{stageId:'two',journey:[]}]};
 const ctx=vm.createContext({draft,stageOf:c=>c.stageId?'ROUND:'+c.stageId:c.stageKey,stageDefs:()=>['POOL','CONTACT','SCREENING','COMPANY_SUBMISSION','ROUND:one','ROUND:two','SELECTED','JOINED'].map(key=>({key}))});
 vm.runInContext(helpers.join('\n')+"globalThis.result={count:stageCount('ROUND:one'),pending:stagePending('ROUND:one'),decision:stageDecision(draft.candidates[0],'ROUND:one')};",ctx);
 assert.equal(ctx.result.count,2);assert.equal(ctx.result.pending,0);assert.equal(ctx.result.decision,'REJECTED');
});

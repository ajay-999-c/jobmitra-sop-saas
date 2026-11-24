import test from 'node:test';
import assert from 'node:assert/strict';
import {canComposePipelineEmail,pipelineEmailContext} from '../src/jobmitra/static/ats_v2/pipeline-email.mjs';
const member={candidate_id:4294967297,job_id:4294967298,candidate_name:'Canonical Candidate',job_title:'Canonical Role',stage:'SCREENING',selection_outcome:null,recipient_email:null,company_name:null,location:null,contacts:[],round_id:null,round_name:null};
const context={jobId:'4294967298',candidateName:'Stale name',status:'interview_scheduled',candidates:[{id:'4294967297',name:'Stale name'}]};
test('pipeline Email is available at every supported stage regardless of recipient or workflow',()=>{
 for(const stage of ['POOL','CONTACT','SCREENING','COMPANY_SUBMISSION','ROUND:opaque-round','SELECTED','JOINED','NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED'])assert.equal(canComposePipelineEmail(stage),true,stage);
 for(const stage of ['UNKNOWN'])assert.equal(canComposePipelineEmail(stage),false,stage);
});
for(const [stage,status] of [['POOL','jobmitra_screening'],['CONTACT','jobmitra_screening'],['SCREENING','jobmitra_screening'],['ROUND','custom_round'],['SELECTED','selected'],['JOINED','joined'],['NOT_SELECTED','not_selected']]){
 test('canonical '+stage+' selects existing '+status+' draft',async()=>{
  const facts={...member,stage,round_id:stage==='ROUND'?'current-round':null,round_name:stage==='ROUND'?'Client Discussion':null,selection_outcome:stage==='SELECTED'?'PENDING_JOINING':null};
  const result=await pipelineEmailContext({api:async()=>facts},context);
  assert.equal(result.status,status);assert.equal(result.candidateName,member.candidate_name);
  assert.equal(result.candidateId,String(member.candidate_id));assert.equal(result.jobId,String(member.job_id));
  assert.equal(result.candidates[0].name,member.candidate_name);assert.equal(result.candidateEmail,'');
  assert.equal(result.companyName,'');assert.equal(result.interviewDate,'');
  if(stage==='ROUND')assert.equal(result.roundName,'Client Discussion');
 });
}
test('company submission still opens with a saved company recipient when candidate email is missing',async()=>{
 const audiences=[];
 const native={api:async path=>{const audience=new URL('http://fixture'+path).searchParams.get('audience');audiences.push(audience);return {...member,stage:'COMPANY_SUBMISSION',company_name:audience==='COMPANY'?'Canonical Company':null,recipient_email:audience==='COMPANY'?'hr@example.test':null,contacts:audience==='COMPANY'?[{id:'contact-id',name:'HR',email:'hr@example.test'}]:[],selected_contact_id:'contact-id'};}};
 const result=await pipelineEmailContext(native,context);
 assert.deepEqual(audiences,['CANDIDATE','COMPANY']);assert.equal(result.status,'candidate_submission');
 assert.equal(result.companyName,'Canonical Company');assert.equal(result.companyContacts[0].email,'hr@example.test');assert.equal(result.companyContacts[0].is_primary,true);
 assert.equal(result.candidateEmail,'');
});
test('only the same current round retains its recorded schedule',async()=>{
 const native={api:async()=>({...member,stage:'ROUND',round_id:'current',round_name:'Current Round'})};
 const old={...context,roundId:'previous',interviewDate:'2030-01-01',interviewTime:'10:00'};
 const result=await pipelineEmailContext(native,old);assert.equal(result.interviewDate,'');assert.equal(result.interviewTime,'');
 const same=await pipelineEmailContext(native,{...old,roundId:'current'});assert.equal(same.interviewDate,'2030-01-01');assert.equal(same.interviewTime,'10:00');
});
test('missing membership and unsupported closed outcomes fail before opening a misleading draft',async()=>{
 await assert.rejects(()=>pipelineEmailContext({api:async()=>{throw Error('Membership not found');}},context),/Membership not found/);
 for(const selection_outcome of ['NOT_JOINED','SELECTION_CANCELLED'])await assert.rejects(()=>pipelineEmailContext({api:async()=>({...member,selection_outcome})},context),/no Not Joined or Selection Cancelled template/);
});

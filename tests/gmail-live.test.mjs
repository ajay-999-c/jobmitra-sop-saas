import test from 'node:test';
import assert from 'node:assert/strict';
import {recipientMatches,sendConfirmation,emailHistoryHTML} from '../src/jobmitra/static/ats_v2/gmail-send.mjs';
const jobmitra={candidateId:'42',candidateName:'Jobmitra',candidateEmail:'jobs@jobmitra.com'};
const pooja={candidateId:'17',candidateName:'Pooja Jobmitra',candidateEmail:'pooja.jobmitra@gmail.com'};
const recipient=c=>({allowed:true,candidate_id:Number(c.candidateId),candidate_name:c.candidateName,intended_recipient:c.candidateEmail,actual_recipient:c.candidateEmail});
test('switching candidate changes actual confirmation recipient without a hardcoded address',()=>{
 for(const context of [pooja,jobmitra]){
  assert.equal(recipientMatches(context,recipient(context)),true);
  const confirmation=sendConfirmation({mode:'live'},recipient(context),'Reviewed subject');
  assert.ok(confirmation.includes('To: '+context.candidateEmail));assert.ok(!confirmation.includes('test email'));
 }
 assert.ok(!sendConfirmation({mode:'live'},recipient(jobmitra),'Reviewed subject').includes(pooja.candidateEmail));
 assert.ok(sendConfirmation({mode:'test'},recipient(pooja),'Reviewed subject').includes('test email'));
 assert.ok(sendConfirmation({mode:'live'},recipient(jobmitra),'Reviewed subject',true).includes('may duplicate'));
});
test('missing, invalid and stale candidate/name/recipient snapshots cannot enable sending',()=>{
 assert.equal(recipientMatches(jobmitra,null),false);
 assert.equal(recipientMatches(jobmitra,{allowed:false,detail:'Missing email'}),false);
 assert.equal(recipientMatches(jobmitra,recipient(pooja)),false);
 assert.equal(recipientMatches(jobmitra,{...recipient(jobmitra),candidate_name:'Other person'}),false);
 assert.equal(recipientMatches(jobmitra,{...recipient(jobmitra),intended_recipient:'changed@example.test'}),false);
});
test('live and historical test emails retain distinct history labels and canonical recipient',()=>{
 const entry={candidate_id:42,test_mode:false,status:'Accepted by Gmail',subject:'Reviewed subject',actual_recipient:'jobs@jobmitra.com',email_reference:'ref',gmail_message_id:'mock-id'};
 const live=emailHistoryHTML([entry],42);assert.ok(live.includes('jobs@jobmitra.com'));assert.ok(live.includes('mock-id'));assert.ok(!live.includes('Test email'));
 assert.ok(emailHistoryHTML([{...entry,test_mode:true}],42).includes('Test email'));
});

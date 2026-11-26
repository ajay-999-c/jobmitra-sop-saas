import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {candidateTemplates,emailEntries,emailHistoryHTML} from '../src/jobmitra/static/ats_v2/gmail-send.mjs';

test('direct-send template allowlist matches actual approved candidate options',()=>{
 const source=fs.readFileSync('Jobmitra_Unified_Workspace_V12_Companies_Integrated (1).html','utf8');
 const document=JSON.parse(source.match(/const EMAIL_STUDIO_DOCUMENT=("(?:\\.|[^"\\])*");/)[1]);
 const selector=document.match(/<select id="candidateStatus"[^>]*>([\s\S]*?)<\/select>/)[1];
 const ids=[...selector.matchAll(/<option value="([^"]+)"/g)].map(m=>m[1]).filter(x=>!['candidate_submission','f2f_company'].includes(x));
 assert.deepEqual([...candidateTemplates].sort(),ids.sort());
 assert.ok(!candidateTemplates.has('candidate_submission'));assert.ok(!candidateTemplates.has('f2f_company'));
});
const attempt={event_type:'EMAIL_SEND_ATTEMPT',candidate_id:17,job_id:25,jd_candidate_id:34,created_at:'2026-11-26T10:00:00Z',payload:{email_reference:'same-reference',status:'Sending',subject:'Reviewed subject',actual_recipient:'test@example.test',test_mode:true}};
test('attempt and result collapse to one persistent candidate/JD email entry',()=>{
 const result={...attempt,event_type:'EMAIL_SEND_RESULT',payload:{email_reference:'same-reference',status:'Accepted by Gmail',gmail_message_id:'gmail-id',sent_at:'2026-11-26T10:00:05Z'}};
 const entries=emailEntries([attempt,result],Date.parse('2026-11-26T10:10:00Z'));
 assert.deepEqual(emailEntries([result,attempt],Date.parse('2026-11-26T10:10:00Z')),entries);
 assert.equal(entries.length,1);assert.equal(entries[0].status,'Accepted by Gmail');assert.equal(entries[0].candidate_id,17);assert.equal(entries[0].job_id,25);assert.equal(entries[0].subject,'Reviewed subject');
 const html=emailHistoryHTML(entries,'17');assert.ok(html.includes('gmail-id'));assert.ok(html.includes('Test email'));assert.equal(emailHistoryHTML(entries,18),'');
});
test('abandoned claims display unknown and history escapes untrusted subject',()=>{
 const entries=emailEntries([{...attempt,payload:{...attempt.payload,subject:'<img src=x onerror=alert(1)>'}}],Date.parse('2026-11-26T10:10:00Z'));
 assert.equal(entries[0].status,'Send outcome unknown');const html=emailHistoryHTML(entries,17);assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img'));
});

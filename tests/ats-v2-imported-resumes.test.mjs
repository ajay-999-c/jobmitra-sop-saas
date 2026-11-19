import test from 'node:test';
import assert from 'node:assert/strict';
import {resumeVersion} from '../src/jobmitra/static/ats_v2/shared.mjs';

const base={id:42,created_at:'2026-11-17T00:00:00Z',is_current:0};

test('missing imported files keep metadata and status without offering JSON or a download',()=>{
  for(const resume_kind of ['ORIGINAL','JOBMITRA_STANDARD']){
    const html=resumeVersion({...base,resume_kind,downloadable:false,file_status:'missing'});
    assert.match(html,/Source file unavailable · metadata preserved/);
    assert.match(html,/File status: Missing/);
    assert.doesNotMatch(html,/data-resume-json|\/download|View saved professional JSON/);
  }
});

test('historical parsed evidence explicitly requires renewed review',()=>{
  const html=resumeVersion({...base,resume_kind:'PARSED_TEXT',historical_parsed_json:{skills:['Python']},requires_review:true});
  assert.match(html,/Review required/);
  assert.match(html,/View imported parsed JSON/);
  assert.match(html,/data-resume-json="42"/);
  assert.match(html,/Review against the original/);
  assert.doesNotMatch(html,/\/download|Current/);
});

test('available resume versions provide their scoped download without exposing storage paths',()=>{
  const html=resumeVersion({...base,resume_kind:'ORIGINAL',downloadable:true,is_current:1,original_filename:'Candidate <script>.pdf',storage_path:'/private/secret/path.pdf'});
  assert.match(html,/href="\/api\/ats-v2\/resumes\/42\/download"/);
  assert.match(html,/Candidate &lt;script&gt;\.pdf/);
  assert.match(html,/Current/);
  assert.doesNotMatch(html,/<script>|\/private\/secret/);
});

test('native professional JSON remains a separate viewable version',()=>{
  const html=resumeVersion({...base,resume_kind:'PARSED_TEXT',profile:{skills:['Python']},is_current:1});
  assert.match(html,/View saved professional JSON/);
  assert.doesNotMatch(html,/Source file unavailable|Review required/);
});

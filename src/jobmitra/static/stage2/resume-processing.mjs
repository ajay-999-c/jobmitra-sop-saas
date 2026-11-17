const $ = id => document.getElementById(id);
const API = '/api/resume-processing';
const active = new Set(['QUEUED','EXTRACTING','MASKING','PARSING','GENERATING']);
const stateNames = {UPLOADED:'Resume Uploaded',READY_FOR_LLM:'Ready for Groq Parsing',QUEUED:'Queued',EXTRACTING:'Text Extraction',MASKING:'PII Masking',PARSING:'Groq Parsing',REVIEW_REQUIRED:'Review Required',APPROVED:'Approved for generation',GENERATING:'Resume Generation',COMPLETED:'Completed',FAILED:'Failed',DEFERRED:'Waiting for provider retry'};
const errors = {MISSING_API_KEY:'The processor Groq API key is not configured. Ask the administrator to configure it locally.',DEPENDENCY_MISSING:'A processor dependency is missing. Check the separate processing environment.',MASKING_FAILED:'Local masking failed. The resume has not been sent for parsing; local review is required.',LOCAL_REVIEW_REQUIRED:'Local screening or integrity checks need attention. Review the original and the processor’s private artifacts before retrying.',PARSING_FAILED:'Parsing failed. Review configuration or output locally before an explicit retry.',RATE_LIMIT:'The provider deferred this request. Wait until the displayed retry time.',WORKER_STOPPED:'The worker stopped or timed out. Check the processor environment before retrying.',PROCESSING_FAILED:'Processing could not finish. Check local dependencies before retrying.',INTERRUPTED:'Processing was interrupted. Check the worker before retrying.',REJECTED:'This version needs correction and has not been approved.'};
const warningMessages = {
  candidate_name_mismatch: 'The detected resume name differs from registration. The registered identity is preserved; verify the match during review.',
  personal_detail_outside_masking_scope: 'Sanitized input still contains personal-detail labels such as DOB. This is a privacy warning and may be sent to Groq.',
  address_outside_masking_scope: 'Sanitized input still contains an address. It is not fully anonymized and may be sent to Groq.'
};
let current = '',  registered = '', review = null, timer = null, loadingReview = '';
function fail(error) { $('rp-error').textContent = error.message || 'Operation unavailable.'; $('rp-error').hidden = false; }
function clearError() { $('rp-error').hidden = true; }
function node(tag, text, parent) { const el=document.createElement(tag); if(text) el.textContent=text; if(parent) parent.append(el); return el; }
async function api(path, options={}) {
  const response = await fetch(API+path, {credentials:'same-origin',cache:'no-store',...options,headers:{'X-Jobmitra-UI':'1',...options.headers}});
  const body = await response.json();
  if(!response.ok) throw Error(body.detail || 'Operation unavailable.');
  return body;
}
const post = (path, values) => api(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values || {})});
async function refreshLists() {
  const [candidates,documents]=await Promise.all([api('/candidates'),api('/documents')]);
  const selected=$('rp-existing').value;
  $('rp-existing').replaceChildren(new Option('Register a new candidate',''));
  for(const c of candidates) $('rp-existing').add(new Option(`${c.full_name} · ${c.candidate_id.slice(0,8)}`,c.candidate_id));
  $('rp-existing').value=selected;
  $('rp-recent').replaceChildren(new Option('Choose a registered resume',''));
  for(const d of documents) $('rp-recent').add(new Option(`${d.candidate_name} · ${d.document_id.slice(0,8)} · ${stateNames[d.state] || d.state}`,d.document_id));
  $('rp-recent').value=current;
}
function section(title, items, parent) {
  if(!items?.length) return;
  node('h3',title,parent);
  const list=node('ul','',parent);
  for(const item of items) node('li',item,list);
}
function showProfessional(data) {
  const out=$('rp-professional'); out.replaceChildren();
  const p=data.presentation;
  node('h2',p.candidate_name,out);
  if(p.professional_title) node('p',p.professional_title,out);
  if(p.professional_summary) { node('h3','Professional Summary',out); node('p',p.professional_summary,out); }
  section('Skills',p.skills,out);
  if(p.work_experience?.length) {
    node('h3','Work Experience',out);
    for(const job of p.work_experience) {node('h4',[job.role,job.company].filter(Boolean).join(' · '),out);node('p',job.period,out);section('Responsibilities & achievements',job.responsibilities,out);}
  }
  if(p.projects?.length) {
    node('h3','Projects',out);
    for(const project of p.projects) {node('h4',project.name,out);node('p',project.description,out);section('Technologies',project.technologies,out);if(project.associated_employer)node('p',project.associated_employer,out);}
  }
  section('Education',p.education,out); section('Certifications',p.certifications,out); section('Languages',p.languages,out);
}
async function poll() {
  clearTimeout(timer);
  if(!current) return;
  const id=current;
  try {
    const s=await api(`/documents/${id}`);
    if(id!==current) return;
    const progress=$('rp-progress');progress.replaceChildren();
    node('p',stateNames[s.state] || s.state,progress).className='rp-state';
    node('p',`${s.candidate_name} · ${s.document_id.slice(0,12)}`,progress);
    const steps=node('ol','',progress);steps.className='rp-steps';
    s.steps.forEach((label,index)=>{const li=node('li','',steps);const done=index<s.stage || s.state==='COMPLETED';li.dataset.complete=String(done);node('span',label,li);node('span',done?'Done':index===s.stage&&active.has(s.state)?'In progress':'Pending',li);});
    if(s.warnings?.length) {
      const warnings=node('div','',progress);warnings.className='notice';
      node('strong','Warnings — processing is allowed',warnings);
      const list=node('ul','',warnings);
      for(const warning of s.warnings) node('li',warningMessages[warning] || 'Additional privacy review recommended.',list);
    }
    if(s.error) node('p',errors[s.error] || 'Local review required.',progress);
    if(s.next_retry_at) node('p','Retry after: '+new Date(s.next_retry_at*1000).toLocaleString(),progress);
    $('rp-process').disabled=active.has(s.state) || ['APPROVED','COMPLETED'].includes(s.state) || (s.state==='REVIEW_REQUIRED'&&!s.error);
    $('rp-original').href=`${API}/documents/${id}/downloads/original`;$('rp-original').hidden=false;
    const canReview=['REVIEW_REQUIRED','APPROVED','COMPLETED'].includes(s.state) && s.llm_status==='COMPLETED';
    $('rp-review-panel').hidden=!canReview;
    $('rp-export-panel').hidden=!['APPROVED','GENERATING','COMPLETED'].includes(s.state);
    $('rp-generate').disabled=s.state!=='APPROVED';
    $('rp-review-note').textContent=['APPROVED','COMPLETED'].includes(s.state)?'This saved version has been reviewed and approved.':'';
    if(canReview && loadingReview!==id) {
      const data=await api(`/documents/${id}/review`);
      if(id!==current)return;
      review=data;loadingReview=id;$('rp-facts').checked=false;showProfessional(data);
    }
    const downloads=$('rp-downloads');downloads.replaceChildren();
    const labels={preview:'Preview Resume',branded_pdf:'Download Jobmitra Branded PDF',plain_pdf:'Download Plain ATS PDF',docx:'Download Editable DOCX'};
    for(const kind of s.exports) {const a=node('a',labels[kind],downloads);a.href=`${API}/documents/${id}/downloads/${kind}`;a.target='_blank';a.rel='noopener';}
    if(active.has(s.state)) timer=setTimeout(poll,1800);
  } catch(error) {fail(error);}
}
function choose(id) {current=id;review=null;loadingReview='';location.hash=id;clearError();poll();}
$('rp-form').addEventListener('submit',async event=>{
  event.preventDefault();clearError();$('rp-upload').disabled=true;
  try {
    const file=$('rp-file').files[0];
    if(!file)throw Error('Choose a PDF or DOCX.');
    const values={full_name:$('rp-name').value,email:$('rp-email').value||null,mobile:$('rp-mobile').value||null,consent:$('rp-consent').checked,candidate_id:registered||$('rp-existing').value||null};
    const candidate=await post('/candidates',values);registered=candidate.candidate_id;
    const result=await api(`/candidates/${registered}/documents`,{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream','X-Resume-Format':file.name.split('.').pop().toLowerCase(),'X-Candidate-Consent':'confirmed','X-Candidate-Location':encodeURIComponent($('rp-location').value)}});
    choose(result.document_id);await refreshLists();
  } catch(error) {fail(error);} finally {$('rp-upload').disabled=false;}
});
$('rp-existing').addEventListener('change',()=>{registered='';const value=$('rp-existing').selectedOptions[0].textContent;if($('rp-existing').value)$('rp-name').value=value.split(' · ')[0];});
$('rp-name').addEventListener('input',()=>{registered='';});
$('rp-recent').addEventListener('change',()=>choose($('rp-recent').value));
$('rp-refresh').addEventListener('click',()=>{clearError();refreshLists().then(poll).catch(fail);});
$('rp-process').addEventListener('click',async()=>{clearError();$('rp-process').disabled=true;try{await post(`/documents/${current}/process`);await poll();}catch(error){fail(error);$('rp-process').disabled=false;}});
async function decide(approved) {
  clearError();
  try {if(!review||!$('rp-facts').checked)throw Error('Compare the source resume and confirm the factual review first.');
    await post(`/documents/${current}/review`,{parse_id:review.parse_id,sha256:review.sha256,approved,facts_reviewed:true});await poll();
  }catch(error){fail(error);}
}
$('rp-approve').addEventListener('click',()=>decide(true));
$('rp-reject').addEventListener('click',()=>decide(false));
$('rp-generate').addEventListener('click',async()=>{clearError();$('rp-generate').disabled=true;try{await post(`/documents/${current}/exports`);await poll();}catch(error){fail(error);$('rp-generate').disabled=false;}});
current=/^[a-f0-9]{64}$/.test(location.hash.slice(1))?location.hash.slice(1):'';
refreshLists().then(poll).catch(fail);

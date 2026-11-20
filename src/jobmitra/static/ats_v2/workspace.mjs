import {$,$$,api,save,esc,pretty,pill,empty,list,field,values,numberOrNull,words,date,history,dialog,error,clear,notice,bindErrors} from './shared.mjs';
import {unified,v12,v12save,key,actorField} from './unified.mjs';

const host=$('#ats-workspace');
const params=new URLSearchParams(location.search);
const state={view:params.get('view')||'dashboard',jobId:params.get('job')||'',jobs:[],jobsPage:1,jobsTotal:0,jobsPageSize:20,summary:{},companyError:null,workflow:null,pipeline:null,stage:'ALL',historyPage:1};
const fixed=[['POOL','Candidate Pool'],['CONTACT','Candidate Contact'],['SCREENING','Jobmitra Screening'],['COMPANY_SUBMISSION','Company Submission']];
const outcomes=[['SELECTED','Selected'],['JOINED','Joined'],['NOT_SELECTED','Not Selected'],...(unified?[['NOT_JOINED','Not Joined'],['SELECTION_CANCELLED','Selection Cancelled']]:[])];
const numeric=['vacancies','experience_min','experience_max','salary_min_inr','salary_max_inr'];
let companyOptions=[];
let workflowDraft=null;
const current=()=>state.jobs.find(job=>String(job.id)===String(state.jobId));
const rows=data=>list(Array.isArray(data)?data:data?.items);
const jobLabel=job=>`${job.jd_code||'JD '+job.id} · ${job.title}`;
const companyLabel=job=>job.company_name||'Company name unavailable';
const stages=()=>[...fixed.map(([key,label])=>({key,label})),...list(state.workflow?.rounds).filter(r=>r.is_active).sort((a,b)=>a.display_order-b.display_order).map(r=>({key:'ROUND:'+r.id,label:r.round_name})),...outcomes.map(([key,label])=>({key,label}))];
const stageKey=row=>row.stage_code==='ROUND'?'ROUND:'+row.round_id:row.effective_status||row.stage_code;
const stageLabel=row=>row.stage_label||stages().find(s=>s.key===stageKey(row))?.label||pretty(row.stage_code);
const today=()=>new Date(Date.now()+330*60000).toISOString().slice(0,10);

async function loadJobs(){
  const data=await api(`/jobs?page=${state.jobsPage}&page_size=${state.jobsPageSize}`);
  state.jobs=rows(data);state.jobsTotal=data.total;state.summary=data.summary||{};state.companyError=data.company_error;
}
async function loadSelected(){
  if(!state.jobId)return;
  const job=await api('/jobs/'+encodeURIComponent(state.jobId));
  const index=state.jobs.findIndex(row=>row.id===job.id);
  if(index<0)state.jobs.unshift(job);else state.jobs[index]=job;
  const [workflow,pipeline]=await Promise.all([api(`/jobs/${state.jobId}/workflow`),api(`/jobs/${state.jobId}/pipeline`)]);
  state.workflow=workflow;state.pipeline=pipeline;
}
function navigation(){
  const title=state.view==='create'?'Create JD':state.view==='dashboard'?'JD Dashboard':current()?.title||'JD Workspace';
  $('#ats-page-title').textContent=title;
  $('#ats-page-subtitle').textContent=state.view==='dashboard'?'Targets, hiring progress and candidate journeys in one workspace.':state.view==='create'?'Choose an existing company and set a hiring target.':current()?`${jobLabel(current())} · ${companyLabel(current())}`:'Select a job requirement to continue.';
  $$('[data-view]').forEach(button=>{const selected=button.dataset.view===state.view;button.toggleAttribute('aria-current',selected);if(selected)button.setAttribute('aria-current','page');});
  const query=new URLSearchParams();if(state.view!=='dashboard')query.set('view',state.view);if(state.jobId&&state.view!=='create')query.set('job',state.jobId);
  window.history.replaceState(null,'',location.pathname+(query.size?'?'+query:''));
}
function selector(){
  return `<div class="ats-selector"><label>Job requirement<select id="ats-job-select"><option value="">Choose a JD</option>${state.jobs.map(job=>`<option value="${esc(job.id)}" ${String(job.id)===String(state.jobId)?'selected':''}>${esc(jobLabel(job))} · ${esc(pretty(job.status))}</option>`).join('')}</select></label>${current()?`<span class="ats-pill">${esc(pretty(current().status))}</span>`:''}<button class="ats-btn ats-secondary ats-small" id="ats-refresh" type="button">Refresh</button></div>`;
}
function targetTone(value){const key=String(value||'').toUpperCase();return key.includes('OVERDUE')?'ats-red':key==='DUE'||key.includes('SOON')||key.includes('TODAY')?'ats-amber':key.includes('FILLED')||key.includes('TRACK')?'ats-green':'';}
function dashboard(){
  const summary=state.summary;
  const metric=(key,aliases)=>summary[key]??aliases.map(alias=>summary[alias]).find(v=>v!==undefined)??0;
  host.innerHTML=`<div class="ats-metrics">${[['Active JDs',metric('active',['active_count']),''],['Overdue',metric('overdue',['overdue_count']),'ats-red'],['Due soon',metric('due_soon',['due_soon_count']),'ats-amber'],['Filled / closed',metric('filled_closed',['filled_or_closed','closed','closed_count']),'ats-green']].map(([label,count,tone])=>`<div class="ats-metric ${tone}"><span>${label}</span><strong>${esc(count)}</strong></div>`).join('')}</div>${state.companyError?`<div class="ats-alert ats-warning">${esc(state.companyError===true?'The local ATS company list is temporarily unavailable. Check the ATS database and retry.':state.companyError)}</div>`:''}<section class="ats-card"><div class="ats-card-head"><div><h2>Job requirements</h2><p class="ats-muted">Deadline status follows the Asia/Kolkata calendar. Only confirmed joined candidates fill vacancies.</p></div><button id="ats-refresh" class="ats-btn ats-secondary ats-small" type="button">Refresh</button></div><div class="ats-list">${state.jobs.length?state.jobs.map(job=>`<article class="ats-card ats-job"><div><button type="button" class="ats-job-title" data-open-job="${esc(job.id)}">${esc(job.title)} →</button><p class="ats-muted">${esc(companyLabel(job))} · ${esc(job.jd_code||'JD '+job.id)}</p><div class="ats-pills">${pill(pretty(job.status))}${pill(pretty(job.target_state||job.target_status||'NEUTRAL'),targetTone(job.target_state||job.target_status))}${job.location?pill(job.location,'ats-blue'):''}</div><div class="ats-job-meta"><span>Created ${esc(date(job.created_at))}</span><span>Target ${esc(date(job.target_date))}</span><span>Joined ${esc(job.joined_count??job.joined??0)} / ${esc(job.vacancies??'vacancies not recorded')}</span></div></div><div class="ats-actions"><button class="ats-btn ats-secondary ats-small" type="button" data-open-job="${esc(job.id)}">Open pipeline</button></div></article>`).join(''):empty('Your hiring workspace is ready','Create a JD to start tracking targets and candidate journeys.')}</div>${pagination({page:state.jobsPage,page_size:state.jobsPageSize,total:state.jobsTotal},'ats-jobs-page')}</section>`;
}
function jdFields(job={}){
  return `<div class="ats-form-grid">${field('company_id','Company',job.company_id||'',{required:true,choices:[['','Choose an existing company'],...companyOptions.map(c=>[c.id,c.company_name])]})}<div class="ats-stack"><p class="ats-hint">Company not listed? Add it through the existing Companies page, then import company changes before refreshing this list.</p><div class="ats-actions"><a class="ats-link" href="/companies" target="_blank" rel="noopener">Add New Company ↗</a><button id="ats-refresh-companies" class="ats-link" type="button">Refresh company list</button></div><details class="ats-hint"><summary>When does a new company become available?</summary><p>An operator runs the one-way company import, then you refresh this list. Existing companies are updated by their stable identifier.</p><code>python scripts/migrate_postgres_masters_to_sqlite.py --execute --companies-only</code></details></div>${field('title','Job title / working title',job.title||'',{required:true})}${field('target_date','Target date',job.target_date||'',{type:'date',required:true,min:job.created_at?String(job.created_at).slice(0,10):today()})}${field('status','JD status',job.status||'DRAFT',{choices:['DRAFT','ACTIVE','ON_HOLD','CLOSED']})}${field('vacancies','Vacancies',job.vacancies??'',{type:'number',min:1,step:1})}${field('location','Location',job.location||'')}${field('work_mode','Work mode',job.work_mode||'',{choices:[['','Not recorded'],'ONSITE','HYBRID','REMOTE']})}${field('skills','Key skills · comma separated',list(job.skills||job.skills_json).join(', '),{span:true})}${field('experience_min','Minimum experience · years',job.experience_min??'',{type:'number',min:0,step:.1})}${field('experience_max','Maximum experience · years',job.experience_max??'',{type:'number',min:0,step:.1})}${field('qualification','Qualification',job.qualification||'',{span:true})}${field('salary_min_inr','Salary minimum · ₹',job.salary_min_inr??'',{type:'number',min:0,step:1})}${field('salary_max_inr','Salary maximum · ₹',job.salary_max_inr??'',{type:'number',min:0,step:1})}${field('salary_period','Salary period',job.salary_period||'',{choices:[['','Not recorded'],'MONTHLY','ANNUAL']})}${field('salary_basis','Salary basis',job.salary_basis||'UNKNOWN',{choices:['UNKNOWN','CTC','GROSS','IN_HAND']})}${field('company_contact','Company contact · optional',job.company_contact||'',{span:true})}${field('requirement_notes','Requirement notes',job.requirement_notes||'',{type:'textarea',span:true})}${field('full_jd','Full job description',job.full_jd||'',{type:'textarea',span:true})}</div>`;
}
async function companies(){
  try{companyOptions=rows(await api('/companies'));return true;}catch(err){companyOptions=[];error(err);return false;}
}
async function renderDetails(create=false){
  const ready=await companies();const job=create?{}:current();
  if(!create&&!job){host.innerHTML=selector()+empty('Select a JD','Choose a requirement to view or edit its details.');return;}
  host.innerHTML=`${create?'':selector()}<section class="ats-card"><div class="ats-card-head"><div><h2>${create?'Create a job requirement':'JD Details'}</h2><p class="ats-muted">Company, job title and target date are required. Missing optional facts remain unknown.</p></div>${!create?pill(job.jd_code||'JD '+job.id):''}</div>${!ready?'<div class="ats-alert ats-warning">The local ATS company list could not be loaded. Check the ATS database, then refresh before saving.</div>':''}<form id="ats-jd-form">${jdFields(job)}<div class="ats-form-footer"><span class="ats-hint">Salary period and basis are stored separately. Dates use Asia/Kolkata.</span><div class="ats-actions"><button id="ats-cancel-edit" class="ats-btn ats-secondary" type="button">Cancel</button><button class="ats-btn" type="submit" ${!ready?'disabled':''}>${create?'Create JD':'Save JD details'}</button></div></div></form></section>`;
  if(unified&&!create){const footer=document.createElement('div');footer.className='ats-card ats-form-section';footer.innerHTML=`<h3>Company email contact</h3><p class="ats-muted">${esc(job.company_contact_name_snapshot||'No contact selected')} · ${esc(job.company_contact_email_snapshot||'Email not recorded')}</p><button id="v12-choose-contact" class="ats-btn ats-secondary" type="button">Choose contact</button>`;host.append(footer);$('#v12-choose-contact').onclick=chooseContact;}
  if(unified){const info=$('#ats-refresh-companies').closest('.ats-stack');info.querySelectorAll('details').forEach(e=>e.remove());const a=info.querySelector('a');a.href='/workspace-v12/companies';a.textContent='Open Companies ↗';info.querySelector('p').textContent='Create or review a canonical company in Companies, then refresh this list.';}
  $('#ats-refresh-companies').onclick=bindErrors(async()=>{const select=$('[name=company_id]');const selected=select.value;if(await companies()) {select.innerHTML='<option value="">Choose an existing company</option>'+companyOptions.map(c=>`<option value="${esc(c.id)}">${esc(c.company_name)}</option>`).join('');select.value=selected;$('#ats-jd-form button[type=submit]').disabled=false;notice('Imported company list refreshed.');}});
  $('#ats-jd-form').onsubmit=bindErrors(async event=>{
    event.preventDefault();clear();const button=event.submitter;button.disabled=true;
    try{const data=values(event.target);numeric.forEach(key=>data[key]=numberOrNull(data[key]));data.skills=words(data.skills);for(const key of ['location','work_mode','qualification','salary_period','company_contact','requirement_notes','full_jd'])if(data[key]==='')data[key]=null;const result=await save(create?'/jobs':'/jobs/'+state.jobId,data,create?'POST':'PATCH',{'Idempotency-Key':event.target.dataset.requestKey||(event.target.dataset.requestKey=key())});state.jobId=String(result.id);state.view='pipeline';await loadJobs();await loadSelected();await render();notice(create?'JD created. Its candidate pool starts empty.':'JD details saved. The changes are recorded in history.');}finally{button.disabled=false;}
  });
}
function impactHTML(){
  const items=list(state.workflow?.impact);return `<div class="ats-quiet"><strong>Review candidate impact</strong><p>Workflow changes keep every candidate in their current stage. Historical stage labels remain as recorded.</p>${items.length?items.map(item=>`<p>${esc(item.round_name||'Round')} · ${esc(item.candidates??item.candidate_count??0)} currently assigned</p>`).join(''):'<p>No candidates are currently assigned to a company round.</p>'}<p>Retiring a round or changing interview mode may require resolving active references first. The server validates the saved workflow.</p></div>`;
}
function renderWorkflow(){
  if(!current()){host.innerHTML=selector()+empty('Select a JD','Choose a requirement to configure its company interview process.');return;}
  workflowDraft=structuredClone(state.workflow);renderWorkflowDraft();
}
function renderWorkflowDraft(){
  host.innerHTML=selector()+`<div class="ats-columns"><section class="ats-card"><div class="ats-card-head"><div><h2>Hiring Workflow</h2><p class="ats-muted">Version ${esc(state.workflow.workflow_version)} · Save one version after reviewing your changes.</p></div>${pill('Fixed Jobmitra stages','ats-blue')}</div><div class="ats-stage-row">${fixed.map(([,label])=>`<div class="ats-stage"><small>Jobmitra · fixed</small><span>${label}</span></div>`).join('')}</div><h3>Company interview process</h3><label>Interview mode<select id="ats-workflow-mode">${['UNKNOWN','DIRECT','CONFIGURED'].map(value=>`<option value="${value}" ${workflowDraft.workflow_mode===value?'selected':''}>${value==='UNKNOWN'?'Not confirmed':value==='DIRECT'?'Direct selection':'Configured interview rounds'}</option>`).join('')}</select></label><p class="ats-hint">${workflowDraft.workflow_mode==='UNKNOWN'?'Sourcing may begin; company progression requires a confirmed process.':workflowDraft.workflow_mode==='DIRECT'?'Direct selection follows Company Submission without a configured round.':'Give each company round a clear name. Stable round IDs preserve candidate history.'}</p><div id="ats-round-list">${list(workflowDraft.rounds).map((round,index)=>`<div class="ats-round ${round.is_active?'':'ats-retired'}" data-round="${index}"><span class="ats-round-number">${round.is_active?list(workflowDraft.rounds).slice(0,index+1).filter(r=>r.is_active).length:'—'}</span><div class="ats-form-grid">${field('round_name','Round name',round.round_name,{required:true})}${field('round_mode','Interview type',round.mode,{choices:['FLEXIBLE','FACE_TO_FACE','VIDEO','PHONE']})}<p class="ats-hint ats-span">${round.is_active?'Active company interview':'Retired · preserved in history'}</p></div><div class="ats-round-controls"><button class="ats-btn ats-secondary ats-small" type="button" data-round-up="${index}" ${index===0?'disabled':''} aria-label="Move round up">↑</button><button class="ats-btn ats-secondary ats-small" type="button" data-round-down="${index}" ${index===workflowDraft.rounds.length-1?'disabled':''} aria-label="Move round down">↓</button><button class="ats-btn ats-secondary ats-small" type="button" data-round-toggle="${index}">${round.is_active?'Retire':'Restore'}</button></div></div>`).join('')||empty('No company rounds','Choose Configured interview rounds, then add your first round.')}</div><button type="button" id="ats-add-round" class="ats-btn ats-secondary ats-full" ${workflowDraft.workflow_mode!=='CONFIGURED'?'disabled':''}>＋ Add company round</button><div class="ats-form-section"><h3>Hiring outcomes</h3><div class="ats-pills">${pill('Selected','ats-green')}${pill('Joined · separately confirmed','ats-green')}${pill('Not Selected','ats-red')}</div></div><div class="ats-form-footer"><button class="ats-btn ats-secondary" id="ats-reset-workflow" type="button">Discard draft changes</button><button class="ats-btn" id="ats-save-workflow" type="button">Review &amp; save workflow</button></div></section><aside class="ats-card"><h2>Candidate impact</h2>${impactHTML()}<p class="ats-hint">Existing rounds are retired or restored. Saved rounds are never deleted through this workspace.</p></aside></div>`;
  $('#ats-workflow-mode').onchange=event=>{captureRounds();workflowDraft.workflow_mode=event.target.value;renderWorkflowDraft();};
  $('#ats-add-round').onclick=()=>{captureRounds();workflowDraft.rounds.push({id:null,round_name:'New interview round',mode:'FLEXIBLE',is_active:true});renderWorkflowDraft();};
  $('#ats-reset-workflow').onclick=()=>{workflowDraft=structuredClone(state.workflow);renderWorkflowDraft();};
  $('#ats-save-workflow').onclick=()=>{captureRounds();dialog('Review workflow changes',`<p class="ats-muted">Save version ${Number(state.workflow.workflow_version)+1}. Candidate stages are preserved.</p>${impactHTML()}<div class="ats-quiet">${esc(pretty(workflowDraft.workflow_mode))} · ${workflowDraft.rounds.filter(r=>r.is_active).length} active round(s)</div>`,'Save workflow version',async()=>{const payload={workflow_mode:workflowDraft.workflow_mode,workflow_version:state.workflow.workflow_version,rounds:workflowDraft.rounds.map(({id,round_name,mode,is_active})=>({id,round_name,mode,is_active:Boolean(is_active)}))};await save(`/jobs/${state.jobId}/workflow`,payload,'PUT');await loadJobs();await loadSelected();await render();notice('Workflow version saved. Candidate stages were preserved.');});};
}
function captureRounds(){
  $$('[data-round]').forEach(element=>{const round=workflowDraft.rounds[Number(element.dataset.round)];round.round_name=$('[name=round_name]',element).value;round.mode=$('[name=round_mode]',element).value;});
}
function pipeline(){
  if(!current()){host.innerHTML=selector()+empty('Select a JD','Choose a requirement to view its candidate pipeline.');return;}
  const items=rows(state.pipeline);const definitions=stages();const counts=Object.fromEntries(definitions.map(s=>[s.key,items.filter(item=>stageKey(item)===s.key).length]));
  const filtered=state.stage==='ALL'?items:items.filter(item=>stageKey(item)===state.stage);
  host.innerHTML=selector()+`<section class="ats-card"><div class="ats-card-head"><div><h2>Hiring workflow · candidate stages</h2><p class="ats-muted">Current stage counts. Click a stage to view its candidates.</p></div><button class="ats-btn ats-secondary ats-small" type="button" data-stage="ALL">All candidates (${items.length})</button></div><div class="ats-stage-row">${definitions.map(s=>`<button class="ats-stage ${s.key.startsWith('ROUND:')?'ats-round-stage':s.key==='NOT_SELECTED'?'ats-rejected':['SELECTED','JOINED'].includes(s.key)?'ats-outcome':''}" type="button" data-stage="${esc(s.key)}" aria-pressed="${state.stage===s.key}"><small>${s.key.startsWith('ROUND:')?'Company round':outcomes.some(([key])=>key===s.key)?'Outcome':'Jobmitra · fixed'}</small><span>${esc(s.label)}</span><strong>${esc(counts[s.key]||0)}</strong></button>`).join('')}</div></section><section class="ats-card ats-form-section"><div class="ats-card-head"><div><h2>${esc(state.stage==='ALL'?'All candidates':definitions.find(s=>s.key===state.stage)?.label||'Candidate stage')}</h2><p class="ats-muted">${filtered.length} candidate(s) · Selected and Joined are separate confirmations.</p></div><a class="ats-btn ats-secondary ats-small" href="/candidate-search-v2?job=${esc(state.jobId)}">＋ Find candidates</a></div><div class="ats-stack">${filtered.length?filtered.map(item=>`<article class="ats-card ats-candidate-row ${['SELECTED','JOINED'].includes(item.stage_code)?'ats-closed':item.stage_code==='NOT_SELECTED'?'ats-rejected':''}"><div class="ats-row-heading"><div><a href="/ats-v2/candidates/${esc(item.candidate_id)}" class="ats-job-title">${esc(item.full_name||'Candidate '+item.candidate_id)}</a><div class="ats-pills">${pill(stageLabel(item),item.stage_code==='ROUND'?'ats-purple':['SELECTED','JOINED'].includes(item.stage_code)?'ats-green':item.stage_code==='NOT_SELECTED'?'ats-red':'ats-blue')}</div>${item.rejected_from_stage?`<p class="ats-hint">Rejected at ${esc(item.rejected_round_name||pretty(item.rejected_from_stage))} · ${esc(date(item.rejected_at))}</p>`:''}${item.stage_note?`<p class="ats-hint">${esc(item.stage_note)}</p>`:''}</div><div class="ats-actions">${unified?placementButtons(item):''}<button class="ats-btn ats-secondary ats-small" data-journey="${esc(item.id)}" type="button">View journey</button><button class="ats-btn ats-secondary ats-small" data-feedback="${esc(item.id)}" type="button">＋ Feedback</button>${item.next_stage?`<button class="ats-btn ats-small" data-move="${esc(item.id)}" type="button">Advance → ${esc(item.next_stage==='ROUND'?state.workflow.rounds.find(r=>r.id===item.next_round_id)?.round_name||'Company round':fixed.concat(outcomes).find(([key])=>key===item.next_stage)?.[1]||pretty(item.next_stage))}</button>`:''}${!['SELECTED','JOINED','NOT_SELECTED'].includes(item.stage_code)?`<button class="ats-btn ats-danger ats-small" data-reject="${esc(item.id)}" type="button">Not Selected</button>`:''}</div></div></article>`).join(''):empty('No candidates in this stage','Use Candidate Search to add an existing candidate to this JD’s pool.')}</div></section>`;
}
async function viewHistory(page=1){
  state.historyPage=page;
  if(!current()){host.innerHTML=selector()+empty('Select a JD','Choose a requirement to view its complete activity history.');return;}
  const data=await api(`/history?job_id=${state.jobId}&page=${page}`);
  host.innerHTML=selector()+`<section class="ats-card"><div class="ats-card-head"><div><h2>JD Activity History</h2><p class="ats-muted">${esc(data.total)} append-only event(s) · displayed in Asia/Kolkata</p></div></div>${history(data.items)}${pagination(data,'ats-history-page')}</section>`;
}
function pagination(data,attribute){const max=Math.max(1,Math.ceil(data.total/(data.page_size||20)));return `<div class="ats-pagination"><button class="ats-btn ats-secondary ats-small" type="button" data-${attribute}="${data.page-1}" ${data.page<=1?'disabled':''}>Previous</button><span>Page ${esc(data.page)} of ${esc(max)}</span><button class="ats-btn ats-secondary ats-small" type="button" data-${attribute}="${data.page+1}" ${data.page>=max?'disabled':''}>Next</button></div>`;}
async function render(){
  navigation();
  if(state.view==='dashboard')dashboard();
  else if(state.view==='create'||state.view==='details')await renderDetails(state.view==='create');
  else if(state.view==='workflow')renderWorkflow();
  else if(state.view==='history')await viewHistory(state.historyPage);
  else {state.view='pipeline';pipeline();}
}
async function changeView(view){clear();state.view=view;state.stage='ALL';state.historyPage=1;await render();}
async function selectJob(id){clear();state.jobId=String(id||'');state.stage='ALL';state.historyPage=1;host.innerHTML=empty('Loading requirement…');await loadSelected();await render();}
const feedbackFields=()=>field('feedback','Feedback / notes','',{type:'textarea',span:true})+field('feedback_source','Feedback source','NOT_SPECIFIED',{choices:['NOT_SPECIFIED','COMPANY','JOBMITRA','CANDIDATE']});
function candidateAction(id,action){
  const item=rows(state.pipeline).find(row=>String(row.id)===String(id));if(!item)return;
  const reject=action==='reject',note=action==='feedback';
  const title=note?'Record candidate feedback':reject?'Mark candidate Not Selected':'Advance candidate';
  const next=reject?'NOT_SELECTED':item.next_stage;
  if(unified&&!note&&!reject&&['SELECTED','JOINED'].includes(next)){placementAction(item,next==='SELECTED'?'SELECT':'JOIN');return;}
  const destination=next==='ROUND'?state.workflow.rounds.find(r=>r.id===item.next_round_id)?.round_name:fixed.concat(outcomes).find(([key])=>key===next)?.[1]||pretty(next);
  dialog(title,`<p><strong>${esc(item.full_name)}</strong></p><div class="ats-quiet">Current stage: ${esc(stageLabel(item))}${!note?`<br>Change to: <strong>${esc(destination)}</strong>`:''}</div>${feedbackFields()}<p class="ats-hint">${note?'Feedback is required. It is recorded in this candidate’s JD journey.':reject?'The current stage name is preserved as a rejection snapshot.':'Feedback is optional. Stage change and supplied feedback are saved together.'}</p>`,note?'Save feedback':reject?'Save & mark Not Selected':'Save & advance',async data=>{
    if(note&&!data.feedback.trim())throw Error('Enter feedback before saving.');
    if(note)await save(`/jobs/${state.jobId}/candidates/${item.id}/feedback`,data);
    else await save(`/jobs/${state.jobId}/candidates/${item.id}/move`,{...data,stage_code:next,round_id:next==='ROUND'?item.next_round_id:null,expected_stage:item.stage_code,expected_round_id:item.round_id||null,workflow_version:state.workflow.workflow_version});
    await loadJobs();await loadSelected();pipeline();notice(note?'Feedback recorded.':'Candidate stage updated. History is preserved.');
  });
}
async function journey(id,page=1){
  const item=rows(state.pipeline).find(row=>String(row.id)===String(id));if(!item)return;
  const data=await api(`/history?job_id=${state.jobId}&candidate_id=${item.candidate_id}&jd_candidate_id=${item.id}&page=${page}`);
  dialog('Candidate-in-JD Journey',`<p class="ats-muted">${esc(item.full_name)} · ${esc(current().title)}</p><div class="ats-profile-section">${history(data.items)}</div>${pagination(data,'ats-journey-page')}`);
  $$('[data-ats-journey-page]',$('#ats-dialog')).forEach(button=>button.onclick=bindErrors(()=>journey(id,Number(button.dataset.atsJourneyPage))));
}

$('#ats-create-jd').onclick=bindErrors(()=>changeView('create'));
$$('[data-view]').forEach(button=>button.onclick=bindErrors(()=>changeView(button.dataset.view)));
host.addEventListener('change',bindErrors(async event=>{if(event.target.id==='ats-job-select')await selectJob(event.target.value);}));
host.addEventListener('click',bindErrors(async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.openJob){state.view='pipeline';await selectJob(button.dataset.openJob);}
  else if(button.id==='ats-refresh'){await loadJobs();await loadSelected();await render();notice('Workspace refreshed.');}
  else if(button.id==='ats-cancel-edit')await changeView('dashboard');
  else if(button.dataset.stage){state.stage=button.dataset.stage;pipeline();}
  else if(button.dataset.move)candidateAction(button.dataset.move,'move');
  else if(button.dataset.reject)candidateAction(button.dataset.reject,'reject');
  else if(button.dataset.feedback)candidateAction(button.dataset.feedback,'feedback');
  else if(button.dataset.journey)await journey(button.dataset.journey);
  else if(button.dataset.outcome){const item=rows(state.pipeline).find(r=>String(r.id)===button.dataset.link);if(item)placementAction(item,button.dataset.outcome);}
  else if(button.dataset.atsHistoryPage)await viewHistory(Number(button.dataset.atsHistoryPage));
  else if(button.dataset.atsJobsPage){state.jobsPage=Number(button.dataset.atsJobsPage);await loadJobs();dashboard();}
  else if(button.dataset.roundUp!==undefined||button.dataset.roundDown!==undefined){captureRounds();const index=Number(button.dataset.roundUp??button.dataset.roundDown);const other=button.dataset.roundUp!==undefined?index-1:index+1;[workflowDraft.rounds[index],workflowDraft.rounds[other]]=[workflowDraft.rounds[other],workflowDraft.rounds[index]];renderWorkflowDraft();}
  else if(button.dataset.roundToggle!==undefined){captureRounds();const round=workflowDraft.rounds[Number(button.dataset.roundToggle)];round.is_active=!round.is_active;renderWorkflowDraft();}
}));
try{await loadJobs();if(state.jobId)await loadSelected();await render();}catch(err){host.innerHTML=empty('Workspace could not be loaded','Check the error above. Reload after the configuration or connection is restored.');error(err);}

function placementButtons(item){
  const closed=item.selection_outcome==='PENDING_JOINING'?`<button class="ats-btn ats-secondary ats-small" data-outcome="NOT_JOINED" data-link="${item.id}" type="button">Not Joined</button><button class="ats-btn ats-danger ats-small" data-outcome="CANCEL" data-link="${item.id}" type="button">Cancel selection</button>`:item.selection_outcome==='JOINED_CONFIRMED'&&!item.eligibility_released_at_utc?`<button class="ats-btn ats-secondary ats-small" data-outcome="REACTIVATE" data-link="${item.id}" type="button">Reactivate for sourcing</button>`:'';
  return `${closed}<button class="ats-btn ats-secondary ats-small" data-v12-email="${item.candidate_id}" data-v12-job="${state.jobId}" type="button">Email preview</button>`;
}
function placementAction(item,action){
  const labels={SELECT:'Confirm company selection',JOIN:'Confirm actual joining',NOT_JOINED:'Record Not Joined',CANCEL:'Cancel company selection',REACTIVATE:'Reactivate for sourcing'};
  const requestKey=key();
  dialog(labels[action],`<p><strong>${esc(item.full_name)}</strong> · ${esc(current().title)}</p>${field('effective_on',action==='JOIN'?'Actual joining date':'Effective date',today(),{type:'date',required:true,max:today()})}${actorField()}${action==='JOIN'?field('confirmation_evidence','Joining confirmation details','',{type:'textarea',required:true}):''}${['NOT_JOINED','CANCEL','REACTIVATE'].includes(action)?field('reason','Reason','',{type:'textarea',required:true}):''}<p class="ats-hint">${action==='JOIN'?'Only an explicit actual joining counts as a placement.':action==='SELECT'?'The candidate remains searchable. New JD allocation will be on hold.':action==='REACTIVATE'?'Requires a supervisor access key. Historical joining and all JD memberships remain unchanged.':'The original selection remains in company and candidate history.'}</p>`,'Confirm & record',async data=>{
    await v12save(`/jobs/${state.jobId}/candidates/${item.id}/outcome`,{...data,action,idempotency_key:requestKey,expected_stage:item.stage_code,workflow_version:state.workflow.workflow_version});
    await loadJobs();await loadSelected();pipeline();notice('Outcome recorded. Company reporting and allocation eligibility are updated.');
  });
}
async function chooseContact(){
  const company=await v12('/companies/'+current().company_id);const requestKey=key();
  if(!company.contacts.length){notice('No contacts are recorded for this company.');return;}
  dialog('Choose company email contact',`${field('contact_id','Company contact',current().company_contact_id||company.contacts[0].id,{choices:company.contacts.map(c=>[c.id,(c.contact_name||'Contact')+' · '+(c.email||'Email not recorded')])})}${actorField()}<p class="ats-hint">The selected contact name and email are recorded as a JD snapshot. Email previews use the current saved contact address.</p>`,'Save contact',async data=>{await v12save(`/jobs/${state.jobId}/contact`,{...data,idempotency_key:requestKey},'PUT');await loadSelected();await renderDetails();notice('Company contact selected and audited.');});
}

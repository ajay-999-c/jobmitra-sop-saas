import {installDirectMovement} from './direct-movement.mjs';
// Presentation and sourcing adapter only. Canonical services own all recruitment facts.
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const closed=new Set(['NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED']);
export function allocation(candidate,job){
 const linked=job.candidates.some(c=>String(c.id)===String(candidate.id))||(candidate.participation||[]).some(p=>String(p.job_id)===String(job.id));
 if(linked)return {allowed:false,label:'Already added',tone:'linked',reason:'Already linked to this JD'};
 if(job.status!=='ACTIVE')return {allowed:false,label:'Not eligible',tone:'unavailable',reason:'Only active JDs accept candidates'};
 if(candidate.is_active===false||candidate.can_allocate!==true)return {allowed:false,label:'Not eligible',tone:'unavailable',reason:({PLACED_LOCKED:'Confirmed joining; not eligible for a new JD',SELECTED_ON_HOLD:'Selected; new JD allocation is on hold'})[candidate.allocation_eligibility]||'Candidate is unavailable for new JD allocation'};
 return {allowed:true,label:'Available',tone:'good',reason:''};
}
export function salaryLabel(person){
 const amount=person.expected_salary_inr;
 if(amount===null||amount===undefined)return 'Not recorded';
 const raw=String(amount),match=raw.match(/^(\d+)(\.\d+)?$/);
 const value=match?BigInt(match[1]).toLocaleString('en-IN')+(match[2]||''):raw;
 const period=({MONTHLY:'month',ANNUAL:'year'})[person.expected_salary_period]||'period not recorded';
 const basis=({CTC:'CTC',GROSS:'gross',IN_HAND:'in hand'})[person.expected_salary_basis]||'basis not recorded';
 return '₹'+value+' / '+period+' · '+basis;
}
export function experienceLabel(person){
 if(Number.isInteger(person.experience_months)&&person.experience_months>=0){const m=person.experience_months;return `${Math.floor(m/12)} yr${m%12?' '+m%12+' mo':''}`;}
 return person.experience_years===null||person.experience_years===undefined?'Not recorded':String(person.experience_years)+' yr';
}
export function linkedRows(context,filter){
 const rows=context.reached(context.stage);
 if(filter==='here')return rows.filter(c=>context.stageOf(c)===context.stage&&!closed.has(context.stageOf(c)));
 if(filter==='selected')return rows.filter(c=>['SELECTED','JOINED'].includes(context.stageOf(c)));
 if(filter==='closed')return rows.filter(c=>closed.has(context.stageOf(c)));
 return rows.slice().sort((a,b)=>{const rank=c=>closed.has(context.stageOf(c))?2:context.stageOf(c)===context.stage&&context.stage!=='JOINED'?0:1;return rank(a)-rank(b);});
}
export function feedbackAtStage(candidate,stage,name){
 const round=stage.startsWith('ROUND:')?stage.slice(6):null,code=round?'ROUND':stage;
 return (candidate.journey||[]).filter(e=>{
  if(!e.feedback?.trim()||['MILESTONE','INTERVIEW_SCHEDULED'].includes(e.type))return false;
  if(e.feedback_stage)return e.feedback_stage.stage_code===code&&(code!=='ROUND'||e.feedback_stage.round_id===round);
  if(code!=='ROUND')return e.fromKey===code||e.toKey===code;
  const id=e.round_id||e.to_round_id||e.from_round_id;
  return id? id===round : [e.fromName,e.toName].includes(name);
 });
}
export function stagePresentation(context,c){
 const key=context.stageOf(c),decision=context.decision(c,context.stage);
 if(closed.has(key))return {tone:'red',label:context.label(c)};
 if(['ADVANCED','COMPLETED'].includes(decision))return {tone:'green',label:'Stage completed'};
 return {tone:'amber',label:'Awaiting action'};
}
export function createPoolAttacher(native){
 const owners=new Map(),pending=new Map();
 return (candidateId,jobId)=>{
  candidateId=String(candidateId);jobId=String(jobId);const key=jobId+':'+candidateId;
  if(pending.has(key))return pending.get(key);
  if(!owners.has(key))owners.set(key,{});
  const promise=(async()=>{
   await native.addToPool(candidateId,jobId,owners.get(key));
   const member=native.jobs.find(j=>String(j.id)===jobId)?.candidates.find(c=>String(c.id)===candidateId);
   if(!member)throw Error('The server has not confirmed this JD membership. Refresh and retry.');
   return member;
  })().finally(()=>pending.delete(key));
  pending.set(key,promise);return promise;
 };
}

export function installCleanJD(native,options){
 installDirectMovement(native,options);
 const root=options.root,states=new Map(),attach=createPoolAttacher(native),busy=new Set();
 const $=id=>root.getElementById(id),context=()=>options.context();
 const state=()=>{const id=String(context().job.id);if(!states.has(id))states.set(id,{mode:'find',filter:'reached',query:'',draftQuery:'',page:1,result:null,loaded:null,snapshot:null,loading:false,ticket:0,error:''});return states.get(id);};
 const active=()=>context().stage==='POOL';
 function render(){options.renderCandidates();}
 function stageChanged(key){const s=state();s.mode=key==='POOL'?'find':'linked';s.filter='reached';s.message='';s.error='';}
 function summary(){
  const {job}=context(),t=options.target(job);
  const node=$('jdTargetSummary');if(!node)return;
  node.className='summary '+t.key;
  node.innerHTML=`<div><span class="label">Created</span><strong>${esc(options.created(job))}</strong></div><div><span class="label">Target date</span><strong>${esc(options.date(job.targetDate))}</strong><small><span class="status ${t.key==='overdue'?'red':t.key==='due'?'amber':t.key==='track'||t.key==='filled'?'green':'neutral'}"><i></i>${esc(t.key==='overdue'?'Overdue':t.label)}</span> · ${esc(t.detail)}</small></div><div><span class="label">Joined / vacancies</span><strong>${options.joined(job)} / ${esc(job.vacancies??'Unknown')}</strong></div>`;
 }
 function workflow(){
  const ctx=context();
  const card=d=>`<button type="button" class="stage ${ctx.stage===d.key?'selected':''} ${d.key==='JOINED'?'joined':''}" data-kind="${d.kind==='standard'?'core':d.kind}" data-stage-filter="${esc(d.key)}" title="${esc(d.name)}" aria-pressed="${ctx.stage===d.key}" aria-label="${esc(d.name)}, ${options.count(d.key)} reached, ${options.awaiting(d.key)} awaiting action"><span class="stage-title">${esc(d.name)}</span><span class="stage-num">${options.count(d.key)}</span><span class="stage-meta"><b>${options.awaiting(d.key)}</b> awaiting action</span></button>`;
  const group=(label,kind)=>{const items=ctx.defs.filter(d=>d.kind===kind);return `<div class="group"><div class="group-label">${label}</div><div class="steps">${items.length?items.map(card).join('<span class="next-arrow" aria-hidden="true">›</span>'):`<p class="workflow-empty">${ctx.job.workflowMode==='UNKNOWN'?'Company interview plan not confirmed':ctx.job.workflowMode==='DIRECT'?'Direct selection · no company interview rounds':'No active company interview rounds'}</p>`}</div></div>`;};
  return `<section class="section workflow" aria-label="Hiring workflow"><div class="section-heading"><h2>Hiring Workflow</h2><span class="hint">Select a stage · cumulative stage reach</span></div><div class="rail">${group('Jobmitra Process','standard')}${group('Company Interview Process','interview')}${group('Hiring Outcomes','outcome')}</div></section>`;
 }
 function tablePeople(items){
  const ctx=context();
  return items.map(c=>{const member=ctx.job.candidates.find(m=>String(m.id)===String(c.id)),a=allocation(c,ctx.job),pending=busy.has(ctx.job.id+':'+c.id),disabled=!a.allowed||ctx.disabled||pending;
   return `<tr><td><div class="candidate"><span class="avatar" aria-hidden="true">${esc(c.full_name.split(/\s+/).map(w=>w[0]).slice(0,2).join(''))}</span><div class="person"><strong>${esc(c.full_name)}</strong><small>${esc(c.job_title||'Job title not recorded')}</small></div></div></td><td data-label="Location">${esc(c.current_city||'Not recorded')}</td><td data-label="Experience">${esc(experienceLabel(c))}</td><td data-label="Expected CTC" class="salary">${esc(salaryLabel(c))}</td><td data-label="Availability"><span class="row-status ${a.tone}">${a.label}${a.reason?`<small>${esc(a.reason)}</small>`:''}</span></td><td>${member?'<button class="btn small" data-clean-open-member="'+c.id+'">Open '+esc(ctx.label(member))+'</button>'+memberActions(member):`<div class="rowactions"><button class="btn small" data-clean-profile="${c.id}">Profile</button><button class="btn add ${disabled?'status':'primary'}" data-clean-add="${c.id}" ${disabled?'disabled':''} title="${esc(ctx.disabled?'Activate/save this JD and workflow before adding candidates':a.reason||'Add to the selected JD')}">${pending?'Adding…':a.label==='Already added'?'Already added':!a.allowed?'Not eligible':'+ Add to this JD'}</button></div>`}</td></tr>`;
  }).join('');
 }
 function memberActions(c){
  const ctx=context(),key=ctx.stageOf(c),next=ctx.next(c),canAct=!ctx.disabled&&!closed.has(key)&&key!=='JOINED'&&key===ctx.stage;
  return `<div class="rowactions"><button class="btn small" data-clean-profile="${c.id}">Profile</button>${ctx.canEmail(key)?`<button class="btn small" data-compose-candidate-email="${c.id}">Email</button>`:''}${!ctx.disabled?`<button class="btn small" data-feedback-candidate="${c.id}">Feedback</button>${canAct&&key.startsWith('ROUND:')?`<button class="btn small" data-schedule-interview="${c.id}">Interview</button>`:''}`:''}${key==='SELECTED'&&canAct?`<button class="btn primary" data-confirm-joined="${c.id}">Confirm joining</button><button class="btn small" data-mark-not-selected="${c.id}">Close selection</button>`:''}${canAct&&next?`<button class="btn primary" data-move-next="${c.id}" title="Next: ${esc(options.stageName(next))}">Next Stage →</button>`:''}${canAct?`<button class="btn small" data-direct-stage="${c.id}">Move to Stage</button>`:''}${canAct&&key!=='SELECTED'?`<button class="btn small" data-mark-not-selected="${c.id}">Not Selected</button>`:''}${['SELECTED','JOINED'].includes(key)?'<button class="btn small" data-goto-view="placement">Placement</button>':''}</div>`;
 }
 function tableMembers(items){
  const ctx=context();
  return items.map(c=>{
   const key=ctx.stageOf(c),next=ctx.next(c),canAct=!ctx.disabled&&!closed.has(key)&&key!=='JOINED'&&key===ctx.stage;
   const feedback=feedbackAtStage(c,ctx.stage,options.stageName(ctx.stage))[0],person=native.people.find(p=>p.id===c.id),presentation=stagePresentation(ctx,c),status=presentation.tone;
   const decisionText=presentation.label;
   const rejection=key==='NOT_SELECTED'&&c.rejection?'Not Selected at '+(c.rejection.stageKey==='ROUND'?c.rejection.stageName:options.stageName(c.rejection.stageKey))+' · '+c.rejection.at:'';
   return `<tr><td><div class="person"><strong>${esc(c.name)}</strong><small>${esc(person?.title||'')}</small></div></td><td data-label="Current status"><span class="row-status ${status}">${esc(decisionText)}<small>Current: ${esc(ctx.label(c))}</small></span>${canAct&&next?`<small class="next-destination">Next: ${esc(options.stageName(next))}</small>`:''}</td><td data-label="Latest feedback"><span>${esc(feedback?.feedback||'No feedback recorded at this stage')}</span>${rejection?`<small class="next-destination">Rejection: ${esc(rejection)}</small>`:''}</td><td>${memberActions(c)}</td></tr>`;
  }).join('');
 }
 function panel(host){
  if(!host)return;const ctx=context(),s=state(),pool=ctx.stage==='POOL',find=pool;
  const result=s.result||{items:[],total:0,page:s.page,page_size:10};
  const members=linkedRows(ctx,s.filter),pages=Math.max(1,Math.ceil(result.total/result.page_size));
  host.innerHTML=`<section class="section pipeline" aria-label="Candidate pipeline"><div class="pipeline-top"><div><h2>${esc(options.stageName(ctx.stage))}</h2><p>${pool?'Find candidates and add them directly to this JD.':'Review candidates and move them through this requirement.'}</p></div><div class="pipeline-actions"><span class="muted">${ctx.job.candidates.length} linked candidates</span>${!find?`<label class="sr-only" for="cleanStageFilter">Filter linked candidates</label><select id="cleanStageFilter">${[['reached','All reached'],['here','At this stage'],['selected','Selected / Joined'],['closed','Not Selected / Not Joined']].map(([v,t])=>`<option value="${v}" ${v===s.filter?'selected':''}>${t}</option>`).join('')}</select>`:''}</div></div>
  ${s.error?`<p class="clean-message error" role="alert">${esc(s.error)}</p>`:''}${s.message?`<p class="clean-message" role="status">${esc(s.message)}</p>`:''}
  ${find?`<form class="search-area" id="cleanSearchForm"><div class="searchfield"><label class="sr-only" for="cleanCandidateQuery">Search candidate database</label><svg viewBox="0 0 24 24" fill="none" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-4-4"></path></svg><input id="cleanCandidateQuery" type="search" maxlength="500" placeholder="Search by name, mobile, job title or skills" value="${esc(s.draftQuery)}" autocomplete="off"></div><button class="btn primary" type="submit">Search</button><button class="btn text" type="button" data-clean-clear>Clear</button></form><div class="results-header" aria-live="polite"><b>${s.loading?'Searching…':result.total+' matching candidates'}</b><span>Canonical candidate database</span></div><div class="table-wrap"><table class="candidate-table"><thead><tr><th>Candidate</th><th>Location</th><th>Experience</th><th>Expected CTC</th><th>Availability</th><th class="align-right">Action</th></tr></thead><tbody>${tablePeople(result.items)}</tbody></table></div>${!s.loading&&!result.items.length?'<div class="empty"><strong>No matching candidates</strong>Try another name, mobile, role, skill or location.</div>':''}<div class="list-end"><span>${result.total?'Showing '+((s.page-1)*result.page_size+1)+'–'+Math.min(s.page*result.page_size,result.total)+' of '+result.total:'0 candidates'}</span><span><button class="btn small" data-clean-page="-1" ${s.page<=1||s.loading?'disabled':''}>‹ Prev</button> <span>Page ${s.page} of ${pages}</span> <button class="btn small" data-clean-page="1" ${s.page>=pages||s.loading?'disabled':''}>Next ›</button></span></div>`:
  `<div class="results-header"><b>${members.length} candidates</b><span>${s.filter==='here'?'Currently at this stage':s.filter==='reached'?'Includes previously advanced candidates':'Filtered candidate history'}</span></div>${ctx.stage==='COMPANY_SUBMISSION'?'<div class="clean-batch"><button class="btn primary small" data-compose-submission id="composeBatchBtn" disabled>✉ Compose submission (0)</button></div>':''}<div class="table-wrap"><table class="candidate-table"><thead><tr><th>Candidate</th><th>Current status</th><th>Latest feedback</th><th class="align-right">Actions</th></tr></thead><tbody>${tableMembers(members)}</tbody></table></div>${!members.length?'<div class="empty"><strong>No candidates in this view</strong>Select All reached to view historical participation.</div>':''}`}</section>`;
  if(!find&&ctx.stage==='COMPANY_SUBMISSION')host.querySelectorAll('tbody tr').forEach((row,i)=>{const cell=row.querySelector('td');const box=document.createElement('input');box.type='checkbox';box.dataset.submissionSelect=members[i].id;box.setAttribute('aria-label','Include '+members[i].name+' in candidate submission email');cell.prepend(box);});
  if(find){const key=JSON.stringify([s.query,s.page]);if((s.loaded!==key||s.snapshot!==native.snapshot)&&!(s.loading&&s.requested===key&&s.requestSnapshot===native.snapshot))void load();}
 }
 async function load(){
  const s=state(),jobId=context().job.id,ticket=++s.ticket,key=JSON.stringify([s.query,s.page]),snapshot=native.snapshot;
  s.loading=true;s.requested=key;s.requestSnapshot=snapshot;s.error='';render();
  try{
   const data=await native.api('/api/v12/approved/search?'+new URLSearchParams({keywords:s.query,identity_lookup:'true',match:'ALL',sort:'recent',page:s.page,page_size:10}));
   if(ticket!==s.ticket)return;s.result=data;s.loaded=key;s.snapshot=snapshot;
  }catch(error){if(ticket===s.ticket){s.error=error.message;s.loaded=key;s.snapshot=snapshot;}}
  finally{if(ticket===s.ticket){s.loading=false;if(String(context().job.id)===String(jobId)&&active())render();}}
 }
 root.addEventListener('input',event=>{if(event.target.id==='cleanCandidateQuery')state().draftQuery=event.target.value;});
 root.addEventListener('submit',event=>{if(event.target.id==='cleanSearchForm'){event.preventDefault();const s=state();s.query=s.draftQuery;s.page=1;s.message='';void load();}});
 root.addEventListener('change',event=>{if(event.target.id==='cleanStageFilter'){state().filter=event.target.value;render();}});
 root.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;const d=button.dataset,s=state();
  if(d.cleanOpenMember){native.openMembership(d.cleanOpenMember,context().job.id);return;}
  if(d.cleanClear!==undefined){s.query='';s.draftQuery='';s.page=1;s.message='';void load();return;}
  if(d.cleanPage){s.page+=Number(d.cleanPage);void load();return;}
  if(d.cleanProfile){void native.run(async()=>{if(!native.people.some(c=>c.id===d.cleanProfile))await native.refresh();window.JobmitraUnified.openCandidate(d.cleanProfile);},options.toast);return;}
  if(d.cleanAdd){
   const ctx=context(),jobId=ctx.job.id,candidate=s.result?.items.find(c=>String(c.id)===d.cleanAdd),key=jobId+':'+d.cleanAdd;
   if(!candidate||ctx.disabled||!allocation(candidate,ctx.job).allowed||busy.has(key))return;
   busy.add(key);s.error='';s.message='';render();
   void attach(d.cleanAdd,jobId).then(()=>{s.message='JD membership confirmed at its current stage.';s.loaded=null;options.toast(s.message);}).catch(error=>{s.error=error.message;}).finally(()=>{busy.delete(key);if(context().job.id===jobId)render();});
  }
 });
 return {summary,workflow,panel,stageChanged,feedbackHistory:(c,key)=>feedbackAtStage(c,key,options.stageName(key))};
}

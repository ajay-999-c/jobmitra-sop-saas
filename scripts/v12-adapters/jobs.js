function persist(){/* Unsaved editor state is memory-only. Service adapters own persistence. */}
function resetDemo(){native.run(async()=>{await native.refresh();toast('Canonical records reloaded. No data was reset.');},toast);}
async function saveDetails(){
 const form=el('jdForm');
 return submitCreation(form,'jd',async submission=>{
  const errors=nativeFieldErrors(form),error=validateDetails();
  if(error&&!errors.length){
   const field=/company/i.test(error)?'company':/title/i.test(error)?'title':/date/i.test(error)?'targetDate':/vacancies/i.test(error)?'vacancies':/experience/i.test(error)?(/Maximum/i.test(error)?'experienceMax':'experienceMin'):/salary/i.test(error)?(/Maximum/i.test(error)?'salaryMax':'salaryMin'):'';
   errors.push({field,message:error});
  }
  if(!submission.validate(errors))return;
  await native.authorize();
  const number=v=>v===''||v==null?null:Number(v),body={company_id:draft.companyId,assigned_recruiter_id:draft.recruiterId||null,...(!isNew?{expected_revision:draft.revision}:{}),title:draft.title,target_date:draft.targetDate||null,company_contact:draft.companyContact||null,location:draft.location||null,work_mode:draft.workMode||null,vacancies:number(draft.vacancies),status:draft.status,skills:String(draft.skills||'').split(',').map(s=>s.trim()).filter(Boolean),experience_min:number(draft.experienceMin),experience_max:number(draft.experienceMax),qualification:draft.qualification||null,salary_min_inr:number(draft.salaryMin),salary_max_inr:number(draft.salaryMax),salary_period:draft.salaryPeriod||null,salary_basis:draft.salaryBasis||'UNKNOWN',requirement_notes:draft.notes||null,full_jd:draft.fullJD||null};
  const result=await submission.request(native,'/api/ats-v2/jobs'+(isNew?'':'/'+draft.id),body,isNew?'POST':'PATCH');
  selectedId=String(result.id);draft.id=selectedId;isNew=false;
  const contacts=native.companies.find(c=>c.id===body.company_id)?.contacts||[],contact=contacts.find(c=>c.id===body.company_contact);
  if(contact)await submission.request(native,'/api/v12/jobs/'+result.id+'/contact',{contact_id:contact.id,actor_name:native.actor,idempotency_key:native.key(form,'contact:'+result.id+':'+contact.id)},'PUT');
  await native.refresh();view='details';render();toast('JD details saved.');
 });
}
function reviewWorkflow(){if(isNew)return toast('Save JD details first.');if(!workflowDirty())return toast('No workflow changes to save.');const error=validateWorkflow();if(error)return toast(error);showModal({title:'Review workflow changes',description:`${draft.id} · Saving will create workflow version ${draft.workflowVersion+1}`,items:[...diffSummary(),{title:'Candidate impact policy',text:`${impact().impacted.length} may see inserted rounds in future. ${impact().manuallyReview.length} require order review. No candidate is moved automatically.`},{title:'History protection',text:'Stable stage IDs and historical events remain intact.'}],confirmLabel:'Save workflow version',onConfirm:()=>native.run(async()=>{await native.authorize();const owner=el('confirmModal');await native.api(`/api/ats-v2/jobs/${draft.id}/workflow`,{workflow_mode:draft.workflowMode,workflow_version:draft.workflowVersion,rounds:draft.rounds.map(r=>({id:r.history?r.id:null,round_name:r.name,mode:r.mode,is_active:r.active}))},'PUT',owner);closeModal();await native.refresh();render();toast('Workflow version saved. Candidate stages were preserved.');},toast)});}
async function confirmCandidateAction(){return native.run(async()=>{if(!modalAction)return;const {candidateId,action,next}=modalAction,c=draft.candidates.find(c=>c.id===candidateId),owner=el('confirmCandidateAction');if(!c)throw Error('Candidate membership is unavailable.');await native.authorize();const feedback=(el('candidateFeedback')?.value||'').trim(),feedback_source=({'Company':'COMPANY','Jobmitra':'JOBMITRA','Candidate':'CANDIDATE'})[el('feedbackSource')?.value]||'NOT_SPECIFIED';if(action!=='note'&&modalAction.viewStage!==stageOf(c))throw Error('Choose the current stage before changing this candidate.');if(action==='note'){if(!feedback)throw Error('Enter feedback before saving.');await native.api(`/api/ats-v2/jobs/${draft.id}/candidates/${c.linkId}/feedback`,{feedback,feedback_source,stage_code:modalAction.viewStage.startsWith('ROUND:')?'ROUND':modalAction.viewStage,round_id:modalAction.viewStage.startsWith('ROUND:')?modalAction.viewStage.slice(6):null},'POST',owner);}else if(next==='SELECTED'){await native.outcome(draft,c,'SELECT',owner,feedback,feedback_source);}else if(action==='reject'&&c.selectionOutcome==='PENDING_JOINING'){const kind=prompt('Close selection: NOT_JOINED or CANCEL','NOT_JOINED');if(!['NOT_JOINED','CANCEL'].includes(kind))throw Error('No selection closure recorded.');await native.outcome(draft,c,kind,owner,feedback,feedback_source);}else{const stage=action==='reject'?'NOT_SELECTED':next;await native.api(`/api/ats-v2/jobs/${draft.id}/candidates/${c.linkId}/move`,{stage_code:stage.startsWith('ROUND:')?'ROUND':stage,round_id:stage.startsWith('ROUND:')?stage.slice(6):null,feedback:feedback||null,feedback_source,expected_stage:c.stageCode,expected_round_id:c.stageId||null,workflow_version:draft.workflowVersion},'POST',owner);}closeModal();await native.refresh();render();toast('Saved. Candidate and JD history reloaded from the server.');},toast);}
async function confirmJoined(cid){return native.run(async()=>{const c=draft.candidates.find(c=>c.id===cid);if(!c)throw Error('Candidate membership is unavailable.');await native.outcome(draft,c,'JOIN',{});await native.refresh();render();toast('Actual joining confirmed. Placement reporting uses the joining date.');},toast);}
function joinedAt(c){return c.joinedOn?c.joinedOn+'T12:00:00+05:30':null;}
function recordJDEvent(){throw Error('A canonical service must record the action before reporting success.');}
function renderDashboard(){
 native.jdDashboard ||= installJDDashboard(native,{root:jdShadow,target:targetState,created:createdDate,date:dateLabel,open:id=>native.run(async()=>{await native.refresh();switchJob(String(id));view='pipeline';stageFilter='ALL';render();},toast)});
 return native.jdDashboard.render();
}
function cleanJD(){
 native.jdClean ||= installCleanJD(native,{root:jdShadow,
  context:()=>({job:draft,stage:stageFilter,defs:stageDefs(),disabled:isNew||draft.status!=='ACTIVE'||workflowDirty(),reached:stageRows,stageOf,decision:stageDecision,next:nextStageKey,label:c=>candidateStage(c),feedback:c=>(c.journey||[]).find(e=>e.feedback?.trim()&&!['MILESTONE','INTERVIEW_SCHEDULED'].includes(e.type)),canEmail:canComposePipelineEmail}),
  renderCandidates:renderPipelineCandidates,target:targetState,created:createdDate,date:dateLabel,joined:countJoined,count:stageCount,awaiting:stagePending,stageName,toast});
 return native.jdClean;
}
function header(){
 const hasJob=!!selectedId&&!isNew;
 el('jdSelectedHeader').hidden=!hasJob||view==='dashboard';
 el('heroTitle').textContent=draft.title||'';
 el('heroSubtitle').textContent=(draft.company||'Company not selected')+' · '+(draft.location||'Location not set');
 el('jdRecruiter').textContent=(draft.recruiterName||'Unassigned')+(draft.recruiterActive===false?' (Inactive)':'');
 el('statusPill').className='status '+({ACTIVE:'green',ON_HOLD:'amber',CLOSED:'red'}[draft.status]||'neutral');
 el('statusPill').textContent=({ACTIVE:'Active',DRAFT:'Draft',ON_HOLD:'On hold',CLOSED:'Closed'})[draft.status]||'Draft';
 el('topSaveBtn').hidden=true;
 for(const [id,value] of Object.entries({navDashboard:'dashboard',navDetails:'details',navWorkflow:'workflow',navPipeline:'pipeline',navPlacement:'placement',navHistory:'history'})){
  const node=el(id);node.disabled=id!=='navDashboard'&&!hasJob;node.classList.toggle('active',view===value);node.setAttribute('aria-current',view===value?'page':'false');
 }
 el('jdSwitch').hidden=!hasJob||view==='dashboard';
 el('newJobBtn').hidden=view==='dashboard'||isNew;el('newJobBtn').parentElement.hidden=el('newJobBtn').hidden;
 el('jdSidebarContext').textContent=hasJob&&view!=='dashboard'?(draft.code||'JD '+draft.id):'Select a JD to manage its pipeline.';
 renderJobPicker();renderDateSummary();
}
function headerNoRerender(){header();}
function renderDateSummary(){el('jdTargetSummary').hidden=isNew||view==='dashboard';cleanJD().summary();}
function workflowNavigator(){return '<div class="jd-clean">'+cleanJD().workflow()+'</div>';}
function renderPipeline(){
 if(!stageDefs().some(d=>d.key===stageFilter)){stageFilter='POOL';cleanJD().stageChanged(stageFilter);}
 el('workspace').innerHTML='<div class="jd-clean">'+cleanJD().workflow()+'<div id="pipelineCandidateList"></div></div>';
 renderPipelineCandidates();
}
function renderPipelineCandidates(){cleanJD().panel(el('pipelineCandidateList'));}
function selectStage(key){stageFilter=key;cleanJD().stageChanged(key);view='pipeline';render();}
function nextStageKey(c){
 if(['SELECTED','JOINED','NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED'].includes(stageOf(c)))return null;
 return c.nextStage==='ROUND'?(c.nextRoundId?'ROUND:'+c.nextRoundId:null):c.nextStage||null;
}
function switchJob(id){
 if(!abandonIfDirty())return;const j=state.jobs.find(x=>x.id===id);if(!j)return;
 selectedId=id;isNew=false;draft=clone(j);stageFilter='POOL';view='pipeline';fullJDOpen=false;cleanJD().stageChanged('POOL');persist();render();
}

function showCandidateAction(id,action){
      if(isNew)return toast('Create the JD before editing candidate journeys.','error');
       if(!engagementActive())return toast('Set JD status to Active before updating candidates.','error');
      if(workflowDirty())return toast('Save the workflow changes before updating candidates.','error');
      const c=draft.candidates.find(x=>x.id===id);if(!c)return;
      if(action==='reject'&&['JOINED','NOT_SELECTED'].includes(stageOf(c)))return toast('Closed journey cannot be rejected again.','error');
      if(action!=='note'&&stageFilter!==stageOf(c))return toast('Choose the current stage before changing this candidate.','error');
      const next=action==='advance'?nextStageKey(c):null;
      if(action==='advance'&&!next)return toast('No next configured stage available.','error');
      modalAction={candidateId:id,action,next,viewStage:stageFilter};
      const heading=action==='reject'?'Mark candidate Not Selected':action==='advance'?'Move candidate to next stage':'Record feedback / recruiter note';
      const dest=action==='reject'?'Not Selected':action==='advance'?stageName(next):stageName(stageFilter);
      const helper=action==='note'?'This feedback is recorded at the selected stage. It does not move or reopen the candidate.':'Feedback is optional. Saving creates a separate JD event and candidate journey record.';
      el('modalHost').innerHTML=`<div class="modal-shade" role="presentation"><div class="modal action-dialog" role="dialog" aria-modal="true" aria-label="${esc(heading)}"><div class="modal-header"><h3>${esc(heading)}</h3><p>${esc(c.name)} · ${esc(draft.id)}</p></div><div class="modal-body"><div class="action-context"><strong>Current stage:</strong> ${esc(candidateStage(c))}<br/><strong>${action==='note'?'Feedback recorded at':'Change to'}:</strong> ${esc(dest)}</div>${action==='note'?`<details><summary>Recorded feedback at ${esc(dest)}</summary>${cleanJD().feedbackHistory(c,stageFilter).map(e=>'<p>'+esc(e.feedback)+' · '+esc(e.at)+'</p>').join('')||'<p>No feedback recorded at this stage.</p>'}</details>`:''}<div class="action-subheading">Feedback / notes ${action==='note'?'*':'(optional)'}</div><textarea class="control action-feedback" id="candidateFeedback" maxlength="1500" placeholder="Example: Client confirmed strong technical knowledge; proceed to next round. Or: Not selected due to missing practical experience."></textarea><div class="action-hint">${esc(helper)}</div><div class="field" style="margin-top:15px"><label for="feedbackSource">Feedback source (optional)</label><select class="control" id="feedbackSource"><option value="Not specified">Not specified</option><option value="Company">Company / Interviewer</option><option value="Jobmitra">Jobmitra Screening</option><option value="Candidate">Candidate</option></select></div>${action==='reject'?'<div class="review-tip" style="margin-top:15px">The rejection stage is recorded as a permanent snapshot. Even if interview rounds are renamed later, history stays accurate.</div>':''}</div><div class="modal-footer"><button class="btn secondary" id="cancelModal">Cancel</button><button class="btn ${action==='reject'?'danger':'primary'}" id="confirmCandidateAction">${action==='note'?'Save feedback':action==='reject'?'Save & Mark Not Selected':'Save & Move to Next Stage'}</button></div></div></div>`;
      el('candidateFeedback')?.focus();
    }

function emailContextForCandidate(c,kind){
      const stage=stageDefs().some(d=>d.key===stageFilter)?stageFilter:stageOf(c),roundId=stage.startsWith('ROUND:')?stage.slice(6):null;
      const status=kind||(
        stage==='COMPANY_SUBMISSION'?'candidate_submission':
        stage==='SELECTED'?'selected':stage==='JOINED'?'joined':stage==='NOT_SELECTED'?'not_selected':
        stage.startsWith('ROUND:')?(stageName(stage).toLowerCase().includes('final')?'final_completed':stageName(stage).toLowerCase().includes('technical')?'technical_interview':'interview_scheduled'):
        'interview_scheduled');
      const master=emailCandidateData(c);
      const interview=(c.journey||[]).find(e=>e.type==='INTERVIEW_SCHEDULED'&&e.scheduledAt&&e.round_id===roundId);
      let interviewDate='',interviewTime='';
      if(interview){
        const d=new Date(interview.scheduledAt);
        if(!Number.isNaN(+d)){
          const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(d);
          const v=k=>parts.find(p=>p.type===k)?.value||'';
          interviewDate=`${v('year')}-${v('month')}-${v('day')}`;interviewTime=`${v('hour')}:${v('minute')}`;
        }
      }
      return {status,viewStage:stage,jobId:draft.id,jobTitle:draft.title,companyName:draft.company,location:draft.location||'',candidateName:master.name,candidateEmail:window.JobmitraUnifiedCandidate?.getCandidateById?.(c.id)?.email||'',companyContacts:window.JobmitraUnifiedCompanies?.getContacts?.(draft.companyId)||[],roundId,interviewDate,interviewTime,candidates:[master],startSerial:1};
    }

function composeSubmissionBatch(){
      if(isNew||!selectedId)return toast('Choose a saved JD first.','error');
      // Pending at the Company Submission stage are initial suggestions; operator can edit the batch in the studio.
      const ids=[...document.querySelectorAll('[data-submission-select]:checked')].map(x=>x.dataset.submissionSelect);
      const list=draft.candidates.filter(c=>ids.includes(c.id));
      if(!list.length)return toast('Select one or more candidates from this stage first.','error');
      const contacts=window.JobmitraUnifiedCompanies?.getContacts?.(draft.companyId)||[];
      const base={status:'candidate_submission',viewStage:'COMPANY_SUBMISSION',jobId:draft.id,jobTitle:draft.title,companyName:draft.company,location:draft.location||'',companyContacts:contacts,candidates:list.map(emailCandidateData),startSerial:1};
      window.JobmitraUnified?.openEmailStudio?.(base);
    }

function newJD(){
 if(!abandonIfDirty())return;
 stageFilter='POOL';isNew=true;selectedId=null;draft={...native.emptyJD(),status:'ACTIVE'};
 view='details';fullJDOpen=false;render();
}

function renderDetails(){
 const select=(label,id,name,values,value)=>`<div class="field"><label for="${id}">${label}</label><select class="control" id="${id}" name="${name}">${options(value,values)}</select></div>`;
 el('workspace').innerHTML=`<div class="jd-editor"><div class="row between titlebar"><h2>${isNew?'Create JD':'Edit JD'}</h2><button type="button" class="btn secondary" data-goto-view="${isNew?'dashboard':'pipeline'}">${isNew?'Back to dashboard':'Back to pipeline'}</button></div>
 <form id="jdForm" novalidate><section class="panel"><div class="formgroup"><h3>Basic information</h3><div class="formgrid" style="margin-top:15px">
 <div class="field"><label for="f_company">Company *</label><select class="control" id="f_company" name="company" required>${options(draft.companyId,[['','Choose an existing company'],...native.companies.filter(c=>c.active).map(c=>[c.id,c.name])])}</select></div>
 ${valueInput('Job title / working title','title',{placeholder:'e.g. Accounts Executive',required:true})}
 ${valueInput('JD target date','targetDate',{type:'date',required:true})}
 ${valueInput('Work location','location',{placeholder:'e.g. Indore'})}
 ${valueInput('Vacancies','vacancies',{placeholder:'Not set',type:'number',min:1,step:1})}
 ${select('JD status','f_status','status',[['DRAFT','Draft'],['ACTIVE','Active'],['ON_HOLD','On hold'],['CLOSED','Closed']],draft.status)}
 ${select('Assigned Recruiter','f_recruiterId','recruiterId',[['','Unassigned'],...(native.employees||[]).filter(e=>e.active||e.id===draft.recruiterId).map(e=>[e.id,e.name+(e.active?'':' (Inactive)')])],draft.recruiterId)}
 ${select('Work mode','f_workMode','workMode',[['','Not specified'],['ONSITE','Office / On-site'],['HYBRID','Hybrid'],['REMOTE','Remote']],draft.workMode)}
 ${valueInput('Company contact (optional)','companyContact',{placeholder:'Contact name or saved contact ID'})}
 <div class="field"><label for="f_createdAt">JD creation date · automatic</label><input class="control" id="f_createdAt" readonly value="${esc(isNew?'Automatic on save':createdDate(draft))}"></div>
 </div></div>
 <details class="group" ${isNew?'':'open'}><summary>Requirements <small>· Optional</small></summary><div class="formgroup formgrid"><div class="field"><label for="f_notes">Requirement / company notes</label><textarea class="control" id="f_notes" name="notes" maxlength="20000">${esc(draft.notes)}</textarea></div>${valueInput('Key skills · comma separated','skills')}${valueInput('Minimum experience (years)','experienceMin',{type:'number',min:0,step:.5})}${valueInput('Maximum experience (years)','experienceMax',{type:'number',min:0,step:.5})}${valueInput('Qualification (optional)','qualification')}</div></details>
 <details class="group" ${isNew?'':'open'}><summary>Salary Budget <small>· Optional</small></summary><div class="formgroup formgrid"><div class="field"><label>Salary period</label><div class="segmented"><button type="button" class="segment ${draft.salaryPeriod==='MONTHLY'?'active':''}" data-salary-period="MONTHLY">Monthly</button><button type="button" class="segment ${draft.salaryPeriod==='ANNUAL'?'active':''}" data-salary-period="ANNUAL">Annual</button></div></div>${select('Salary basis','f_salaryBasis','salaryBasis',[['UNKNOWN','Not specified'],['CTC','CTC / Total package'],['GROSS','Gross'],['IN_HAND','In-hand']],draft.salaryBasis)}<div></div>${valueInput('Minimum salary (₹)','salaryMin',{type:'number',min:0,step:1})}${valueInput('Maximum salary (₹)','salaryMax',{type:'number',min:0,step:1})}</div></details>
 <button class="full-jd-toggle" type="button" id="toggleFullJD">Full Job Description · Optional ${fullJDOpen?'−':'+'}</button><div id="fullJDContent" class="full-jd-content ${fullJDOpen?'':'hidden'}"><div class="field"><label for="f_fullJD">Paste detailed JD if available</label><textarea class="control" id="f_fullJD" name="fullJD" maxlength="100000">${esc(draft.fullJD)}</textarea></div></div></section>
 <div class="savebar"><span class="grow muted" id="detailsDirtyLabel"></span><button type="button" class="btn secondary" id="discardDetails">Discard</button><button type="submit" class="btn primary">${isNew?'Create JD':'Save JD Details'}</button></div></form></div>`;
 updateDetailsPreview();
}

function renderHistory(){
 const filter=state.activityFilter||'ALL';
 const groups={MOVED:'Movement',FEEDBACK:'Feedback',INTERVIEW_SCHEDULED:'Interview',EMAIL:'Email',JD_CREATED:'JD details',JD_UPDATED:'JD details',JD_RECRUITER_ASSIGNED:'JD details',JD_WORKFLOW_UPDATED:'Workflow',ROUND_ADDED:'Workflow',ROUND_UPDATED:'Workflow',ROUND_RETIRED:'Workflow'};
 const names={MOVED:'Stage advanced',ADDED:'Added to JD Pool',JD_RECRUITER_ASSIGNED:'Recruiter assignment changed',JD_CREATED:'JD created',JD_UPDATED:'JD details updated',JD_WORKFLOW_UPDATED:'Interview rounds updated'};
 const events=draft.events.filter(e=>filter==='ALL'||(groups[e.type]||e.type)===filter);
 el('workspace').innerHTML=`<section class="panel timeline"><div class="toolbar"><h2>JD Activity</h2><span class="grow"></span><label>Activity type <select class="control" id="jdActivityFilter">${options(filter,[['ALL','All activity'],...['Movement','Feedback','Interview','Email','JD details','Workflow','Placement'].map(x=>[x,x])])}</select></label></div>${events.map(e=>`<div class="event"><div class="muted compact"><time>${esc(e.at||e.time)}</time></div><div><strong>${esc(names[e.type]||e.type)}</strong><details><summary>Details</summary><pre>${esc(e.info||e.feedback||'Recorded event')}</pre></details></div></div>`).join('')||'<div class="empty">No matching activity</div>'}</section>`;
 el('jdActivityFilter').onchange=e=>{state.activityFilter=e.target.value;renderHistory();};
}

function renderImpact(){
 const dirty=workflowDirty(),label=el('workflowDirtyLabel');
 if(label){label.textContent=dirty?'Unsaved workflow changes':'✓ Workflow configuration saved';label.className=dirty?'unsaved':'saved';}
 const discard=document.querySelector('[data-undo-workflow]'),review=document.querySelector('[data-review-workflow]');
 if(discard)discard.disabled=!dirty;if(review)review.disabled=!dirty||isNew;
}

function renderWorkflow(){
 const active=activeRounds(),retired=archivedRounds(),mode=draft.workflowMode,used=draft.rounds.some(r=>r.history||isCurrentlyAssigned(r.id));
 const presets=`<div class="row presetrow">${[1,2,3].map(n=>`<button type="button" class="btn secondary small" data-preset="${n}" ${used?'disabled title="Saved round history must be preserved; add or rename individual rounds"':''}>${n===1?'＋ 1 round':n+' rounds'}</button>`).join('')}</div>`;
 const round=(r,i)=>`<div class="roundrow"><strong>${i+1}</strong><input class="control" aria-label="Stage ${i+1} name" maxlength="80" data-round-name="${esc(r.id)}" value="${esc(r.name)}"><select class="control" aria-label="Stage ${i+1} typical interview mode" data-round-mode="${esc(r.id)}">${options(r.mode,[['FLEXIBLE','Flexible'],['FACE_TO_FACE','Face-to-Face'],['VIDEO','Video / Online'],['PHONE','Phone']])}</select><div class="row"><button class="btn secondary small" type="button" data-add-at="${i}" aria-label="Insert an interview round at position ${i+1}" title="Insert before" ${active.length>=15?'disabled':''}>＋</button><button class="btn secondary small" type="button" data-move-up="${esc(r.id)}" aria-label="Move ${esc(r.name)} up" ${i===0?'disabled':''}>↑</button><button class="btn secondary small" type="button" data-move-down="${esc(r.id)}" aria-label="Move ${esc(r.name)} down" ${i===active.length-1?'disabled':''}>↓</button><button class="btn secondary small" type="button" data-remove-stage="${esc(r.id)}" ${isCurrentlyAssigned(r.id)?'disabled title="A candidate is currently at this round"':'title="Remove from the active plan; saved history is retained"'}>Remove</button></div></div>`;
 el('workspace').innerHTML=`<div class="workflow-form"><section class="panel"><div class="formgroup workflow-top"><div class="row between"><h2>Add / Remove Interview Rounds</h2><span class="locked-label">${svg('lock',12)} Standard process locked</span></div><p class="sub">Modify interview rounds without changing JD details or candidate results.</p></div>
 <div class="formgroup"><h3 class="workflow-heading"><span class="stepnum">01</span> Standard Jobmitra Process</h3><div class="standard-flow">${standard.map(s=>`<div class="flow-step"><span class="flow-icon">${svg(s[1],22)}</span><strong>${esc(s[0])}</strong><small>${esc(s[2])}</small></div>`).join('')}</div></div>
 <div class="formgroup"><div class="row between"><h3 class="workflow-heading"><span class="stepnum purple">02</span> Company Interview Process</h3><span class="round-count">${mode==='CONFIGURED'?active.length:0} rounds</span></div><p class="sub workflow-help">Add, rename or reorder company interview rounds.</p><div class="field plan-field"><label for="workflowMode">Interview plan status</label><select class="control" id="workflowMode">${options(mode,[['UNKNOWN','Not confirmed yet'],['DIRECT','Direct selection · no interview'],['CONFIGURED','Custom / configured interview rounds']])}</select></div>
 ${mode==='UNKNOWN'?'<div class="plan-empty"><strong>Interview plan not confirmed</strong><p>Start sourcing candidates now. Configure rounds when the client shares the process.</p></div>'+presets:mode==='DIRECT'?'<div class="plan-empty"><strong>Direct selection · no interview</strong><p>Company Submission is followed by Selected by Company.</p></div>'+presets:presets+'<div class="round-list">'+active.map(round).join('')+'</div><div style="margin-top:14px"><button class="btn secondary" type="button" data-add-at="'+active.length+'" '+(active.length>=15?'disabled':'')+'>＋ Add final round</button></div>'}
 ${retired.length?`<details class="group" style="margin-top:15px"><summary>Retired rounds · kept for history</summary>${retired.map(r=>`<div class="row between" style="padding:9px 0"><span>${esc(r.name)}</span><button class="btn secondary small" type="button" data-restore-stage="${esc(r.id)}" ${active.length>=15?'disabled':''}>Restore</button></div>`).join('')}</details>`:''}</div>
 <div class="formgroup"><h3 class="workflow-heading"><span class="stepnum green">03</span> Standard Hiring Outcomes</h3><div class="row outcomes-flow"><span>Selected by Company</span><span>Joined</span></div></div></section>
 <div class="savebar"><span class="grow muted" id="workflowDirtyLabel"></span><button class="btn secondary" type="button" data-undo-workflow>Discard edits</button><button class="btn primary" type="button" data-review-workflow>Review &amp; Save Workflow</button></div></div>`;
 renderImpact();
}

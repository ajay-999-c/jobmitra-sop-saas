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
  const number=v=>v===''||v==null?null:Number(v),body={company_id:draft.companyId,title:draft.title,target_date:draft.targetDate||null,company_contact:draft.companyContact||null,location:draft.location||null,work_mode:draft.workMode||null,vacancies:number(draft.vacancies),status:draft.status,skills:String(draft.skills||'').split(',').map(s=>s.trim()).filter(Boolean),experience_min:number(draft.experienceMin),experience_max:number(draft.experienceMax),qualification:draft.qualification||null,salary_min_inr:number(draft.salaryMin),salary_max_inr:number(draft.salaryMax),salary_period:draft.salaryPeriod||null,salary_basis:draft.salaryBasis||'UNKNOWN',requirement_notes:draft.notes||null,full_jd:draft.fullJD||null};
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
 el('heroTitle').textContent=view==='dashboard'?'JD Dashboard':draft.title.trim()||'New Job Requirement';
 el('heroSubtitle').textContent=view==='dashboard'?'Requirements, deadlines and progress':draft.company||'Select company';
 const status=draft.status;
 el('statusPill').className='status '+({ACTIVE:'green',ON_HOLD:'amber',CLOSED:'red'}[status]||'neutral');
 el('statusPill').innerHTML='<i></i>'+({ACTIVE:'Active hiring',DRAFT:'Draft',ON_HOLD:'On hold',CLOSED:'Closed'}[status]||'Draft');
 el('statusPill').hidden=view==='dashboard';
 el('topSaveBtn').hidden=view!=='workflow';el('topSaveBtn').disabled=isNew;
 for(const [id,value] of Object.entries({navDashboard:'dashboard',navDetails:'details',navWorkflow:'workflow',navPipeline:'pipeline',navPlacement:'placement',navHistory:'history'})){
  const node=el(id);node.classList.toggle('active',view===value);node.setAttribute('aria-current',view===value?'page':'false');
 }
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

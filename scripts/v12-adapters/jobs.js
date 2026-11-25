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
async function confirmCandidateAction(){return native.run(async()=>{if(!modalAction)return;const {candidateId,action,next}=modalAction,c=draft.candidates.find(c=>c.id===candidateId),owner=el('confirmCandidateAction');if(!c)throw Error('Candidate membership is unavailable.');await native.authorize();const feedback=(el('candidateFeedback')?.value||'').trim(),feedback_source=({'Company':'COMPANY','Jobmitra':'JOBMITRA','Candidate':'CANDIDATE'})[el('feedbackSource')?.value]||'NOT_SPECIFIED';if(action==='note'){if(!feedback)throw Error('Enter feedback before saving.');await native.api(`/api/ats-v2/jobs/${draft.id}/candidates/${c.linkId}/feedback`,{feedback,feedback_source},'POST',owner);}else if(next==='SELECTED'){await native.outcome(draft,c,'SELECT',owner,feedback,feedback_source);}else if(action==='reject'&&c.selectionOutcome==='PENDING_JOINING'){const kind=prompt('Close selection: NOT_JOINED or CANCEL','NOT_JOINED');if(!['NOT_JOINED','CANCEL'].includes(kind))throw Error('No selection closure recorded.');await native.outcome(draft,c,kind,owner,feedback,feedback_source);}else{const stage=action==='reject'?'NOT_SELECTED':next;await native.api(`/api/ats-v2/jobs/${draft.id}/candidates/${c.linkId}/move`,{stage_code:stage.startsWith('ROUND:')?'ROUND':stage,round_id:stage.startsWith('ROUND:')?stage.slice(6):null,feedback:feedback||null,feedback_source,expected_stage:c.stageCode,expected_round_id:c.stageId||null,workflow_version:draft.workflowVersion},'POST',owner);}closeModal();await native.refresh();render();toast('Saved. Candidate and JD history reconciled from SQLite.');},toast);}
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

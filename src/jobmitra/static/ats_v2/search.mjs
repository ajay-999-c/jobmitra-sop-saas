import {$,$$,api,save,esc,pretty,pill,empty,list,field,values,numberOrNull,words,money,date,history,dialog,error,clear,notice,bindErrors,resumeVersion} from './shared.mjs';

const params=new URLSearchParams(location.search);
const searchForm=$('#ats-search-form');
const drawer=$('#ats-profile-drawer');
const panel=$('#ats-profile-panel');
const layout=$('.desk-results-layout');
const desktop=matchMedia('(min-width: 1280px)');
const parsedMode=params.get('section')==='parsed-resumes';
$('#ats-parsed-mode').hidden=!parsedMode;
const state={page:1,total:0,pageSize:20,items:[],candidate:null,resumes:[],activities:[],jobs:[],selectedJob:params.get('job')||'',searchVersion:0,profileVersion:0,applied:new URLSearchParams(),profileOpen:false,origin:null};
const numberFields=['experience_years','current_salary_inr','expected_salary_inr','notice_days'];
const currentId=()=>state.candidate?.id;
const rows=data=>list(Array.isArray(data)?data:data?.items);
const skills=candidate=>list(candidate.skills||candidate.skills_json);
const preferred=candidate=>list(candidate.preferred_cities||candidate.preferred_cities_json);
const salary=candidate=>candidate.expected_salary_inr==null?'Expected salary not recorded':`${money(candidate.expected_salary_inr)} · ${pretty(candidate.expected_salary_period||'unknown period')} · ${pretty(candidate.expected_salary_basis||'UNKNOWN')}`;
const noticeText=candidate=>candidate.notice_days==null?(candidate.notice_period_text||'Notice not recorded'):candidate.notice_days===0?'Immediate':candidate.notice_days+' days notice';
function experience(candidate){
  const months=candidate.experience_months??(candidate.experience_years==null?null:Math.round(candidate.experience_years*12));
  if(months==null)return 'Experience not recorded';
  const years=Math.floor(months/12);
  return [years||!months?`${years} yr`:'',months%12?`${months%12} mo`:''].filter(Boolean).join(' ');
}

function searchParams(){
  const query=new URLSearchParams(state.applied);
  query.set('sort',$('#ats-sort').value);query.set('page',state.page);query.set('page_size',state.pageSize);return query;
}
function applyDraft(){
  const query=new URLSearchParams();
  for(const [key,value] of new FormData(searchForm)){
    if(!key.startsWith('include_unknown_')&&value.trim())query.set(key,value.trim());
  }
  let advanced=Number(query.has('max_notice_days'))+Number(query.has('availability'));
  for(const input of searchForm.querySelectorAll('[name^=include_unknown_]')){
    query.set(input.name,String(input.checked));
    if(!input.checked)advanced++;
  }
  state.applied=query;
  $('#ats-advanced-count').textContent=advanced?` · ${advanced}`:'';
}
function salaryQualifier(candidate){
  if(!state.applied.has('salary_min')&&!state.applied.has('salary_max'))return '';
  const basis=state.applied.get('salary_basis');
  if(candidate.expected_salary_inr==null||!candidate.expected_salary_period||
    !candidate.expected_salary_basis||candidate.expected_salary_basis==='UNKNOWN'||
    (basis!=='INDICATIVE'&&basis!==candidate.expected_salary_basis))return ' · Not comparable';
  return basis==='INDICATIVE'?' · Indicative':'';
}
function resultCard(candidate){
  const tags=skills(candidate);
  const participation=list(candidate.participation).length;
  return `<article class="ats-card ats-result" data-candidate="${esc(candidate.id)}"><button class="ats-result-name" type="button" data-open-candidate="${esc(candidate.id)}" ${String(currentId())===String(candidate.id)?'aria-current="true"':''}>${esc(candidate.full_name)}</button><p class="ats-muted">${esc(candidate.job_title||'Job title not recorded')}${candidate.current_employer?' · '+esc(candidate.current_employer):''}</p><div class="ats-result-facts"><span>${esc(candidate.current_city||'Location not recorded')}</span><span>${esc(experience(candidate))}</span><span>${esc(noticeText(candidate))}</span><span>${esc(salary(candidate)+salaryQualifier(candidate))}</span>${participation?`<span>${participation} JD ${participation===1?'link':'links'}</span>`:''}</div><div class="ats-taglist">${tags.slice(0,5).map(skill=>pill(skill,'ats-blue')).join('')}${tags.length>5?pill('+'+(tags.length-5)+' more'):''}</div></article>`;
}
async function search(reset=false){
  if(reset)state.page=1;
  clear();const version=++state.searchVersion;
  $('#ats-results').innerHTML=empty('Searching candidates…');
  $('#ats-pagination').replaceChildren();
  const context=$('#ats-salary-context');
  const hasSalary=state.applied.has('salary_min')||state.applied.has('salary_max');
  context.hidden=!hasSalary;
  context.textContent=state.applied.get('salary_basis')==='INDICATIVE'
    ?'Indicative amounts only. CTC, gross and in-hand are not equivalent.'
    :'Amounts are compared only within the selected salary basis.';
  let result;
  try{result=await api('/candidates?'+searchParams());}
  catch(err){
    if(version!==state.searchVersion)return;
    $('#ats-result-count').textContent='Candidate Results';
    $('#ats-results').innerHTML=empty('Search unavailable','Submit the search again to retry.');
    throw err;
  }
  if(version!==state.searchVersion)return;
  state.items=result.items;state.total=result.total;state.page=result.page;state.pageSize=result.page_size;
  $('#ats-result-count').textContent=`${result.total} Candidate${result.total===1?'':'s'}`;
  $('#ats-results').innerHTML=result.items.length?result.items.map(resultCard).join(''):empty('No matching candidates','Try broadening the search or clearing filters.');
  pagination();
}
function pagination(){
  const max=Math.max(1,Math.ceil(state.total/state.pageSize));
  $('#ats-pagination').innerHTML=`<button type="button" class="ats-btn ats-secondary ats-small" data-page="${state.page-1}" ${state.page<=1?'disabled':''}>Previous</button><span>Page ${state.page} of ${max}</span><button type="button" class="ats-btn ats-secondary ats-small" data-page="${state.page+1}" ${state.page>=max?'disabled':''}>Next</button>`;
}
async function loadJobs(){
  let page=1;state.jobs=[];let result;
  do{result=await api(`/jobs?status=ACTIVE&page=${page}&page_size=100`);state.jobs.push(...rows(result));page++;}while(state.jobs.length<result.total&&rows(result).length);
}
function moveProfile(){
  if(!state.profileOpen)return;
  if(desktop.matches){
    if(drawer.open)drawer.close();
    layout.append(panel);
  }else{
    drawer.append(panel);
    if(!drawer.open)drawer.showModal();
  }
  $('#ats-close-profile').focus({preventScroll:true});
}
function closeProfile(){
  state.profileOpen=false;
  state.profileVersion++;
  state.candidate=null;
  if(drawer.open)drawer.close();
  panel.hidden=true;
  layout.append(panel);
  layout.classList.remove('has-profile');
  $$('[data-open-candidate]').forEach(item=>item.removeAttribute('aria-current'));
  const url=new URL(location.href);
  if(/^\/ats-v2\/candidates\/\d+$/.test(url.pathname))url.pathname='/candidate-search-v2';
  url.searchParams.delete('candidate');
  window.history.replaceState(null,'',url);
  const origin=state.origin;
  const replacement=origin?.dataset.openCandidate
    ?$$('[data-open-candidate]').find(item=>item.dataset.openCandidate===origin.dataset.openCandidate):null;
  (origin?.isConnected?origin:replacement||searchForm.elements.keywords).focus();
}
desktop.addEventListener('change',moveProfile);
drawer.addEventListener('cancel',event=>{event.preventDefault();closeProfile();});
$('#ats-close-profile').onclick=closeProfile;
async function profile(id,focus=false){
  const version=++state.profileVersion;
  const profileHost=$('#ats-profile');profileHost.innerHTML=empty('Loading candidate profile…');
  if(!state.profileOpen){
    state.profileOpen=true;
    panel.hidden=false;
    layout.classList.add('has-profile');
    moveProfile();
  }
  let candidate,resumes,activities;
  try{
    [candidate,resumes,activities]=await Promise.all([api('/candidates/'+id),api(`/candidates/${id}/resumes`),api(`/candidates/${id}/activities`)]);
  }catch(err){
    if(version!==state.profileVersion)return;
    profileHost.innerHTML=empty('Profile unavailable',err.message);
    return;
  }
  if(version!==state.profileVersion)return;
  state.candidate=candidate;state.resumes=rows(resumes);state.activities=rows(activities);
  renderProfile();
  $$('[data-open-candidate]').forEach(item=>{
    if(item.dataset.openCandidate===String(id))item.setAttribute('aria-current','true');
    else item.removeAttribute('aria-current');
  });
  const url=new URL(location.href);url.searchParams.set('candidate',id);url.searchParams.delete('register');window.history.replaceState(null,'',url);
  if(focus&&parsedMode)$('#ats-profile-resumes h3').focus();
  else if(focus)$('#ats-close-profile').focus();
}
const detail=(label,value)=>`<dt>${esc(label)}</dt><dd>${esc(value??'Not recorded')}</dd>`;
function renderProfile(){
  const candidate=state.candidate;if(!candidate)return;
  const participation=list(candidate.participation);
  const links=candidate.links||{};
  const original=state.resumes.filter(resume=>resume.resume_kind==='ORIGINAL'&&resume.is_current&&resume.downloadable);
  const parsed=state.resumes.filter(resume=>resume.resume_kind==='PARSED_TEXT'&&resume.is_current&&!resume.requires_review);
  $('#ats-profile').innerHTML=`<div class="ats-row-heading"><div><p class="ats-hint desk-candidate-id">${esc(candidate.candidate_code||'CANDIDATE #'+candidate.id)}</p><h2>${esc(candidate.full_name)}</h2><p class="ats-muted">${esc(candidate.job_title||'Job title not recorded')}</p></div><button id="ats-edit-candidate" class="ats-btn ats-secondary ats-small" type="button">Edit</button></div><div class="ats-pills">${pill(pretty(candidate.availability),candidate.availability==='AVAILABLE'?'ats-green':'')}${pill(candidate.is_active?'Active':'Inactive')}${candidate.source_legacy?pill('Imported','ats-blue'):''}</div><dl>${detail('Employer',candidate.current_employer)}${detail('Location',candidate.current_city)}${candidate.hometown?detail('Hometown',candidate.hometown):''}${candidate.home_state?detail('Home state',candidate.home_state):''}${candidate.ready_to_relocate!=null?detail('Relocation',candidate.ready_to_relocate?'Ready to relocate':'Not confirmed'):''}${detail('Preferred',preferred(candidate).join(', ')||null)}${detail('Experience',experience(candidate))}${detail('Qualification',candidate.qualification)}${detail('Domain',candidate.primary_domain)}${detail('Expected salary',salary(candidate))}${detail('Current salary',candidate.current_salary_inr==null?null:`${money(candidate.current_salary_inr)} · ${pretty(candidate.current_salary_period||'Unknown period')} · ${pretty(candidate.current_salary_basis||'UNKNOWN')}`)}${detail('Notice',noticeText(candidate))}${detail('Phone',candidate.phone)}${detail('Email',candidate.email)}${detail('Source',candidate.source_original||pretty(candidate.source))}</dl><div class="ats-taglist">${skills(candidate).map(skill=>pill(skill,'ats-blue')).join('')}</div>${candidate.professional_summary?`<p class="ats-muted ats-preline ats-profile-section">${esc(candidate.professional_summary)}</p>`:''}${Object.keys(links).length?`<div class="ats-profile-section"><h3>Professional links</h3>${Object.entries(links).map(([label,value])=>`<p class="ats-hint"><b>${esc(pretty(label))}</b><br>${/^https?:\/\//i.test(value)?`<a class="ats-link" href="${esc(value)}" target="_blank" rel="noopener noreferrer">${esc(value)}</a>`:esc(value)}</p>`).join('')}</div>`:''}<div class="ats-profile-section"><div class="ats-row-heading"><h3>JD participation</h3><button class="ats-link" id="ats-candidate-history" type="button">Candidate History</button></div>${participation.length?participation.map(item=>`<div class="ats-resume-row"><a class="ats-link" href="/jd-workspace-v2?job=${esc(item.job_id)}&amp;view=pipeline">${esc(item.jd_code||'JD '+item.job_id)} · ${esc(item.title)}</a><br>${pill(item.stage_label||pretty(item.stage_code),item.stage_code==='ROUND'?'ats-purple':'ats-blue')} <button class="ats-link" data-participation-history="${esc(item.id)}" type="button">View journey</button></div>`).join(''):'<p class="ats-hint">This candidate has not been added to a JD yet.</p>'}<label>Active job requirement<select id="ats-pool-job"><option value="">Choose an active JD</option>${state.jobs.map(job=>`<option value="${esc(job.id)}" ${String(job.id)===String(state.selectedJob)?'selected':''}>${esc(job.jd_code||'JD '+job.id)} · ${esc(job.title)}${job.company_name?' · '+esc(job.company_name):''}</option>`).join('')}</select></label><div id="ats-pool-action"></div><p class="ats-hint">Adding creates one association at Candidate Pool. The candidate record is reused.</p></div><div class="ats-profile-section" id="ats-profile-resumes"><div class="ats-row-heading"><h3 tabindex="-1">Resume versions</h3><button id="ats-upload-resume" class="ats-link" type="button">＋ Upload</button></div>${state.resumes.length?state.resumes.map(resumeVersion).join(''):'<p class="ats-hint">No resume versions saved.</p>'}<div class="ats-actions"><button id="ats-attach-parse" class="ats-btn ats-secondary ats-small" type="button" ${original.length?'':'disabled'}>Attach reviewed parse</button><button id="ats-standardize" class="ats-btn ats-secondary ats-small" type="button" ${parsed.length?'':'disabled'}>Create standard resume</button></div><p class="ats-hint">Originals, parsed professional data and standardized outputs remain separate versions. Review facts before attaching a parse or generating an output.</p></div><div class="ats-profile-section"><div class="ats-row-heading"><h3>Activities &amp; follow-ups</h3><button id="ats-add-activity" class="ats-link" type="button">＋ Add</button></div>${state.activities.length?state.activities.map(activity=>`<div class="ats-activity"><strong>${esc(pretty(activity.activity_type))}</strong> ${pill(pretty(activity.status))}${activity.notes?`<p>${esc(activity.notes)}</p>`:''}<p class="ats-hint">${activity.due_at?'Due '+esc(date(activity.due_at))+' IST':activity.occurred_at?'Occurred '+esc(date(activity.occurred_at))+' IST':'No date recorded'}</p>${activity.status==='OPEN'?`<div class="ats-actions"><button class="ats-link" data-activity-done="${esc(activity.id)}" type="button">Mark done</button><button class="ats-link" data-activity-cancel="${esc(activity.id)}" type="button">Cancel activity</button></div>`:''}</div>`).join(''):'<p class="ats-hint">No activities recorded.</p>'}</div><p class="ats-hint ats-profile-section">Created ${esc(date(candidate.created_at))} IST<br>Updated ${esc(date(candidate.updated_at))} IST</p>`;
  $('#ats-pool-job').onchange=()=>{state.selectedJob=$('#ats-pool-job').value;poolAction();};poolAction();
}
function poolAction(){
  const id=$('#ats-pool-job').value;const existing=list(state.candidate?.participation).find(item=>String(item.job_id)===String(id));
  $('#ats-pool-action').innerHTML=existing?`<a href="/jd-workspace-v2?job=${esc(id)}&amp;view=pipeline" class="ats-btn ats-secondary ats-full">View Existing JD Pool →</a>`:`<button id="ats-add-to-pool" class="ats-btn ats-full" type="button" ${!id||!state.candidate?.is_active?'disabled':''}>Add to JD Pool</button>`;
}
function candidateForm(candidate={}){
  const links=candidate.links||{};
  return `<div class="ats-form-grid">${field('full_name','Full name · preserve candidate identity',candidate.full_name||'',{required:true,span:true})}${field('phone','Phone',candidate.phone||'',{type:'tel'})}${field('email','Email',candidate.email||'',{type:'email'})}${field('job_title','Current job title',candidate.job_title||'')}${field('current_employer','Current employer',candidate.current_employer||'')}${field('current_city','Current location',candidate.current_city||'')}${field('preferred_cities','Preferred locations · comma separated',preferred(candidate).join(', '))}${field('experience_years','Experience · years',candidate.experience_years??'',{type:'number',min:0,max:80,step:.1})}${field('qualification','Qualification',candidate.qualification||'')}${field('primary_domain','Primary domain',candidate.primary_domain||'')}${field('notice_days','Notice period · days',candidate.notice_days??'',{type:'number',min:0,max:365,step:1})}${field('skills','Skills · comma separated',skills(candidate).join(', '),{span:true})}${field('professional_summary','Professional summary / responsibilities',candidate.professional_summary||'',{type:'textarea',span:true})}<h3 class="ats-span ats-form-section">Salary · keep period and basis separate</h3>${field('current_salary_inr','Current salary · ₹',candidate.current_salary_inr??'',{type:'number',min:0,step:1})}${field('current_salary_period','Current salary period',candidate.current_salary_period||'',{choices:[['','Not recorded'],'MONTHLY','ANNUAL']})}${field('current_salary_basis','Current salary basis',candidate.current_salary_basis||'UNKNOWN',{choices:['UNKNOWN','CTC','GROSS','IN_HAND']})}${field('expected_salary_inr','Expected salary · ₹',candidate.expected_salary_inr??'',{type:'number',min:0,step:1})}${field('expected_salary_period','Expected salary period',candidate.expected_salary_period||'',{choices:[['','Not recorded'],'MONTHLY','ANNUAL']})}${field('expected_salary_basis','Expected salary basis',candidate.expected_salary_basis||'UNKNOWN',{choices:['UNKNOWN','CTC','GROSS','IN_HAND']})}<h3 class="ats-span ats-form-section">Professional links &amp; availability</h3>${field('linkedin','LinkedIn URL',links.linkedin||'',{type:'url'})}${field('portfolio','Portfolio URL',links.portfolio||'',{type:'url'})}${field('github','GitHub URL',links.github||'',{type:'url'})}${field('availability','Availability',candidate.availability||'TO_CONFIRM',{choices:['AVAILABLE','TO_CONFIRM','UNAVAILABLE']})}${field('source','Source',candidate.source||'MANUAL',{choices:['MANUAL','WALK_IN','FOUNDIT_PASTE','RESUME_UPLOAD','OTHER']})}${candidate.id?field('is_active','Profile status',candidate.is_active?'true':'false',{choices:[['true','Active'],['false','Inactive']]}):''}</div><p class="ats-hint">Leave unknown amounts and experience blank. Potential contact duplicates require review; matching names alone do not merge candidates.</p>`;
}
function editCandidate(create=false){
  const original=create?{}:state.candidate;
  dialog(create?'Register Candidate':'Edit Candidate Profile',candidateForm(original),create?'Register candidate':'Save candidate profile',async data=>{
    numberFields.forEach(key=>data[key]=numberOrNull(data[key]));data.skills=words(data.skills);data.preferred_cities=words(data.preferred_cities);data.links={...(original.links||{})};for(const key of ['linkedin','portfolio','github']){if(data[key])data.links[key]=data[key];else delete data.links[key];delete data[key];}for(const key of ['phone','email','job_title','current_employer','current_city','qualification','primary_domain','professional_summary','current_salary_period','expected_salary_period'])if(data[key]==='')data[key]=null;if(data.is_active!==undefined)data.is_active=data.is_active==='true';
    const saved=await save(create?'/candidates':'/candidates/'+original.id,data,create?'POST':'PATCH');await search();await profile(saved.id,true);notice(create?'Candidate registered in the new workspace.':'Candidate profile updated. Tracked changes are recorded in history.');
  });
}
function uploadResume(){
  dialog('Upload resume version',`<label>Resume kind<select name="resume_kind"><option value="ORIGINAL">Original resume</option><option value="JOBMITRA_STANDARD">Existing Jobmitra standardized resume</option></select></label><label class="ats-form-section">PDF or DOCX<input name="file" type="file" accept=".pdf,.docx" required></label><p class="ats-hint">Uploads create preserved versions. Filenames are displayed as labels; storage uses private generated paths.</p>`,'Upload version',async(_,form)=>{
    const file=$('[name=file]',form).files[0];if(!file)throw Error('Choose a PDF or DOCX.');
    await api(`/candidates/${currentId()}/resumes`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Resume-Filename':encodeURIComponent(file.name),'X-Resume-Kind':$('[name=resume_kind]',form).value},body:file});await profile(currentId());notice('Resume version uploaded. Previous versions are preserved.');
  });
}
function attachParse(){
  const originals=state.resumes.filter(resume=>resume.resume_kind==='ORIGINAL'&&resume.is_current&&resume.downloadable);
  dialog('Attach reviewed professional parse',`<label>Source original resume<select name="source_resume_id" required>${originals.map(resume=>`<option value="${esc(resume.id)}">#${esc(resume.id)} · ${esc(resume.original_filename||'Original resume')} · ${esc(date(resume.created_at))}</option>`).join('')}</select></label><p class="ats-hint">Attach professional JSON produced by your parsing workflow. Candidate identity and contacts are taken from registration, never replaced by the parse.</p><label>Load JSON file · optional<input type="file" name="json_file" accept=".json,application/json"></label><label>Professional JSON<textarea name="profile" class="ats-json" required placeholder="{}"></textarea></label><p class="ats-hint">Supported fields include professional_summary, current_job_title, current_employer, skills, qualification, work_experience, education, projects, certifications and languages. Do not include personal identity fields.</p><button type="button" id="ats-preview-parse" class="ats-btn ats-secondary ats-small">Preview JSON</button><pre id="ats-parse-preview" class="ats-json ats-preline" aria-live="polite" hidden></pre><label class="ats-check ats-form-section"><input name="facts_reviewed" type="checkbox" required> I reviewed these facts against the source original resume.</label>`,'Save parsed version',async data=>{
    let profileData;try{profileData=JSON.parse(data.profile);}catch{throw Error('Enter valid professional JSON.');}
    await save(`/candidates/${currentId()}/parsed-resume`,{profile:profileData,source_resume_id:Number(data.source_resume_id),facts_reviewed:data.facts_reviewed==='on'});await profile(currentId());await search();notice('Reviewed professional JSON saved as a separate version.');
  });
  const form=$('#ats-dialog-form');
  const source=form.elements.profile;
  const preview=$('#ats-parse-preview');
  form.elements.json_file.onchange=async event=>{
    const file=event.target.files[0];
    if(!file)return;
    try{
      if(file.size>250000)throw Error('Choose a JSON file up to 250 KB.');
      source.value=await file.text();
      source.dispatchEvent(new Event('input'));
    }catch(err){preview.textContent=err.message;preview.hidden=false;}
  };
  source.oninput=()=>{preview.hidden=true;form.elements.facts_reviewed.checked=false;};
  form.elements.source_resume_id.onchange=source.oninput;
  $('#ats-preview-parse').onclick=()=>{
    try{preview.textContent=JSON.stringify(JSON.parse(source.value),null,2);}
    catch{preview.textContent='Enter valid professional JSON.';}
    preview.hidden=false;
  };
}
function standardize(){
  const parsed=state.resumes.filter(resume=>resume.resume_kind==='PARSED_TEXT'&&resume.is_current&&!resume.requires_review);
  dialog('Create Jobmitra standard resume',`<label>Reviewed parsed version<select name="parsed_resume_id" required>${parsed.map(resume=>`<option value="${esc(resume.id)}">Parsed version #${esc(resume.id)} · ${esc(date(resume.created_at))}</option>`).join('')}</select></label><div class="ats-quiet">The standardized output uses the registered candidate name and saved professional facts. Originals and earlier outputs remain preserved.</div><label class="ats-check"><input name="facts_reviewed" type="checkbox" required> I have checked the candidate identity and professional facts for this version.</label>`,'Generate standard resume',async data=>{await save(`/candidates/${currentId()}/standardize`,{parsed_resume_id:Number(data.parsed_resume_id),facts_reviewed:data.facts_reviewed==='on'});await profile(currentId());notice('A new standardized resume version is ready to download.');});
}
function addActivity(){
  dialog('Record candidate activity',`<div class="ats-form-grid">${field('activity_type','Activity type','FOLLOW_UP',{choices:['FOLLOW_UP','OFFICE_VISIT','JOB_SEARCH_REQUEST','CALL','INTERVIEW','CANDIDATE_SUBMISSION','OTHER']})}${field('status','Status','OPEN',{choices:['OPEN','DONE','CANCELLED']})}${field('job_id','Related JD · optional','',{choices:[['','Candidate only'],...list(state.candidate.participation).map(item=>[item.job_id,item.jd_code+' · '+item.title])]})}${field('due_at','Due date & time · local','',{type:'datetime-local'})}${field('occurred_at','Occurred date & time · local','',{type:'datetime-local'})}${field('notes','Notes','',{type:'textarea',span:true})}</div>`,'Save activity',async data=>{data.job_id=numberOrNull(data.job_id);for(const key of ['due_at','occurred_at'])data[key]=data[key]?new Date(data[key]).toISOString():null;await save(`/candidates/${currentId()}/activities`,data);await profile(currentId());notice('Candidate activity recorded.');});
}
async function showHistory(page=1,participationId=null){
  const participation=participationId?list(state.candidate.participation).find(item=>String(item.id)===String(participationId)):null;
  const query=new URLSearchParams({candidate_id:currentId(),page});if(participation){query.set('job_id',participation.job_id);query.set('jd_candidate_id',participation.id);}
  const result=await api('/history?'+query);
  const max=Math.max(1,Math.ceil(result.total/result.page_size));
  dialog(participation?'Candidate-in-JD Journey':'Candidate History',`<p class="ats-muted">${esc(state.candidate.full_name)}${participation?' · '+esc(participation.title):' · all profile changes, resume versions and JD journeys'}</p><div class="ats-profile-section">${history(result.items)}</div><div class="ats-pagination"><button class="ats-btn ats-secondary ats-small" data-history-page="${result.page-1}" type="button" ${result.page<=1?'disabled':''}>Previous</button><span>Page ${esc(result.page)} of ${esc(max)}</span><button class="ats-btn ats-secondary ats-small" data-history-page="${result.page+1}" type="button" ${result.page>=max?'disabled':''}>Next</button></div>`);
  $$('[data-history-page]',$('#ats-dialog')).forEach(button=>button.onclick=bindErrors(()=>showHistory(Number(button.dataset.historyPage),participationId)));
}

$('#ats-register').onclick=()=>editCandidate(true);
searchForm.addEventListener('invalid',event=>{
  if(event.target.closest('#ats-more-filters'))$('#ats-more-filters').open=true;
},true);
searchForm.onsubmit=bindErrors(async event=>{
  event.preventDefault();clear();
  for(const [min,max,label] of [['experience_min','experience_max','experience'],['salary_min','salary_max','salary']]){
    const lower=searchForm.elements[min],upper=searchForm.elements[max];
    if(lower.value!==''&&upper.value!==''&&lower.valueAsNumber>upper.valueAsNumber){
      upper.setCustomValidity(`Maximum ${label} must be at least the minimum.`);
      upper.reportValidity();
      upper.setCustomValidity('');
      return;
    }
  }
  applyDraft();$('#ats-more-filters').open=false;await search(true);
});
$('#ats-sort').onchange=bindErrors(()=>search(true));
$('#ats-clear-filters').onclick=bindErrors(async()=>{searchForm.reset();applyDraft();$('#ats-more-filters').open=false;$('#ats-sort').value='relevance';await search(true);});
$('#ats-results').addEventListener('click',bindErrors(async event=>{
  const button=event.target.closest('[data-open-candidate]');
  if(button){state.origin=button;await profile(button.dataset.openCandidate,true);}
}));
$('#ats-pagination').addEventListener('click',bindErrors(async event=>{const button=event.target.closest('[data-page]');if(button){state.page=Number(button.dataset.page);await search();$('#ats-result-count').scrollIntoView({behavior:'smooth',block:'start'});}}));
$('#ats-profile').addEventListener('click',bindErrors(async event=>{
  const button=event.target.closest('button');if(!button)return;clear();
  if(button.id==='ats-edit-candidate')editCandidate();
  else if(button.id==='ats-candidate-history')await showHistory();
  else if(button.dataset.participationHistory)await showHistory(1,button.dataset.participationHistory);
  else if(button.id==='ats-upload-resume')uploadResume();
  else if(button.id==='ats-attach-parse')attachParse();
  else if(button.id==='ats-standardize')standardize();
  else if(button.id==='ats-add-activity')addActivity();
  else if(button.id==='ats-add-to-pool'){
    button.disabled=true;
    try{await save(`/jobs/${$('#ats-pool-job').value}/candidates`,{candidate_id:currentId()});await profile(currentId());await search();notice('Candidate added to JD Pool. Their initial stage is Candidate Pool.');}catch(err){await profile(currentId());throw err;}
  }
  else if(button.dataset.resumeJson){const resume=state.resumes.find(item=>String(item.id)===button.dataset.resumeJson);dialog(resume.requires_review?'Imported parsed JSON · review required':'Saved professional JSON',`${resume.requires_review?'<div class="ats-alert ats-warning">This is preserved historical parse data. It has not been approved for this workspace’s resume generation workflow.</div>':''}<pre class="ats-json ats-preline">${esc(JSON.stringify(resume.historical_parsed_json??resume.profile??resume.parsed_json,null,2))}</pre>`);}
  else if(button.dataset.activityDone||button.dataset.activityCancel){await save('/activities/'+(button.dataset.activityDone||button.dataset.activityCancel),{status:button.dataset.activityDone?'DONE':'CANCELLED'},'PATCH');await profile(currentId());notice('Activity status updated.');}
}));

try{
  applyDraft();await Promise.all([loadJobs(),search()]);
  const pathCandidate=location.pathname.match(/^\/ats-v2\/candidates\/(\d+)$/)?.[1];
  if(params.get('candidate')||pathCandidate)await profile(params.get('candidate')||pathCandidate);
  if(params.get('register'))editCandidate(true);
}catch(err){error(err);if(!state.items.length)$('#ats-results').innerHTML=empty('Candidate search could not be loaded','Check the error above and retry after the connection is restored.');}

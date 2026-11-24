import {uuid,sha256} from './crypto.mjs';
// Additive Candidate Desk controls, scoped to the approved candidate Shadow DOM.
import {parsedResume} from './parsed-resume.mjs';
import {submitCreation,nativeFieldErrors} from './creation-forms.mjs';
const coreGroups=[
 ['Personal & contact',[['full_name','Full name'],['phone','Mobile number'],['email','Email','email'],['links','Professional links','links'],['current_city','Current location'],['preferred_cities','Preferred locations','list']]],
 ['Professional',[['job_title','Current job title'],['current_employer','Current / last employer'],['experience_years','Experience years','number'],['qualification','Qualification'],['primary_domain','Domain'],['skills','Skills','list'],['professional_summary','Professional summary','textarea'],['availability','Availability','availability'],['source','Candidate source','source']]],
 ['Salary & availability',[['current_salary_inr','Current salary (INR)','decimal'],['current_salary_period','Current salary period','period'],['current_salary_basis','Current salary basis','basis'],['expected_salary_inr','Expected salary (INR)','decimal'],['expected_salary_period','Expected salary period','period'],['expected_salary_basis','Expected salary basis','basis'],['notice_days','Verified notice days','integer']]]
];
const extraFields=[['registration_purpose','Purpose of Visit / Registration','textarea'],['hometown','Hometown'],['home_state','Home state'],['subdomain','Subdomain'],['ready_to_relocate','Relocation preference','boolean'],['experience_months','Exact experience months','integer'],['notice_period_text','Original notice text','textarea']];
const structures={employment_history:[['employer','Employer'],['job_title','Job role'],['start_date','Start (YYYY / YYYY-MM / YYYY-MM-DD)'],['end_date','End (blank if unknown/current)'],['experience_months','Role experience months','integer'],['responsibilities','Responsibilities','textarea'],['achievements','Achievements','textarea']],education_history:[['institution','Institution'],['qualification','Qualification'],['start_year','Start year','integer'],['end_year','End year','integer']],certifications:[['name','Certification'],['issuer','Issuer'],['issued_on','Issue date (optional)']],projects:[['name','Project'],['role','Role'],['description','Description','textarea']]};
const choices={availability:['TO_CONFIRM','AVAILABLE','UNAVAILABLE'],source:['MANUAL','WALK_IN','FOUNDIT_PASTE','RESUME_UPLOAD','OTHER','EMAIL'],period:['','MONTHLY','ANNUAL'],basis:['','UNKNOWN','CTC','GROSS','IN_HAND'],boolean:['','true','false']};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const same=(a,b)=>JSON.stringify(a??null)===JSON.stringify(b??null);
export function installCandidateDesk(native,bridge){
 const root=bridge.root,$=id=>root.getElementById(id),apiBase='/api/v12/approved';
 const parsed=parsedResume(native,bridge);
 let opener=null,previousOverflow=null,scrollY=0,historyNavigation=false;
 const style=document.createElement('style');style.textContent=`
 #detailPanel{min-height:0;max-height:calc(100dvh - var(--detail-offset,90px));overflow-y:auto!important;overscroll-behavior:contain;scrollbar-gutter:stable;scroll-padding:14px}
 #detailPanel:focus-visible{outline:2px solid #2477b8;outline-offset:-2px}#detailContent{min-height:0}
 .candidate-complete .edit-body{overflow:auto;min-height:0;padding:16px;overscroll-behavior:contain}.candidate-complete{display:flex;flex-direction:column;max-height:90dvh;width:min(960px,96vw)!important}.candidate-complete header,.candidate-complete footer{flex-shrink:0;padding:14px 18px}
 .candidate-complete details{border:1px solid #e3e8ef;border-radius:9px;margin-bottom:12px;padding:12px}.candidate-complete summary{font-weight:700;cursor:pointer;margin-bottom:10px}.candidate-edit-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.candidate-edit-grid .field{min-width:0}.candidate-complete textarea{min-height:75px}.candidate-structure{border:1px solid #e3e8ef;padding:12px;border-radius:8px;margin-bottom:10px}
 .candidate-complete pre,.candidate-diff{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 inherit}.candidate-field-review{display:flex;gap:8px;align-items:start;padding:9px;border-bottom:1px solid #e3e8ef}.candidate-field-review span{min-width:0;overflow-wrap:anywhere}.candidate-field-review input{width:auto}.candidate-resume-meta{overflow-wrap:anywhere;font-size:11px;color:#68778d}.candidate-native-notice{padding:10px;border:1px solid #d6e6f4;border-radius:8px;background:#f1f7fc;margin-bottom:12px}.candidate-foundit textarea{min-height:170px;width:100%}.candidate-foundit .candidate-complete{width:100%!important;max-width:none;max-height:none}
 @media(max-width:650px){.candidate-edit-grid{grid-template-columns:1fr}.candidate-complete{width:100vw!important;max-height:100dvh;border-radius:0}.candidate-complete .edit-body{padding:12px}}
 `;root.append(style);
 function lock(){if(previousOverflow)return;scrollY=window.scrollY;previousOverflow=[document.documentElement.style.overflow,document.body.style.overflow];document.documentElement.style.overflow='hidden';document.body.style.overflow='hidden';}
 function unlock(){if(!previousOverflow)return;[document.documentElement.style.overflow,document.body.style.overflow]=previousOverflow;previousOverflow=null;window.scrollTo({top:scrollY,behavior:'instant'});}
 const panel=$('detailPanel');panel.tabIndex=0;panel.setAttribute('role','region');panel.setAttribute('aria-label','Candidate Details');
 function remember(){const e=root.activeElement;opener=e?{element:e,id:e.id,label:e.getAttribute('aria-label')}:null;}
 function opened(){
  const top=Math.max(0,panel.getBoundingClientRect().top);panel.style.setProperty('--detail-offset',(top+12)+'px');
  if(getComputedStyle(panel).position==='fixed')lock();panel.focus({preventScroll:true});
 }
 function closed(){unlock();queueMicrotask(()=>{const e=opener?.element?.isConnected?opener.element:opener?.id?$(opener.id):[...root.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===opener?.label);e?.focus?.({preventScroll:true});});}
 panel.addEventListener('keydown',e=>{
  if(e.key==='Escape'){e.preventDefault();bridge.close();return;}
  if(e.target!==panel||e.altKey||e.ctrlKey||e.metaKey)return;
  const increments={ArrowDown:44,ArrowUp:-44,PageDown:panel.clientHeight*.85,PageUp:-panel.clientHeight*.85};
  if(e.key in increments){e.preventDefault();panel.scrollBy({top:increments[e.key],behavior:'instant'});}
  else if(e.key==='Home'||e.key==='End'){e.preventDefault();panel.scrollTo({top:e.key==='Home'?0:panel.scrollHeight,behavior:'instant'});}
 });
 panel.addEventListener('keydown',e=>{if(e.key!=='Tab'||!previousOverflow)return;const list=[panel,...panel.querySelectorAll('button:not([disabled]),input,select,a[href],[tabindex="0"]')].filter(x=>x.getClientRects().length);const i=list.indexOf(root.activeElement);if((!e.shiftKey&&i===list.length-1)||(e.shiftKey&&i<=0)){e.preventDefault();(e.shiftKey?list.at(-1):panel).focus();}});
 window.addEventListener('resize',()=>{if(panel.classList.contains('mobile-open')){if(getComputedStyle(panel).position==='fixed')lock();else unlock();panel.style.setProperty('--detail-offset',(Math.max(0,panel.getBoundingClientRect().top)+12)+'px');}});
 new MutationObserver(()=>{if(root.host.hidden){unlock();panel.classList.remove('mobile-open');$('detailUnderlay').classList.remove('mobile-open');}}).observe(root.host,{attributes:true,attributeFilter:['hidden']});
 function input(field,value,prefix='core'){
  const [key,label,type='text']=field,id=prefix+'_'+key;
  const val=type==='list'?(value||[]).join(', '):type==='links'?Object.entries(value||{}).map(([k,v])=>k+' = '+v).join('\n'):value??'';
  let control;
  if(type==='source'&&!native.snapshot.candidate_sources?.some(x=>x.value==='EMAIL'))choices.source=choices.source.filter(x=>x!=='EMAIL');
  if(choices[type])control=`<select class="control" id="${id}">${choices[type].map(v=>`<option value="${v}" ${String(value??'')===v?'selected':''}>${v===''?'Unknown':v.replaceAll('_',' ')}</option>`).join('')}</select>`;
  else if(type==='textarea'||type==='links'||(type==='list'&&key==='skills'))control=`<textarea class="control" id="${id}">${esc(val)}</textarea>`;
  else control=`<input class="control" id="${id}" value="${esc(val)}" type="${type==='email'?'email':['number','integer','decimal'].includes(type)?'number':'text'}" ${['number','decimal'].includes(type)?'step="any" min="0"':type==='integer'?'step="1" min="0"':''} ${key==='full_name'?'required maxlength="300"':''}>`;
  return `<div class="field"><label for="${id}">${label}${type==='links'?' (one Label = https://… per line)':''}</label>${control}</div>`;
 }
 function read(field,host,prefix='core'){
  const [key,,type='text']=field,value=host.querySelector('#'+prefix+'_'+key).value.trim();
  if(type==='list')return value?value.split(/[,\n]+/).map(s=>s.trim()).filter(Boolean):[];
  if(type==='links')return Object.fromEntries(value?value.split('\n').map(line=>{const i=line.indexOf('=');if(i<1)throw Error('Use Label = https://… for each professional link.');return[line.slice(0,i).trim(),line.slice(i+1).trim()];}):[]);
  if(type==='boolean')return value===''?null:value==='true';
  if(type==='integer'||type==='number')return value===''?null:Number(value);
  if(type==='decimal')return value===''?null:value; // Never route salaries through Number/parseInt.
  return value===''?null:value;
 }
 function fields(form,state,foundit=false){
  form.innerHTML=coreGroups.map(([name,group],i)=>`<details ${i===0?'open':''}><summary>${name}</summary><div class="candidate-edit-grid">${group.map(f=>input(f,state.candidate[f[0]])).join('')}</div></details>`).join('')+`<details><summary>Registration, location, exact experience & notice evidence</summary><div class="candidate-edit-grid">${extraFields.map(f=>input(f,state.extra?.[f[0]],'extra')).join('')}</div><label><input type="checkbox" id="noticeVerified"> I verified normalized notice days; original notice text remains separate.</label></details>`+Object.entries(structures).map(([key,defs])=>`<details><summary>${key.replaceAll('_',' ')}</summary><div data-rows="${key}"></div><button class="btn tiny outline" type="button" data-add-row="${key}">Add ${key.replaceAll('_',' ')}</button></details>`).join('');
  function row(key,data={}){const defs=structures[key],box=document.createElement('div');box.className='candidate-structure';const prefix='row'+uuid().replaceAll('-','');box.dataset.prefix=prefix;box.innerHTML=`<div class="candidate-edit-grid">${defs.map(f=>input(f,data[f[0]],prefix)).join('')}</div><button class="btn tiny outline" type="button">Remove entry</button>`;box.querySelector('button').onclick=()=>box.remove();form.querySelector(`[data-rows="${key}"]`).append(box);}
  form.querySelectorAll('[data-add-row]').forEach(b=>b.onclick=()=>row(b.dataset.addRow));
  for(const key of Object.keys(structures))for(const item of state.extra?.[key]||[])row(key,item);
  form.querySelectorAll('input[id],select[id],textarea[id]').forEach(control=>{control.name=control.id.startsWith('core_')?control.id.slice(5):control.id.startsWith('extra_')?'extra.'+control.id.slice(6):control.id;});
  if(foundit){
   const source=form.querySelector('#core_source');source.disabled=true;source.selectedOptions[0].textContent='Foundit';
   if(!state.candidate.availability){const blank=new Option('Unknown','',true,true);form.querySelector('#core_availability').prepend(blank);}
   form.querySelector('label[for="core_primary_domain"]').textContent='Industry / Domain';
   form.querySelector('label[for="extra_subdomain"]').textContent='Functional area / Subdomain';
   form.querySelector('#noticeVerified').parentElement.remove();
   for(const id of ['core_experience_years','extra_experience_months'])form.querySelector('#'+id).oninput=()=>{
    const years=form.querySelector('#core_experience_years'),months=form.querySelector('#extra_experience_months');
    if(id==='extra_experience_months')years.value=months.value===''?'':Number(months.value)/12;
    else months.value=years.value===''||!Number.isInteger(Number(years.value)*12)?'':Number(years.value)*12;
   };
  }
 }
 function values(host){
  const candidate=Object.fromEntries(coreGroups.flatMap(([,g])=>g.map(f=>[f[0],read(f,host)])));
  const extra=Object.fromEntries(extraFields.map(f=>[f[0],read(f,host,'extra')]));
  for(const [key,defs]of Object.entries(structures))extra[key]=[...host.querySelector(`[data-rows="${key}"]`).children].map(row=>Object.fromEntries(defs.map(f=>{let value=read(f,row,row.dataset.prefix);if(value===null&&f[2]!=='integer'&&!['start_date','end_date','issued_on'].includes(f[0]))value='';return[f[0],value];}))).filter(row=>Object.values(row).some(v=>v!==null&&v!==''));
  return{candidate,extra};
 }
 function diff(before,after){
  const changes={},extra={};
  for(const [k,v]of Object.entries(after.candidate))if(!same(v,before.candidate[k]))changes[k]=v;
  for(const [k,v]of Object.entries(after.extra))if(!same(v,before.extra?.[k]??(Array.isArray(v)?[]:null)))extra[k]=v;
  return{changes,extra};
 }
 async function edit(cid){
  await native.authorize();const state=await native.api(`${apiBase}/candidates/${cid}/profile`),focus=root.activeElement;
  $('modalHost').innerHTML=`<div class="modal-backdrop"><form class="modal candidate-complete" role="dialog" aria-modal="true" aria-label="Edit Candidate Details"><header><h2>Edit Candidate Details</h2><p>Omitted fields stay unchanged. Clearing an edited field is explicit. Original import and resume evidence are retained.</p></header><div class="edit-body"><div class="candidate-edit-fields"></div><div class="candidate-native-notice" role="status"></div></div><footer><button type="button" class="btn outline" data-cancel>Cancel</button><button type="submit" class="btn primary">Save reviewed changes</button></footer></form></div>`;
  const form=$('modalHost').querySelector('form'),body=form.querySelector('.candidate-edit-fields'),status=form.querySelector('[role="status"]');fields(body,state);const initialFormValues=values(body);lock();
  const close=()=>{$('modalHost').replaceChildren();unlock();if(panel.classList.contains('mobile-open')&&getComputedStyle(panel).position==='fixed'&&panel.getClientRects().length)lock();focus?.focus({preventScroll:true});};form.querySelector('[data-cancel]').onclick=close;
  form.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close();}if(e.key==='Tab'){const list=[...form.querySelectorAll('button,input:not([disabled]),select:not([disabled]),textarea')].filter(x=>x.getClientRects().length);if(e.shiftKey&&root.activeElement===list[0]){e.preventDefault();list.at(-1).focus();}else if(!e.shiftKey&&root.activeElement===list.at(-1)){e.preventDefault();list[0].focus();}}});
  form.querySelector('input').focus();
  form.onsubmit=e=>{e.preventDefault();native.run(async()=>{
   const update=diff(initialFormValues,values(body)),approved=[...Object.keys(update.changes),...Object.keys(update.extra).map(k=>'extra:'+k)];if(!approved.length){status.textContent='No changes to save.';return;}
   const button=form.querySelector('[type="submit"]');button.disabled=true;
   try{await native.api(`${apiBase}/candidates/${cid}/profile`,{...update,expected_revision:state.revision,actor_name:native.actor,idempotency_key:native.key(form),approved_fields:approved,notice_days_verified:!!body.querySelector('#noticeVerified').checked},'PATCH',form);const saved=await native.api(`${apiBase}/candidates/${cid}/profile`);if(saved.revision===state.revision)throw Error('Save read-back did not confirm a new version.');await native.refresh();close();bridge.profile(cid,'overview');bridge.toast('Candidate details persisted and read back.');}finally{button.disabled=false;}
  },message=>{status.textContent=message;});};
 }
 function resumeHTML(c){
  const versions=native.snapshot.resumes.filter(r=>String(r.candidate_id)===String(c.id)&&r.resume_kind!=='PARSED_TEXT');
  const group=(kind,title)=>`<section class="profile-v9-card"><h3>${title}</h3><div class="profile-v9-docs">${versions.filter(r=>r.resume_kind===kind).map(r=>`<div class="profile-v9-doc"><div><strong>${esc(r.original_filename||'Historical reference')} ${r.is_current?'<span class="tiny-pill blue">Current version</span>':''}</strong><small>${esc(r.created_at)} · Uploaded by ${esc(r.uploaded_by||'Not recorded')}</small><p class="candidate-resume-meta">SHA-256: ${esc(r.sha256||'Not recorded / unavailable')}${kind==='JOBMITRA_STANDARD'?'<br>Preparation: '+esc(r.preparation_source||r.source_type)+' · Original version: '+esc(r.source_original_id||'Not linked')+'<br>'+esc(r.upload_notes):''}</p></div><div>${r.downloadable?`<button type="button" class="btn tiny outline" data-resume-download="${r.id}">View / Download</button>${r.is_current?'':`<button type="button" class="btn tiny outline" data-resume-current="${r.id}" data-resume-kind="${kind}">Set current version</button>`}`:'<span class="tiny-pill amber">Historical file unavailable</span>'}</div></div>`).join('')||'<p class="profile-v9-muted">No versions recorded.</p>'}</div></section>`;
  return`<div class="profile-v9-panel">${group('ORIGINAL','Original Candidate Resume · Version History')}<section class="profile-v9-card"><form class="profile-v9-form" id="profileResumeForm"><label for="profileResumeFile">Upload Original Resume · PDF/DOCX up to 10 MB</label><input id="profileResumeFile" type="file" accept=".pdf,.docx" required><button class="btn primary" type="submit">Upload Original Resume</button></form></section>${group('JOBMITRA_STANDARD','Jobmitra Altered / Standardized Resume · Version History')}<section class="profile-v9-card"><form class="profile-v9-form" id="alteredResumeForm"><label for="alteredResumeFile">Upload Jobmitra Altered Resume · PDF/DOCX</label><input id="alteredResumeFile" type="file" accept=".pdf,.docx" required><label for="alteredSource">Preparation source</label><select id="alteredSource">${['ChatGPT','Claude','Manual','Other'].map(s=>'<option>'+s+'</option>').join('')}</select><label for="alteredOriginal">Source original version · optional</label><select id="alteredOriginal"><option value="">Not linked</option>${versions.filter(r=>r.resume_kind==='ORIGINAL').map(r=>`<option value="${r.id}">${esc(r.original_filename||r.id)} · ${esc(r.created_at)}</option>`).join('')}</select><label for="alteredNotes">Upload notes</label><textarea id="alteredNotes" maxlength="2000" class="control"></textarea><button class="btn primary" type="submit">Upload Jobmitra Altered Resume</button></form><p class="profile-v9-prep">Files and earlier versions are immutable. No AI extraction or master-field replacement occurs. Parsed Resume JSON remains a separate review workflow.</p></section></div>`;
 }
 function bindResume(cid){
  const form=$('alteredResumeForm');if(!form)return;
  form.onsubmit=e=>{e.preventDefault();native.run(async()=>{const file=$('alteredResumeFile').files[0];await native.upload(cid,file,form,'JOBMITRA_STANDARD',{preparation_source:$('alteredSource').value,source_original_id:$('alteredOriginal').value?Number($('alteredOriginal').value):null,upload_notes:$('alteredNotes').value});await native.refresh();bridge.profile(cid,'resumes');bridge.toast('Altered resume version saved and read back.');},bridge.toast);};
  root.querySelectorAll('[data-resume-download]').forEach(b=>b.onclick=()=>native.run(async()=>{await native.authorize();const response=await fetch(`/api/ats-v2/candidates/${cid}/resumes/${b.dataset.resumeDownload}/download`,{credentials:'same-origin'});if(!response.ok)throw Error('Document download was not authorized or verified.');const blob=await response.blob(),bytes=await blob.arrayBuffer(),hash=await sha256(bytes),record=native.snapshot.resumes.find(r=>String(r.id)===b.dataset.resumeDownload);if(hash!==record.sha256)throw Error('Downloaded document checksum differs.');const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=record.original_filename||'resume';a.hidden=true;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);},bridge.toast));
  root.querySelectorAll('[data-resume-current]').forEach(b=>b.onclick=()=>native.run(async()=>{await native.authorize();const current=native.snapshot.resumes.find(r=>String(r.candidate_id)===String(cid)&&r.resume_kind===b.dataset.resumeKind&&r.is_current);await native.api(`${apiBase}/candidates/${cid}/resumes/${b.dataset.resumeCurrent}/current`,{actor_name:native.actor,expected_current_id:current?.id||null},'POST',b);await native.refresh();bridge.profile(cid,'resumes');bridge.toast('Current version persisted; all earlier files retained.');},bridge.toast));
 }
 async function foundit(){
  const view=$('reservedView');let host=$('nativeFoundit');if(host){host.hidden=false;return;}
  host=document.createElement('section');host.id='nativeFoundit';host.className='profile-v9-card candidate-foundit';
  host.innerHTML=`<h2>Foundit Paste</h2><p>Paste candidate profile details from Foundit to automatically populate the registration form.</p><label for="founditPaste">Foundit candidate profile</label><textarea class="control" id="founditPaste" maxlength="50000" placeholder="Paste copied Foundit candidate profile here..."></textarea><div class="profile-v9-inline" style="margin:12px 0"><button class="btn primary" id="parseFoundit" type="button">Parse Candidate Details</button><button class="btn outline" id="clearFoundit" type="button">Clear</button></div><div id="founditStatus" role="status"></div><div id="founditReview"></div>`;
  view.append(host);
  const clear=()=>{$('founditPaste').value='';$('founditReview').replaceChildren();$('founditStatus').textContent='';$('founditPaste').focus();};
  $('clearFoundit').onclick=clear;
  $('parseFoundit').onclick=async()=>{
   const parse=$('parseFoundit');if(parse.disabled)return;parse.disabled=true;$('clearFoundit').disabled=true;
   try{
    await native.authorize();
    if(!$('founditPaste').value.trim()){$('founditStatus').textContent='Paste a candidate profile first.';$('founditPaste').focus();return;}
    const result=await native.api(apiBase+'/foundit/preview',{raw:$('founditPaste').value},'POST',{}),area=$('founditReview');
    area.replaceChildren();$('founditStatus').textContent='Parsed draft only. Review and edit the details before Save Candidate.';
    const title=document.createElement('h3');title.textContent='Review Candidate Details';area.append(title);
    const limitations=document.createElement('p');limitations.className='candidate-native-notice';limitations.textContent='Only supported information is populated. Blank or ambiguous values need your review. Raw pasted text is not retained; a source checksum and reviewed fields are audited.';area.append(limitations);
    for(const item of result.unmapped||[]){const p=document.createElement('p');p.textContent=item.field+': '+item.value+' — '+item.reason;area.append(p);}
    const evidence=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Parsing evidence and ambiguities';evidence.append(summary);
    for(const item of result.evidence){const p=document.createElement('p');p.textContent=item.field+': '+item.raw+' · '+item.note;evidence.append(p);}area.append(evidence);
    const matches=document.createElement('div');matches.className='candidate-native-notice';area.append(matches);
    const showMatches=list=>{matches.replaceChildren();matches.hidden=!list?.length;for(const match of list||[]){const row=document.createElement('p');row.textContent='Existing candidate matches '+(match.matched_fields||['phone/email']).join(' and ')+': '+match.full_name+'. ';const button=document.createElement('button');button.type='button';button.className='btn tiny outline';button.textContent='View Existing Candidate';button.onclick=()=>bridge.profile(String(match.id),'overview');row.append(button);matches.append(row);}};
    showMatches(result.possible_matches);
    const form=document.createElement('form');form.id='founditRegistrationForm';form.noValidate=true;form.className='candidate-complete';form.style.maxHeight='none';form.style.width='100%';
    const body=document.createElement('div');body.className='edit-body';form.append(body);fields(body,result,true);area.append(form);
    const footer=document.createElement('footer');footer.innerHTML='<details><summary>Separate person with matching contact details</summary><label>Separate-person justification (only if this is a different person)<textarea id="founditSeparateReason" class="control" maxlength="2000"></textarea></label></details><button class="btn primary" type="submit">Save Candidate</button>';form.append(footer);
    form.onsubmit=async e=>{e.preventDefault();if(form.getAttribute('aria-busy')==='true')return;parse.disabled=true;$('clearFoundit').disabled=true;try{return await submitCreation(form,'candidate',async submission=>{
     const errors=nativeFieldErrors(form);
     for(const prefix of ['current','expected'])if(form.elements[prefix+'_salary_inr'].value!==''&&!form.elements[prefix+'_salary_period'].value)errors.push({field:prefix+'_salary_period',message:'Please select the '+prefix+' salary period.'});
     if(!submission.validate(errors))return;
     const v=values(body);for(const key of Object.keys(v.candidate))if(v.candidate[key]===null)delete v.candidate[key];v.candidate.source='FOUNDIT_PASTE';
     const payload={...v,source_digest:result.source_digest,confirmed:true,separate_person_reason:$('founditSeparateReason').value,actor_name:await native.authorize()};
     payload.idempotency_key=native.key(form,'foundit:'+JSON.stringify(payload));
     const saved=await submission.request(native,apiBase+'/foundit/candidates',payload),cid=saved.candidate.id;
     // A committed registration remains successful even if a subsequent refresh fails.
     const success=document.createElement('section');success.className='candidate-native-notice';success.setAttribute('role','status');
     const heading=document.createElement('h3');heading.textContent='Candidate Registered Successfully';success.append(heading);
     const actions=document.createElement('div');actions.className='profile-v9-inline';
     const profile=document.createElement('button');profile.type='button';profile.className='btn primary';profile.textContent='View Candidate Profile';
     profile.onclick=()=>native.run(async()=>{await native.refresh();bridge.profile(String(cid),'overview');},message=>$('founditStatus').textContent=message);
     const another=document.createElement('button');another.type='button';another.className='btn outline';another.textContent='Add Another Candidate';another.onclick=clear;actions.append(profile,another);success.append(actions);area.replaceChildren(success);$('founditStatus').textContent='';
     try{await native.refresh();}catch{const warning=document.createElement('p');warning.textContent='The candidate was saved. The dashboard could not refresh; reload records or open the profile. Do not register this candidate again.';success.append(warning);}
    },error=>{if(error.matches?.length)showMatches(error.matches);});}finally{parse.disabled=false;$('clearFoundit').disabled=false;}};
   }catch(error){$('founditStatus').textContent=error.userFacing?error.message:'Unable to parse this profile. Please review the pasted text and try again.';}
   finally{parse.disabled=false;$('clearFoundit').disabled=false;}
  };
 }
 function section(next){
  if(next!=='search'){unlock();panel.classList.remove('mobile-open');$('detailUnderlay').classList.remove('mobile-open');}
  const placeholder=$('reservedTitle').parentElement;placeholder.hidden=next==='foundit';const host=$('nativeFoundit');if(host)host.hidden=next!=='foundit';if(next==='foundit')foundit();
  if(next==='domains'){$('reservedTitle').textContent='Domain Catalog · V12 replacement pending';const p=$('reservedView').querySelector('p');if(p)p.textContent='The legacy catalog and backend APIs are preserved. A native V12 catalog editor requires separate scope; this control does not leave V12.';}
  const url=new URL(location.href);if(url.pathname!=='/workspace-v12/candidates')return;const before=url.href;if(next==='search')url.searchParams.delete('section');else url.searchParams.set('section',next);if(before!==url.href&&!historyNavigation)history.pushState({},'',url);
 }
 window.addEventListener('popstate',()=>{if(location.pathname==='/workspace-v12/candidates'){historyNavigation=true;bridge.tab(new URL(location.href).searchParams.get('section')||'search');historyNavigation=false;}});
 queueMicrotask(()=>{const url=new URL(location.href);if(url.pathname==='/workspace-v12/candidates'){historyNavigation=true;bridge.tab(url.searchParams.get('section')||'search');if(url.searchParams.has('candidate_id'))bridge.profile(url.searchParams.get('candidate_id'),'overview');if(url.searchParams.get('register')==='1')bridge.registration();historyNavigation=false;}});
 const describe=value=>value&&typeof value==='object'?Object.entries(value).filter(([,v])=>v!=null&&v!=='').map(([k,v])=>k.replaceAll('_',' ')+': '+(typeof v==='object'?JSON.stringify(v):v)).join(' · '):String(value??'');
 return{remember,opened,closed,edit,resumeHTML,bindResume,section,describe,parsedHTML:parsed.html,bindParsed:parsed.bind};
}

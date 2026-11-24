import {sha256} from './crypto.mjs';
// Private versioned JSON/PDF review inside the approved Candidate Desk. No external AI.
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const selectedDrafts=new Map(),selectedPdfs=new Map();
export function parsedResume(native,bridge){
 const root=bridge.root,$=id=>root.getElementById(id),base=cid=>'/api/v12/approved/candidates/'+cid;
 const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const versions=cid=>native.snapshot.resumes.filter(r=>String(r.candidate_id)===String(cid));
 function html(c){
  const docs=versions(c.id).filter(r=>r.resume_kind!=='PARSED_TEXT'),parsed=versions(c.id).filter(r=>r.resume_kind==='PARSED_TEXT');
  return `<div class="profile-v9-panel" id="nativeParsedRoot"><div class="candidate-native-notice" id="nativeParsedStatus" role="status">JSON and PDF source versions stay separate from recruiter approval.</div>
   <div class="profile-v9-multicol"><section class="profile-v9-card"><h3>Structured JSON</h3>
   <label for="parsedJsonSource">Exact source resume version</label><select class="control" id="parsedJsonSource"><option value="">Choose a source version</option>${docs.filter(r=>r.downloadable).map(r=>`<option value="${r.id}">#${r.id} · ${escape(r.resume_kind)} · ${escape(r.original_filename)} · ${escape(r.created_at)}</option>`).join('')}</select>
   <label for="profileParsedFile">Upload structured JSON (.json)</label><input id="profileParsedFile" class="profile-v9-file" type="file" accept=".json,application/json">
   <label for="profileParsedText">Or paste JSON below</label><textarea id="profileParsedText" class="profile-v9-textarea" spellcheck="false" placeholder='{"skills":["Python"],"current_job_title":"Reviewed role"}'></textarea>
   <div class="profile-v9-inline"><button class="btn primary" type="button" id="profilePreviewParsed">Preview extracted details</button><button class="btn outline" type="button" id="parsedUnlock" ${native.directAccess?'hidden style="display:none"':''}>Unlock private history</button></div>
   <p class="profile-v9-prep">Preview saves a preserved, unapproved draft linked to the exact source. Missing and unselected fields do not replace the candidate profile.</p></section>
   <section class="profile-v9-card"><h3>Jobmitra Altered Resume PDF</h3><label for="parsedPdfSource">Select existing altered PDF</label><select class="control" id="parsedPdfSource"><option value="">Choose an altered PDF</option>${docs.filter(r=>r.resume_kind==='JOBMITRA_STANDARD'&&r.downloadable&&/\.pdf$/i.test(r.original_filename||'')).map(r=>`<option value="${r.id}">#${r.id} · ${escape(r.original_filename)} · ${escape(r.created_at)}</option>`).join('')}</select>
   <p class="profile-v9-prep">Selecting a PDF extracts local text and prepares a review draft. Existing Resumes-tab files are reused; no PDF copy is created.</p>
   <div class="profile-v9-inline"><button class="btn outline" type="button" id="parsedPdfDownload" disabled>Download PDF</button><button class="btn outline" type="button" id="parsedPdfExtract" disabled>Extract text &amp; preview</button></div>
   <iframe id="parsedPdfPreview" title="Jobmitra Altered Resume PDF preview" hidden style="width:100%;height:480px;border:1px solid #e1e6ef;margin-top:12px"></iframe>
   <details><summary>Upload an altered PDF when needed</summary><form id="parsedPdfUpload"><label for="parsedPdfFile">Altered resume PDF · up to 10 MB</label><input type="file" id="parsedPdfFile" accept=".pdf,application/pdf" required><label for="parsedPdfPreparation">Preparation source</label><select class="control" id="parsedPdfPreparation">${['ChatGPT','Claude','Manual','Other'].map(x=>'<option>'+x+'</option>').join('')}</select><label for="parsedPdfOriginal">Source original version · optional</label><select class="control" id="parsedPdfOriginal"><option value="">Not linked</option>${docs.filter(r=>r.resume_kind==='ORIGINAL').map(r=>`<option value="${r.id}">#${r.id} · ${escape(r.original_filename)}</option>`).join('')}</select><label for="parsedPdfNotes">Upload notes</label><textarea class="control" id="parsedPdfNotes" maxlength="2000"></textarea><button class="btn primary" type="submit">Upload altered PDF &amp; extract</button></form></details></section></div>
   <section class="profile-v9-card"><h3>Parsed JSON version history</h3><div class="profile-v9-docs">${parsed.map(r=>`<div class="profile-v9-doc"><div><strong>#${r.id} · ${escape(r.original_filename||'Historical JSON')}</strong><small>${escape(r.created_at)} · ${escape(r.review_status||'Historical review required')} · Source ${r.source_resume_id?'#'+r.source_resume_id:'not recorded'}</small></div><div><button class="btn tiny outline" type="button" data-parsed-open="${r.id}">Open review</button><button class="btn tiny outline" type="button" data-parsed-download="${r.id}">Download preserved JSON</button></div></div>`).join('')||'<p class="profile-v9-muted">No parsed versions yet. Earlier drafts and unapproved information will remain here.</p>'}</div></section>
   <section class="profile-v9-card"><h3>Review proposed fields</h3><div id="profileParsedPreview" aria-live="polite"><p class="profile-v9-muted">Upload/paste JSON or select an altered PDF. No candidate fields are changed by preview.</p></div></section>
  </div>`;
 }
 function bind(cid){
  const container=$('nativeParsedRoot');if(!container)return;
  let draft=null,busy=false,uploadedJson=null;const owner={};
  const notice=(text,error=false)=>{const e=container.querySelector('#nativeParsedStatus');e.textContent=text;e.style.color=error?'#a32128':'';};
  async function request(url,body){
   const key=native.key(owner,url+JSON.stringify(body));
   const response=await fetch(url,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'X-Jobmitra-UI':'1','Idempotency-Key':key,'Content-Type':'application/json'},body:JSON.stringify(body)});
   const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Check the required fields and values.');return result;
  }
  async function run(fn){
   if(busy)return;busy=true;container.inert=true;
   try{await fn();}catch(e){notice(e.message,true);}finally{busy=false;container.inert=false;}
  }
  async function download(url,filename,expected){
   await native.authorize();const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});if(!response.ok){let e=await response.json();throw Error(e.detail||'Download was not confirmed.');}
   const blob=await response.blob();const hash=await sha256(await blob.arrayBuffer());
   if(expected&&hash!==expected)throw Error('Downloaded bytes differ from the stored checksum.');
   const a=node('a'),object=URL.createObjectURL(blob);a.href=object;a.download=filename;a.hidden=true;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(object),1000);
  }
  function pdfSource(id){
   $('parsedPdfSource').value=String(id||'');$('parsedPdfDownload').disabled=!id;$('parsedPdfExtract').disabled=!id;
   const frame=$('parsedPdfPreview');frame.hidden=!id;if(id){selectedPdfs.set(String(cid),String(id));frame.src=base(cid)+'/resumes/'+id+'/preview';}else frame.removeAttribute('src');
  }
  async function show(id){
   const current=await native.api(base(cid)+'/parsed-drafts/'+id);if(!container.isConnected)return;
   draft=current;selectedDrafts.set(String(cid),id);const preview=$('profileParsedPreview');preview.replaceChildren();
   const heading=node('p','#'+id+' · '+current.status+' · '+current.created_at);preview.append(heading);
   const source=node('p',current.source?'Exact source: #'+current.source.id+' · '+current.source.original_filename+' · SHA-256 '+(current.source_sha256||current.source.sha256||'not recorded'):'Historical source is not linked to a verified canonical document.');source.className='candidate-resume-meta';preview.append(source);
   if(current.source){$('parsedJsonSource').value=String(current.source.id);pdfSource(current.source.resume_kind==='JOBMITRA_STANDARD'&&/\.pdf$/i.test(current.source.original_filename||'')?current.source.id:null);}
   if(current.json_origin==='serialized_historical_metadata')preview.append(node('p','Original JSON bytes were not recorded for this historical version. Its download serializes the preserved database metadata.'));
   for(const warning of current.warnings)preview.append(node('p',warning));
   if(current.extracted_text){const details=node('details'),summary=node('summary','Extracted PDF text · source evidence');details.append(summary);const pre=node('pre',current.extracted_text);pre.style.whiteSpace='pre-wrap';pre.style.overflowWrap='anywhere';details.append(pre);preview.append(details);}
   if(current.original_json_text!==null){const details=node('details'),summary=node('summary','Preserved original JSON');details.append(summary);const pre=node('pre',current.original_json_text);pre.style.whiteSpace='pre-wrap';details.append(pre);preview.append(details);}
   if(current.identity_confirmation_required){const label=node('label'),check=node('input');check.type='checkbox';check.id='confirmParsedIdentity';label.append(check,document.createTextNode(' I confirm this source belongs to the canonical candidate despite its different name.'));preview.append(label);}
   const selected=[];
   for(const [key,value]of Object.entries(current.proposed_fields)){
    const label=node('label');label.className='candidate-field-review';const check=node('input');check.type='checkbox';check.dataset.parsedReviewField=key;
    const text=node('span');const before=key.startsWith('extra:')?current.current_profile.extra[key.slice(6)]:current.current_profile.candidate[key];
    text.append(node('strong',key+(key==='extra:experience_months'?' · also normalizes experience years':'')),node('p','Current: '+JSON.stringify(before??null)),node('p','Proposed: '+JSON.stringify(value)),node('small','Evidence: '+JSON.stringify(current.field_evidence[key]||{})));
    label.append(check,text);preview.append(label);selected.push(check);
   }
   if(!selected.length)preview.append(node('p',current.status==='APPROVED_FIELDS'?'This reviewed version is preserved. Open its earlier draft to inspect unapproved information.':'No validated structured fields were produced. Text extraction alone is not a successful structured parse. Review the evidence and supply JSON or use Edit Candidate Details.'));
   const actions=node('div');actions.className='profile-v9-inline';const save=node('button','Apply explicitly approved fields');save.id='confirmParsedApply';save.type='button';save.className='btn primary';save.disabled=true;
   selected.forEach(c=>c.onchange=()=>save.disabled=!selected.some(x=>x.checked));
   save.onclick=()=>run(async()=>{
    const actor=await native.authorize(),keys=selected.filter(c=>c.checked).map(c=>c.dataset.parsedReviewField);
    const result=await request(base(cid)+'/parsed-drafts/'+current.id+'/approve',{actor_name:actor,expected_revision:current.profile_revision,approved_fields:keys,identity_confirmed:!!$('confirmParsedIdentity')?.checked});
    selectedDrafts.set(String(cid),result.parsed_version.id);
    const actual=await native.api(base(cid)+'/profile');if(actual.revision===current.profile_revision)throw Error('Database read-back did not confirm approval.');
    await native.refresh();bridge.toast('Selected fields persisted and read back. Unselected fields were not applied; earlier JSON/PDF versions remain preserved.');
   });
   const keep=node('button','Keep draft without applying');keep.id='discardParsedPreview';keep.type='button';keep.className='btn outline';keep.onclick=()=>{selected.forEach(c=>c.checked=false);save.disabled=true;notice('Draft preserved. No proposed field was approved or applied.');};
   const get=node('button','Download preserved JSON');get.type='button';get.className='btn outline';get.onclick=()=>run(()=>download(base(cid)+'/parsed-drafts/'+id+'/download','parsed-resume-'+id+'.json',current.json_sha256));
   actions.append(save,keep,get);preview.append(actions);notice('Source version and review loaded. Only checked fields will be applied; remaining fields stay unchanged.');
  }
  async function extract(id){
   if(!id)throw Error('Choose an existing Jobmitra Altered PDF.');const actor=await native.authorize();pdfSource(id);
   const result=await request(base(cid)+'/resumes/'+id+'/extract',{actor_name:actor});selectedDrafts.set(String(cid),result.id);selectedPdfs.set(String(cid),String(id));
   await native.refresh();bridge.toast('Local extraction draft saved. Review its actual status and field evidence before approval.');
  }
  // Capture original controls before their previous local-only preview handlers run.
  container.addEventListener('change',event=>{
   if(event.target.id!=='profileParsedFile')return;event.stopImmediatePropagation();const file=event.target.files[0];
   run(async()=>{if(!file||!file.name.toLowerCase().endsWith('.json')||file.size>262144)throw Error('Choose a UTF-8 .json file up to 256 KB.');uploadedJson={filename:file.name,json_base64:await native.base64(file)};$('profileParsedText').value=await file.text();notice('JSON bytes loaded for review. Preview will preserve them without applying any fields.');});
  },true);
  $('profileParsedText').oninput=()=>uploadedJson=null;
  container.addEventListener('click',event=>{
   if(!event.target.closest('#profilePreviewParsed'))return;event.stopImmediatePropagation();event.preventDefault();
   run(async()=>{const actor=await native.authorize(),source=Number($('parsedJsonSource').value);if(!source)throw Error('Select the exact original or altered source resume version first.');
    const body={actor_name:actor,source_resume_id:source,...(uploadedJson||{raw_json:$('profileParsedText').value,filename:'pasted-resume.json'})};
    const result=await request(base(cid)+'/parsed-drafts',body);selectedDrafts.set(String(cid),result.id);await native.refresh();bridge.toast('Unapproved JSON draft preserved. No candidate fields changed.');});
  },true);
  $('parsedPdfSource').onchange=()=>run(()=>extract($('parsedPdfSource').value));
  $('parsedPdfExtract').onclick=()=>run(()=>extract($('parsedPdfSource').value));
  $('parsedPdfDownload').onclick=()=>run(async()=>{const record=versions(cid).find(r=>String(r.id)===$('parsedPdfSource').value);if(!record)throw Error('Choose an altered PDF.');await download(`/api/ats-v2/candidates/${cid}/resumes/${record.id}/download`,record.original_filename,record.sha256);});
  $('parsedPdfUpload').onsubmit=event=>{event.preventDefault();run(async()=>{const file=$('parsedPdfFile').files[0];if(!file||!file.name.toLowerCase().endsWith('.pdf'))throw Error('Choose an altered PDF.');const original=$('parsedPdfOriginal').value;
   const record=await native.upload(cid,file,owner,'JOBMITRA_STANDARD',{preparation_source:$('parsedPdfPreparation').value,source_original_id:original?Number(original):null,upload_notes:$('parsedPdfNotes').value},{reuseExisting:true});await extract(record.id);});};
  container.querySelectorAll('[data-parsed-open]').forEach(button=>button.onclick=()=>run(async()=>{await native.authorize();await show(button.dataset.parsedOpen);}));
  container.querySelectorAll('[data-parsed-download]').forEach(button=>button.onclick=()=>run(async()=>{const detail=await native.api(base(cid)+'/parsed-drafts/'+button.dataset.parsedDownload);await download(base(cid)+'/parsed-drafts/'+button.dataset.parsedDownload+'/download','parsed-resume-'+button.dataset.parsedDownload+'.json',detail.json_sha256);}));
  async function initialize(){
   const session=await native.api('/api/v12/access');if(!session.editing){notice('Unlock authorized workspace access to view private PDF/JSON history.');return;}
   const id=selectedDrafts.get(String(cid))||versions(cid).find(r=>r.resume_kind==='PARSED_TEXT')?.id;
   if(id)await show(id);else{const pdf=selectedPdfs.get(String(cid))||versions(cid).find(r=>r.resume_kind==='JOBMITRA_STANDARD'&&r.downloadable&&/\.pdf$/i.test(r.original_filename||''))?.id;if(pdf)pdfSource(pdf);}
  }
  $('parsedUnlock').onclick=()=>run(async()=>{await native.authorize();await initialize();});initialize().catch(e=>notice(e.message,true));
 }
 return {html,bind};
}

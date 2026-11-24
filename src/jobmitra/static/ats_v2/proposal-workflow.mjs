import {uuid} from './crypto.mjs';
// Company PDF workflow in the existing Email Studio overlay. No browser persistence or delivery.
const $=id=>document.getElementById(id),companyId=document.body.dataset.companyId;
const base='/api/v12/approved/companies/'+encodeURIComponent(companyId),requests=new Map();
let context=null,selected=null,epoch=0,busy=false;
const notice=(text,error=false)=>{$('notice').textContent=text;$('notice').classList.toggle('error',error);};
async function api(path,body){
 const headers={'X-Jobmitra-UI':'1'};
 if(body){headers['Content-Type']='application/json';headers['Idempotency-Key']=body.idempotency_key;}
 const response=await fetch(path,{credentials:'same-origin',cache:'no-store',headers,method:body?'POST':'GET',...(body?{body:JSON.stringify(body)}:{})});
 const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Check the fields and valid values.');return data;
}
async function authorize(){
 if(window.parent===window||typeof window.parent.JobmitraProposalAuthorize!=='function')throw Error('Open Prepare Proposal from Companies to authorize this operation.');
 return window.parent.JobmitraProposalAuthorize();
}
async function write(path,body){
 body.actor_name=await authorize();
 const fingerprint=JSON.stringify([path,body]);if(!requests.has(fingerprint))requests.set(fingerprint,uuid());
 return api(path,{...body,idempotency_key:requests.get(fingerprint)});
}
async function run(fn){
 if(busy)return;busy=true;document.querySelector('main').inert=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{await fn();}catch(error){notice(error.message,true);}finally{busy=false;document.querySelector('main').inert=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);$('prepareEmail').disabled=!selected;$('generate').disabled=!context;}
}
function el(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;}
function link(text,url){const a=el('a',text);a.href=url;a.className='button';return a;}
function showVersion(record){
 selected=record;++epoch;$('emailSection').hidden=true;
 $('versionNote').textContent=record.reference+' · '+record.snapshot.company_name+' · '+record.snapshot.fee_percent+'% · '+record.status+' · '+record.issue_date;
 $('pdfPreview').hidden=false;$('pdfPreview').src=base+'/proposals/'+record.id+'/pdf';
 $('download').hidden=false;$('download').href=base+'/proposals/'+record.id+'/pdf?download=true';
 $('prepareEmail').disabled=false;$('evidenceSection').hidden=false;
 $('selectedReference').textContent='Selected version: '+record.reference+' · '+record.snapshot.company_name+' · '+record.snapshot.fee_percent+'%';
 $('signedList').replaceChildren();$('signedChoice').replaceChildren(new Option('Choose a signed copy',''));
 for(const s of record.signed_documents){
  const row=el('p');row.append(link('Download signed copy · '+s.original_filename,base+'/proposals/'+record.id+'/signed-documents/'+s.id),el('small',' · Uploaded '+s.uploaded_at+' by '+s.uploaded_by));$('signedList').append(row);
  $('signedChoice').add(new Option(s.original_filename+' · '+s.uploaded_at,s.id));
 }
 $('eventList').replaceChildren();
 for(const e of record.events){const row=el('div');row.className='history-item';row.append(el('strong',e.status+' · '+e.effective_date),el('p',e.evidence),el('small','Recorded by '+e.recorded_by+(e.authorized_signatory?' · Signatory: '+e.authorized_signatory:'')));$('eventList').append(row);}
 $('statusForm').hidden=['ACCEPTED','DECLINED'].includes(record.status);$('confirmStatus').checked=false;$('evidence').value='';
 $('status').value=record.status==='SENT'?'ACCEPTED':'SENT';$('status').dispatchEvent(new Event('change'));
}
async function refreshHistory(selectedId=selected?.id){
 const result=await api(base+'/proposals');$('history').replaceChildren();
 if(!result.items.length)$('history').append(el('p','No saved proposals for this company.'));
 for(const record of result.items){
  const row=el('div');row.className='history-item';const open=el('button','Open '+record.reference);open.type='button';open.onclick=()=>{if(busy)return;showVersion(record);notice('Showing preserved version '+record.reference+'. Form edits require a new PDF.');};
  row.append(open,el('p',record.snapshot.fee_percent+'% · '+record.status+' · Prepared '+record.created_at+' by '+record.prepared_by),el('code','SHA-256 '+record.pdf_sha256));$('history').append(row);
 }
 const match=result.items.find(p=>p.id===selectedId);if(match)showVersion(match);
}
$('contact').onchange=()=>run(async()=>{
 const version=++epoch;
 const next=await api(base+'/proposal-context?'+new URLSearchParams({company_contact_id:$('contact').value}));
 if(version!==epoch)return;context=next;$('recipient').value=next.recipient_email;
 notice('Active contact loaded. Generate a new PDF to snapshot these details.');
});
$('proposalForm').oninput=()=>{if(selected)notice('Form has unsaved changes. The preview remains '+selected.reference+'. Generate PDF to save a new version.');};
$('proposalForm').onsubmit=event=>{event.preventDefault();run(async()=>{
 if(!$('proposalForm').reportValidity())return;
 const body={company_contact_id:$('contact').value||null,recipient_email:$('recipient').value.trim(),consultant:$('consultant').value.trim(),issue_date:$('issueDate').value,reference:$('reference').value.trim(),fee_percent:document.querySelector('[name="fee"]:checked').value};
 const record=await write(base+'/proposals',body);showVersion(record);await refreshHistory(record.id);
 $('reference').value='';notice('PDF '+record.reference+' saved as Prepared. Nothing has been sent or accepted.');
});};
$('unlock').onclick=()=>run(async()=>{await authorize();await refreshHistory();notice('Company proposal history loaded.');});
$('prepareEmail').onclick=()=>run(async()=>{
 const record=selected,version=++epoch;const draft=await api(base+'/proposals/'+record.id+'/email');if(version!==epoch||selected!==record)return;
 $('emailTo').value=draft.recipient_email;$('emailSubject').value=draft.subject;$('emailBody').value=draft.body;$('emailSection').hidden=false;
 notice('Email draft prepared for '+record.reference+'. Download and manually attach that PDF before sending. Nothing has been sent.');$('emailSection').scrollIntoView({behavior:'smooth',block:'start'});
});
for(const [button,field]of [['copyTo','emailTo'],['copySubject','emailSubject'],['copyBody','emailBody']]){
 $(button).onclick=()=>run(async()=>{if(field==='emailTo'&&(!$(field).value||!$(field).reportValidity()))throw Error('Enter a valid recipient email.');await navigator.clipboard.writeText($(field).value);notice('Copied '+(field==='emailBody'?'email draft. Attach the downloaded PDF manually before sending.':field==='emailTo'?'recipient.':'subject.'));});
}
$('signedForm').onsubmit=event=>{event.preventDefault();run(async()=>{
 const file=$('signedFile').files[0];if(!selected||!file)throw Error('Choose an existing proposal and a signed PDF.');
 if(file.size>10*1024*1024||!file.name.toLowerCase().endsWith('.pdf'))throw Error('Choose a PDF up to 10 MB.');
 const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
 const record=await write(base+'/proposals/'+selected.id+'/signed-documents',{filename:file.name,file_base64:btoa(binary)});
 await refreshHistory(record.id);$('signedFile').value='';notice('Signed copy preserved separately. Proposal status has not changed. Review the evidence before explicitly recording acceptance.');
});};
$('status').onchange=()=>{$('acceptanceFields').hidden=$('status').value!=='ACCEPTED';$('signatory').required=$('status').value==='ACCEPTED';$('signedChoice').required=$('status').value==='ACCEPTED';};
$('statusForm').onsubmit=event=>{event.preventDefault();run(async()=>{
 if(!selected||!$('statusForm').reportValidity())return;
 const accepted=$('status').value==='ACCEPTED';
 const body={status:$('status').value,expected_event_id:selected.latest_event_id,evidence:$('evidence').value.trim(),effective_date:$('effectiveDate').value,confirmed:$('confirmStatus').checked,signed_document_id:accepted?$('signedChoice').value||null:null,authorized_signatory:accepted?$('signatory').value.trim():''};
 const record=await write(base+'/proposals/'+selected.id+'/status',body);await refreshHistory(record.id);notice('Explicit '+record.status+' evidence recorded. Historical PDF bytes are unchanged.');
});};
async function start(){
 context=await api(base+'/proposal-context');$('company').value=context.company_name;
 for(const c of context.contacts)$('contact').add(new Option((c.name||'Contact')+(c.email?' · '+c.email:' · Email not recorded'),c.id));
 if(!context.contacts.length){$('contact').add(new Option('No active contacts recorded',''));$('contact').disabled=true;}
 $('contact').value=context.company_contact_id||'';$('recipient').value=context.recipient_email;$('generate').disabled=false;
 const session=await api('/api/v12/access');if(session.local_development){$('unlock').textContent='Refresh history';}
 if(session.editing)await refreshHistory();
 notice(session.editing?'Company details loaded. Generate PDF to save a proposal version.':'Company details loaded. Unlock workspace access to generate PDFs or view private history.');
}
start().catch(error=>notice(error.message,true));

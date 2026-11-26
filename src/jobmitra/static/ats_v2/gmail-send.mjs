// Optional adapter around the unchanged approved Email Studio document.
import {uuid} from './crypto.mjs';
export const candidateTemplates=new Set(['jobmitra_screening','screening_completed','screening_cleared','interview_scheduled','technical_interview','custom_round','round1_completed','round1_cleared','round2_completed','round2_cleared','final_completed','selected','offer_received','joined','not_selected']);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function emailEntries(events,now=Date.now()){
 const entries=new Map();
 // State snapshots are newest-first; results may arrive before their attempts.
 for(const event of events.filter(e=>e.event_type==='EMAIL_SEND_ATTEMPT')){const p=event.payload||event.payload_json||{};entries.set(p.email_reference,{...p,created_at:event.created_at,candidate_id:event.candidate_id,job_id:event.job_id,jd_candidate_id:event.jd_candidate_id});}
 for(const event of events.filter(e=>e.event_type==='EMAIL_SEND_RESULT')){const p=event.payload||event.payload_json||{};if(entries.has(p.email_reference))Object.assign(entries.get(p.email_reference),p);}
 return [...entries.values()].sort((a,b)=>String(a.created_at).localeCompare(String(b.created_at))).map(e=>({...e,status:e.status==='Sending'&&now-Date.parse(e.created_at)>120000?'Send outcome unknown':e.status}));
}
export function emailHistoryHTML(entries,candidateId){
 const rows=entries.filter(e=>String(e.candidate_id)===String(candidateId));if(!rows.length)return '';
 return '<section class="profile-v9-card"><h3>Email history</h3>'+rows.slice().reverse().map(e=>'<p><strong>'+escape(e.status)+' · Test email</strong><br>'+escape(e.subject)+'<br>To: '+escape(e.actual_recipient)+' · '+escape(e.sent_at||e.created_at)+'<br><small>Reference: '+escape(e.email_reference)+(e.gmail_message_id?' · Gmail: '+escape(e.gmail_message_id):'')+'</small></p>').join('')+'</section>';
}
async function api(path,body){
 const response=await fetch('/api/v12/gmail/'+path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:{'X-Jobmitra-UI':'1',...(body?{'Content-Type':'application/json','Idempotency-Key':body.reference}:{})},...(body?{body:JSON.stringify(body)}:{})});
 const data=await response.json();if(!response.ok){const error=Error(typeof data.detail==='string'?data.detail:'Gmail request could not be confirmed.');error.httpStatus=response.status;throw error;}return data;
}
export async function bindGmailSend(frame,context){
 const doc=frame.contentDocument,bar=doc.createElement('div'),state=doc.createElement('span'),button=doc.createElement('button'),result=doc.createElement('p'),resend=doc.createElement('button');
 bar.style.cssText='display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:12px 0';state.setAttribute('role','status');result.setAttribute('role','status');result.style.cssText='width:100%;margin:0;font-size:13px';button.type=resend.type='button';button.className=resend.className='primary-btn';button.textContent='Send Email';resend.textContent='Resend Email';resend.hidden=true;bar.append(state,button,resend,result);doc.querySelector('.preview-top').after(bar);
 let connection,reference=uuid(),last=null,busy=false,pending=null,uncertain=false;
 const eligible=()=>candidateTemplates.has(doc.getElementById('candidateStatus').value)&&context?.candidateId&&(!context.candidates||context.candidates.length===1);
 const update=()=>{button.disabled=busy||!!last||uncertain||!connection?.enabled||!eligible();button.hidden=!candidateTemplates.has(doc.getElementById('candidateStatus').value);button.style.display=button.hidden?'none':'';button.style.opacity=button.disabled?'.55':'1';button.style.cursor=button.disabled?'not-allowed':'pointer';resend.disabled=busy||!connection?.enabled||!eligible();resend.style.display=!last||last.status==='Sending'||!eligible()?'none':'';};
 state.textContent='Checking Gmail connection…';update();
 doc.getElementById('candidateStatus').addEventListener('change',update);
 try{connection=await api('status');state.textContent=connection.status+(connection.enabled?' · Test Mode — Emails sent to '+connection.actual_recipient:'');if(connection.detail)result.textContent=connection.detail;}catch{state.textContent='Gmail Unavailable';}
 if(!context?.candidateId)result.textContent='Open an existing candidate profile or JD History email shortcut to enable sending. Manual copy remains available.';
 const show=entry=>{last=entry;if(entry.reconnect_required){connection.enabled=false;state.textContent='Reconnect Required';}result.textContent=entry.status+' · Test email · '+entry.email_reference+(entry.gmail_message_id?' · Gmail message '+entry.gmail_message_id:'')+(entry.failure_reason?' · '+entry.failure_reason:'');resend.hidden=entry.status==='Sending';update();window.dispatchEvent(new Event('jobmitra-email-history-update'));if(entry.status==='Accepted by Gmail')doc.defaultView.dispatchEvent(new Event('jobmitra-email-sent'));};
 async function submit(isResend=false){
  if(busy||!connection?.enabled||!eligible())return;
  if(!doc.defaultView.JobmitraEmailStudioCopyAllowed?.())return;
  const subject=doc.getElementById('emailSubject').value,recipient=doc.getElementById('recipientEmail').value.trim();
  if(!doc.defaultView.confirm((isResend?'Send another copy? This may duplicate an earlier accepted/unknown email.\n':'Send this reviewed test email?\n')+'To: '+connection.actual_recipient+'\nSubject: '+subject))return;
  if(isResend){reference=uuid();pending=null;}
  const body=doc.getElementById('emailBody');
  pending??={reference,candidate_id:Number(context.candidateId),job_id:context.jobId?Number(context.jobId):null,company_id:context.companyId||null,template_id:doc.getElementById('candidateStatus').value,intended_recipient:recipient,actual_recipient:connection.actual_recipient,subject,html:body.firstElementChild.outerHTML,plain:body.innerText,...(isResend?{resend_of:last.email_reference,confirm_resend:true}:{})};
  busy=true;update();result.textContent='Sending…';
  try{show(await api('send',pending));}catch(error){
   // Never silently allocate another reference or repeat a possibly accepted POST.
   result.textContent=error.message+' Check email history before any intentional resend.';
   if(error.httpStatus>=400&&error.httpStatus<500)pending=null;else uncertain=true;
   try{const data=await api('history/'+context.candidateId),entry=data.items.find(e=>e.email_reference===reference);if(entry)show(entry);}catch{}
  }finally{busy=false;update();}
 }
 button.addEventListener('click',()=>submit());resend.addEventListener('click',()=>submit(true));update();
 // The prototype's privacy footer is factual only for manual copy. Keep template
 // bytes unchanged; explain the explicitly enabled service in surrounding help.
 if(connection?.enabled){const note=doc.querySelector('body > .note');if(note)note.textContent='Gmail test sending is enabled for the existing Pooja sample candidate only. Review recipient and preview, then explicitly confirm Send Email. Copy workflows remain available. Gmail acceptance does not confirm delivery.';const network=doc.querySelector('.header-right > span:first-child');if(network)network.textContent='Local Mac development';const badge=doc.querySelector('.local-badge');if(badge)badge.lastChild.textContent=' Gmail test mode';const help=frame.ownerDocument.querySelector('.studio-head small');if(help)help.textContent='Review and confirm before sending · Test recipient only';}
}

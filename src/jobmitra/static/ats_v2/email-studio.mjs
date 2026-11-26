// Integration only: approved documents own their templates, wording and rendering.
import {bindGmailSend} from './gmail-send.mjs';
import {contextualEmailDocument} from './email-context.mjs';
const sessions=new WeakMap(),frames=new Set();
const fingerprint=doc=>JSON.stringify([...doc.querySelectorAll('input,select,textarea,[contenteditable="true"]')].map(e=>[e.id||e.name,e.type==='checkbox'||e.type==='radio'?e.checked:e.isContentEditable?e.innerHTML:e.value]));
export const hasEmailChanges=frame=>{const s=sessions.get(frame);return !!(s&&frame.contentDocument&&fingerprint(frame.contentDocument)!==s.baseline);};
export function allowEmailReplacement(frame,key){
 const s=sessions.get(frame);
 return !s||s.key===key||!hasEmailChanges(frame)||window.confirm('This email has unsaved edits. Replace it with the new context?');
}
function remember(frame,key){sessions.set(frame,{key,baseline:fingerprint(frame.contentDocument)});frames.add(frame);}
window.addEventListener('beforeunload',event=>{if([...frames].some(f=>f.isConnected&&hasEmailChanges(f))){event.preventDefault();event.returnValue='';}});

export async function copyEmailContent(doc,html,text){
 let supplied=false;
 const onCopy=event=>{if(!event.clipboardData)return;event.clipboardData.setData('text/plain',text);if(html)event.clipboardData.setData('text/html',html);event.preventDefault();supplied=true;};
 const selection=doc.defaultView.getSelection(),ranges=[];
 for(let i=0;i<selection.rangeCount;i++)ranges.push(selection.getRangeAt(i));
 const node=doc.createElement('div');node.style.cssText='position:fixed;left:-10000px;top:0';if(html)node.innerHTML=html;else node.textContent=text;doc.body.append(node);
 const range=doc.createRange();range.selectNodeContents(node);selection.removeAllRanges();selection.addRange(range);doc.addEventListener('copy',onCopy);
 try{if(doc.execCommand('copy')&&supplied)return true;}catch{}finally{doc.removeEventListener('copy',onCopy);selection.removeAllRanges();for(const r of ranges)selection.addRange(r);node.remove();}
 try{const win=doc.defaultView;if(html&&win.navigator.clipboard?.write&&win.ClipboardItem){await win.navigator.clipboard.write([new win.ClipboardItem({'text/html':new Blob([html],{type:'text/html'}),'text/plain':new Blob([text],{type:'text/plain'})})]);return true;}if(!html&&win.navigator.clipboard?.writeText){await win.navigator.clipboard.writeText(text);return true;}}catch{}
 return false;
}
function notice(doc,message){let node=doc.getElementById('integratedEmailNotice');if(!node){node=doc.createElement('p');node.id='integratedEmailNotice';node.setAttribute('role','status');node.style.cssText='margin:12px;padding:12px;background:#fff6f6;color:#92303a;border:1px solid #efd5d8;border-radius:8px';doc.body.prepend(node);}node.textContent=message;}
function bindCopy(doc,ids,subjectId){
 for(const id of ids){const button=doc.getElementById(id);if(!button)continue;button.addEventListener('click',async event=>{
  event.preventDefault();event.stopImmediatePropagation();
  // Retain the composer's existing required-field/confidentiality validation.
  const allowed=doc.defaultView.JobmitraEmailStudioCopyAllowed||doc.defaultView.JobmitraProposalCopyAllowed;if(!allowed?.())return;
  const body=doc.getElementById('emailBody'),subject=doc.getElementById(subjectId),isSubject=id.toLowerCase().includes('subject');
  const text=isSubject?(subject.value??subject.textContent):body.innerText;
  const ok=await copyEmailContent(doc,isSubject?null:body.firstElementChild?.outerHTML,text);
  notice(doc,ok?(isSubject?'Subject copied.':'Formatted email copied. Review the recipient and manually attach any required document before sending.'):'Automatic copy unavailable. Select the preview and copy it manually.');
 },true);}
}
async function load(frame,html){
 await new Promise((resolve,reject)=>{frame.onload=()=>{if(!frame.contentDocument){reject(Error('Email Studio could not be loaded.'));return;}resolve();};frame.srcdoc=html;});
}
export async function loadCandidateEmail(frame,html,context,key='manual:updates'){
 if(sessions.get(frame)?.key===key)return true;
 if(!allowEmailReplacement(frame,key))return false;
 const bridge='window.JobmitraEmailStudio=Object.freeze({setContext:applyStudioContext});';
 if(!html.includes(bridge))throw Error('Approved Email Studio validation bridge is unavailable.');
 await load(frame,contextualEmailDocument(html).replace(bridge,bridge+'window.JobmitraEmailStudioCopyAllowed=validate;'));
 const doc=frame.contentDocument,win=frame.contentWindow;
 if(context){doc.getElementById('roundName').value=context.roundName||'';win.JobmitraEmailStudio.setContext(context);}
 const sample=doc.getElementById('sampleBtn');sample.hidden=!context;
 if(context){sample.textContent='Reload candidate details';sample.addEventListener('click',event=>{event.stopImmediatePropagation();if(hasEmailChanges(frame)&&!window.confirm('Replace unsaved edits with the candidate details?'))return;win.JobmitraEmailStudio.setContext(context);remember(frame,key);},true);}
 bindCopy(doc,['copyEmailBtn','copySubjectBtn'],'emailSubject');void bindGmailSend(frame,context).catch(()=>notice(doc,'Gmail is unavailable. Existing manual copy remains available.'));win.addEventListener('jobmitra-email-sent',()=>remember(frame,key));remember(frame,key);return true;
}

export async function loadProposalEmail(frame,context=null){
 const key=context?'proposal:'+context.companyId+':'+context.proposalId:'manual:proposal';
 if(sessions.get(frame)?.key===key)return true;
 if(!allowEmailReplacement(frame,key))return false;
 await new Promise((resolve,reject)=>{frame.onload=()=>frame.contentDocument?resolve():reject(Error('Approved Company Proposal Email Studio is unavailable.'));frame.removeAttribute('srcdoc');frame.src='/email/proposal';});const doc=frame.contentDocument;
 const fields=doc.querySelector('.fields'),recipient=doc.createElement('input');recipient.id='proposalEmailRecipient';recipient.type='email';recipient.maxLength=254;recipient.placeholder='Enter recipient email if not recorded';
 const label=doc.createElement('label');label.htmlFor=recipient.id;label.textContent='To · editable';label.append(recipient);fields.prepend(label);
 const help=doc.createElement('p');help.setAttribute('role','status');label.after(help);
 const recipientHint=()=>{help.textContent=recipient.value.trim()?'Verify the recipient before sending.':'No recipient email recorded. Enter it manually before sending.';};recipient.addEventListener('input',recipientHint);
 if(context){
  doc.getElementById('clientName').value=context.companyName;recipient.value=context.recipientEmail||'';
  if(context.contactName){const greeting='Dear '+context.contactName+',';doc.getElementById('salutation').add(new Option(greeting,greeting));doc.getElementById('salutation').value=greeting;}
  const box=doc.querySelector('.docbox');box.querySelector('strong').textContent='Company Proposal · '+context.feePercent+'% Annual CTC';box.querySelector('small').textContent='PDF · '+context.reference;
  const button=doc.getElementById('downloadProposal');button.textContent='↓ Download selected proposal PDF';button.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();const a=doc.createElement('a');a.href=context.downloadUrl;a.download='';a.click();},true);
  box.querySelector('.disclaimer').textContent='Selected preserved PDF: '+context.reference+'. Download and attach it manually. The PDF is not attached automatically.';
  doc.querySelector('.hero p')?.replaceChildren(doc.createTextNode('Review the branded email and manually attach the selected proposal PDF.'));
  for(const p of doc.querySelectorAll('p,.confirm,.hint,.previewfoot span,.notice'))if(!doc.getElementById('emailBody').contains(p)&&(p.textContent.includes('Word')||p.textContent.includes('DOCX')))p.textContent='Download the selected PDF → Copy subject and formatted email → Paste into your mail application → Attach the PDF manually. Nothing has been sent.';
  doc.getElementById('clientName').dispatchEvent(new Event('input',{bubbles:true}));
  notice(doc,context.companyName+' · '+context.reference+' · '+context.feePercent+'% · No PDF attached and no email sent.');
 }
 recipientHint();
 // Keep original proposal validation/copy handlers, but supply explicit rich bytes
 // during their legacy copy event so HTTP copies cannot reuse a stale subject.
 let copying=null;for(const id of ['copyEmail','copySubject'])doc.getElementById(id).addEventListener('click',()=>{copying=id;setTimeout(()=>{copying=null;},0);},true);
 doc.addEventListener('copy',event=>{if(!copying||!event.clipboardData)return;const body=doc.getElementById('emailBody');event.clipboardData.setData('text/plain',copying==='copySubject'?doc.getElementById('subjectText').textContent:body.innerText);if(copying==='copyEmail')event.clipboardData.setData('text/html',body.firstElementChild.outerHTML);event.preventDefault();});
 if(context){const toast=doc.getElementById('toast');new MutationObserver(()=>{if(toast.textContent.includes('Word proposal'))toast.textContent=toast.textContent.replace(/(?:downloaded )?Word proposal/g,'selected PDF');}).observe(toast,{childList:true,characterData:true,subtree:true});}
 remember(frame,key);return true;
}

export function installEmailWorkspace(html){
 const root=document.getElementById('emailHost'),home=document.getElementById('emailHome'),tool=document.getElementById('emailTool'),host=document.getElementById('emailFrames'),cache=new Map();let epoch=0;
 async function render(){
  if(location.pathname.replace(/\/$/,'')!=='/workspace-v12/email')return;
  const request=++epoch,name=new URL(location.href).searchParams.get('tool'),known=['updates','submission','proposal'].includes(name);
  home.hidden=known;tool.hidden=!known;for(const f of cache.values())f.hidden=true;if(!known)return;
  try{let frame=cache.get(name);if(!frame){frame=document.createElement('iframe');frame.id='emailWorkspace-'+name;frame.title=name==='proposal'?'Company Proposal Email Studio':'Candidate Email Studio';frame.allow='clipboard-write; clipboard-read';host.append(frame);cache.set(name,frame);const ok=name==='proposal'?await loadProposalEmail(frame):await loadCandidateEmail(frame,html,name==='submission'?{status:'candidate_submission'}:null,'manual:'+name);if(!ok)return;const size=()=>{frame.style.height=Math.max(900,frame.contentDocument?.documentElement.scrollHeight||0)+'px';};new ResizeObserver(size).observe(frame.contentDocument.body);size();}if(request===epoch)frame.hidden=false;
  }catch(error){document.getElementById('emailWorkspaceNotice').textContent=error.message;}
 }
 root.addEventListener('click',event=>{const a=event.target.closest('a');if(!a||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;const url=new URL(a.href);if(url.origin!==location.origin||url.pathname!=='/workspace-v12/email')return;event.preventDefault();history.pushState({},'',url);void render();});
 window.addEventListener('popstate',render);new MutationObserver(()=>{if(!root.hidden)void render();}).observe(root,{attributes:true,attributeFilter:['hidden']});void render();
}

export function installContextualEmail(native,html,resolve){
 window.addEventListener('jobmitra-email-history-update',()=>void native.run(()=>native.refresh()));
 const overlay=document.getElementById('emailStudioOverlay'),frame=document.getElementById('emailStudioFrame'),heading=overlay.querySelector('.studio-head strong'),original=heading.textContent;let lastFocus=null,epoch=0;
 const close=()=>{overlay.hidden=true;lastFocus?.focus?.();};
 const present=()=>{lastFocus=document.activeElement;heading.textContent=original;frame.hidden=false;const p=document.getElementById('proposalStudioFrame');if(p)p.hidden=true;overlay.hidden=false;document.getElementById('closeEmailStudio').focus();};
 window.JobmitraUnified.openEmailStudio=context=>native.run(async()=>{const request=++epoch;context=await resolve(native,context);if(request!==epoch)return;const key=JSON.stringify([context.jobId,context.candidateId,context.viewStage,context.status,context.roundName,context.companyId,context.companyName,context.candidateName,context.candidateEmail,context.companyContacts,context.candidates?.map(c=>c.id)]);if(await loadCandidateEmail(frame,html,context,key))present();});
 window.JobmitraUnified.openProfileEmail=id=>native.run(async()=>{
  const person=await native.api('/api/ats-v2/candidates/'+encodeURIComponent(id));
  const memberships=native.jobs.filter(j=>j.candidates.some(c=>c.id===String(id)));
  if(memberships.length===1)return window.JobmitraUnified.openEmailStudio({jobId:memberships[0].id,candidates:[{id:String(id)}]});
 if(await loadCandidateEmail(frame,html,{candidateId:String(person.id),status:'jobmitra_screening',candidateName:person.full_name,candidateEmail:person.email||'',jobTitle:person.job_title||'',companyName:'',location:person.current_city||''},'profile:'+id)){notice(frame.contentDocument,'Candidate draft. Select and review an approved template; no JD stage or selection has been recorded. Use JD History for a specific membership.');present();}
 });
 document.getElementById('candidateHost').shadowRoot.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.dataset.emailProfile)void window.JobmitraUnified.openProfileEmail(b.dataset.emailProfile);if(b.dataset.emailJob)void window.JobmitraUnified.openEmailStudio({jobId:b.dataset.emailJob,candidates:[{id:b.dataset.emailCandidate}]});});
 document.getElementById('closeEmailStudio').addEventListener('click',close);overlay.addEventListener('click',event=>{if(event.target===overlay)close();});document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!overlay.hidden){event.stopPropagation();close();}});
}

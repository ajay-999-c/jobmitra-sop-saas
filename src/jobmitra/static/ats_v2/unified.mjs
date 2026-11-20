import {$,$$,api,save,esc,field,dialog,notice,error,bindErrors} from './shared.mjs';

export const unified=Boolean(document.body.dataset.unifiedV12!==undefined);
export const v12=(path,options={})=>api('/api/v12'+path,options);
export const v12save=(path,data,method='POST')=>save('/api/v12'+path,data,method);
export const key=()=>crypto.randomUUID();
export const actorField=()=>field('actor_name','Recorded by · declared name','',{required:true});

function rewriteLinks(){
  $$('a[href]').forEach(a=>{
    const url=new URL(a.href,location.origin);if(url.origin!==location.origin)return;
    const mapped=url.pathname==='/candidate-search-v2'?'/workspace-v12/candidates':url.pathname==='/jd-workspace-v2'?'/workspace-v12/jobs':null;
    const profile=url.pathname.match(/^\/ats-v2\/candidates\/(\d+)$/);
    if(mapped){url.pathname=mapped;a.setAttribute('href',url.pathname+url.search);}
    else if(profile){url.pathname='/workspace-v12/candidates';url.searchParams.set('candidate',profile[1]);a.setAttribute('href',url.pathname+url.search);}
  });
}

async function accessState(){
  const state=await v12('/access');
  $('#v12-access').textContent=state.editing?'Lock editing':'Unlock editing';
  $('#v12-access').dataset.editing=String(state.editing);
}

if(unified){
  rewriteLinks();new MutationObserver(rewriteLinks).observe(document.body,{childList:true,subtree:true});
  $('#v12-access').onclick=bindErrors(async()=>{
    if($('#v12-access').dataset.editing==='true'){await v12('/access',{method:'DELETE'});await accessState();notice('Editing locked.');return;}
    dialog('Unlock workspace editing',`${field('token','Operator or supervisor access key','',{type:'password',required:true})}<p class="ats-hint">Use an approved workspace access key. Each saved outcome also records your declared name.</p>`,'Unlock',async(data,form)=>{
      await v12save('/access',{token:data.token});form.reset();await accessState();notice('Editing is enabled for this session.');
    });
  });
  accessState().catch(error);
}

let emailContext=null;
async function showEmail(candidate,job,audience='CANDIDATE',contact=null){
  const query=new URLSearchParams({candidate_id:candidate,job_id:job,audience});if(contact)query.set('contact_id',contact);
  emailContext=await v12('/email-context?'+query);
  const c=emailContext;
  $('#v12-email-content').innerHTML=`<div class="v12-email-body"><label>Audience<select id="v12-email-audience"><option value="CANDIDATE" ${audience==='CANDIDATE'?'selected':''}>Candidate update</option><option value="COMPANY" ${audience==='COMPANY'?'selected':''}>Company submission</option></select></label>${audience==='COMPANY'?`<label>Company contact<select id="v12-email-contact"><option value="">Choose a contact</option>${c.contacts.map(r=>`<option value="${esc(r.id)}" ${r.id===c.selected_contact_id?'selected':''}>${esc(r.name||'Contact')} · ${esc(r.email||'Email not recorded')}</option>`).join('')}</select></label>`:''}<label>Recipient email · editable<input id="v12-email-recipient" type="email" value="${esc(c.recipient_email||'')}" placeholder="Email not recorded"></label><label>Subject · editable<input id="v12-email-subject" value="${esc(c.subject)}"></label><label>Preview<textarea id="v12-email-body" readonly>${esc(c.body)}</textarea></label><p class="ats-hint">${c.company_disclosed?'Company details are available in this context.':'Client company details remain confidential before selection.'} Previewing and copying do not send email or change recruitment history.</p><div class="ats-actions"><button class="ats-btn ats-secondary" id="v12-copy-recipient" type="button">Copy recipient</button><button class="ats-btn ats-secondary" id="v12-copy-subject" type="button">Copy subject</button><button class="ats-btn" id="v12-copy-body" type="button">Copy email body</button>${(audience==='COMPANY'||['PENDING_JOINING','JOINED_CONFIRMED'].includes(c.selection_outcome))?'<button class="ats-btn ats-secondary" id="v12-full-studio" type="button">Open full Email Studio</button>':''}</div><div id="v12-studio-frame"></div></div>`;
  $('#v12-email-audience').onchange=bindErrors(e=>showEmail(candidate,job,e.target.value));
  if($('#v12-email-contact'))$('#v12-email-contact').onchange=bindErrors(e=>showEmail(candidate,job,audience,e.target.value));
  for(const [button,input] of [['recipient','recipient'],['subject','subject'],['body','body']]){
    $('#v12-copy-'+button).onclick=bindErrors(async()=>{
      const node=$('#v12-email-'+input);if(!node.value.trim()||!node.checkValidity())throw Error('Enter a valid '+input+' before copying.');
      await navigator.clipboard.writeText(node.value);notice('Copied. No email was sent.');
    });
  }
  if($('#v12-full-studio'))$('#v12-full-studio').onclick=()=>{
    const frame=document.createElement('iframe');frame.title='Existing Email Studio · review and copy';frame.src=audience==='COMPANY'?'/email/submission':'/email/updates';
    $('#v12-studio-frame').replaceChildren(frame);
    frame.onload=()=>{
      const doc=frame.contentDocument;const Event=frame.contentWindow.Event;
      const set=(id,value)=>{const node=doc.getElementById(id);if(node){node.value=value||'';node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}));}};
      set('companyName',c.company_name);set('candidateName',c.candidate_name);set('jobPosition',c.job_title);set('jobLocation',c.location);set('contactPerson',c.recipient_name);set('emailJobTitle',c.job_title);set('joiningDate',c.joined_on);
      if(audience==='CANDIDATE')set('candidateStatus',c.stage==='JOINED'?'joined':'selected');
      else {
        const ctc=prefix=>c[prefix+'_salary_basis']==='CTC'&&c[prefix+'_salary_inr']!=null?`₹${Number(c[prefix+'_salary_inr']).toLocaleString('en-IN')} · ${c[prefix+'_salary_period']?c[prefix+'_salary_period'].toLowerCase():'period not recorded'}`:'';
        const fields={name:c.candidate_name,experience:c.experience_years==null?'':c.experience_years+' years',notice:c.notice_days==null?'':c.notice_days+' days',expectedCtc:ctc('expected'),ctc:ctc('current')};
        for(const [name,value] of Object.entries(fields)){const node=doc.querySelector(`[data-field="${name}"]`);if(node){node.value=value;node.dispatchEvent(new Event('input',{bubbles:true}));}}
      }
    };
  };
  const modal=$('#v12-email-dialog');if(!modal.open)modal.showModal();
}

if(unified){
  $('#v12-email-close').onclick=()=>$('#v12-email-dialog').close();
  document.addEventListener('click',bindErrors(async event=>{
    const button=event.target.closest('[data-v12-email]');
    if(button)await showEmail(button.dataset.v12Email,button.dataset.v12Job);
  }));
}

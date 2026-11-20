import {$,$$,esc,pretty,pill,empty,field,dialog,notice,error,bindErrors,date} from './shared.mjs';
import {v12,v12save,key,actorField} from './unified.mjs';

const params=new URLSearchParams(location.search);
const state={page:1,pageSize:20,q:params.get('q')||'',companyId:params.get('company')||'',company:null,tab:'placements',scope:false,directory:null,reportVersion:0};
const statusTone=status=>status==='JOINED_CONFIRMED'?'ats-green':status==='PENDING_JOINING'?'ats-amber':status.includes('CANCEL')||status==='NOT_JOINED'?'ats-red':'';
function table(headings,rows){return `<div class="v12-table-scroll"><table class="v12-table"><thead><tr>${headings.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;}

async function analytics(){
  const version=++state.reportVersion;const form=$('#v12-period-form');const period=form.elements.period.value;
  const query=new URLSearchParams({period});if(period==='custom'){query.set('start',form.elements.start.value);query.set('end',form.elements.end.value);}
  if(state.companyId&&state.scope)query.set('company_id',state.companyId);
  const data=await v12('/placements?'+query);if(version!==state.reportVersion)return;
  $('#v12-report-range').textContent=`${date(data.start)} – ${date(data.end)} · ${data.timezone} · ${query.has('company_id')?state.company.company_name:'All companies'}`;
  const m=data.metrics;
  $('#v12-metrics').innerHTML=[['Confirmed placements',m.confirmed_placements,'Actual joining confirmed'],['Company selections',m.company_selections,'Selected in this period'],['Awaiting joining',m.awaiting_joining,'Selected, joining pending'],['Companies with joinings',m.companies_with_joinings,'Confirmed joining in this period']].map(([label,value,note])=>`<div class="v12-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join('');
  const max=Math.max(1,...data.trend.map(r=>r.confirmed_placements));const width=720,step=width/Math.max(1,data.trend.length);
  const bars=data.trend.map((r,i)=>{const height=r.confirmed_placements/max*82;return `<rect class="v12-bar" x="${i*step+2}" y="${96-height}" width="${Math.max(1,step-4)}" height="${height}" rx="2"><title>${esc(r.date)}: ${r.confirmed_placements} confirmed joinings</title></rect>`;}).join('');
  $('#v12-trend').innerHTML=`<svg viewBox="0 0 720 128" role="img" aria-label="${m.confirmed_placements} confirmed joinings in this period"><line class="v12-chart-base" x1="0" y1="98" x2="720" y2="98"></line>${bars}<text class="v12-chart-label" x="0" y="121">${esc(data.trend[0]?.date||data.start)}</text><text class="v12-chart-label" x="720" y="121" text-anchor="end">${esc(data.trend.at(-1)?.date||data.end)}</text></svg>`;
}

async function directory(){
  const query=new URLSearchParams({q:state.q,page:state.page,page_size:state.pageSize});const data=await v12('/companies?'+query);state.directory=data;
  $('#v12-company-count').textContent=`${data.total} compan${data.total===1?'y':'ies'}`;
  $('#v12-company-list').innerHTML=data.items.map(c=>`<button class="v12-company-option" type="button" data-company="${esc(c.id)}" aria-current="${c.id===state.companyId}"><strong>${esc(c.company_name)}</strong><small>${esc([c.city,c.state].filter(Boolean).join(', ')||'Location not recorded')} · ${c.contact_count} contact${c.contact_count===1?'':'s'}</small></button>`).join('')||empty('No companies match','Try another company name.');
  const max=Math.max(1,Math.ceil(data.total/state.pageSize));$('#v12-company-pages').innerHTML=`<button class="ats-btn ats-secondary ats-small" type="button" data-company-page="${state.page-1}" ${state.page<=1?'disabled':''}>Previous</button><span>${state.page} / ${max}</span><button class="ats-btn ats-secondary ats-small" type="button" data-company-page="${state.page+1}" ${state.page>=max?'disabled':''}>Next</button>`;
}

function placementRows(records){
  if(!records.length)return empty('No company selections yet','Candidates selected through a linked JD will appear here.');
  return table(['Candidate / JD','Outcome','Selection','Actual joining','Journey'],records.map(r=>`<tr><td><a href="/workspace-v12/candidates?candidate=${r.candidate_id}">${esc(r.full_name)}</a><small>${esc(r.jd_code)} · ${esc(r.job_title)}</small></td><td>${pill(pretty(r.effective_status),statusTone(r.effective_status))}<small>${esc(pretty(r.allocation_eligibility))}</small></td><td>${esc(date(r.selected_on))}</td><td>${r.selection_outcome==='JOINED_CONFIRMED'?esc(date(r.joined_on)):'Not confirmed'}</td><td><a href="/workspace-v12/jobs?view=pipeline&job=${r.job_id}">Open JD →</a><button class="ats-link" type="button" data-v12-email="${r.candidate_id}" data-v12-job="${r.job_id}">Email preview</button></td></tr>`));
}

function details(){
  const c=state.company;if(!c)return;
  let body;
  if(state.tab==='placements')body=`<div class="v12-quiet">Selection is a hiring milestone. Only a separately confirmed actual joining counts as a successful placement.</div>${placementRows(c.placements)}`;
  else if(state.tab==='jobs')body=c.jobs.length?table(['Job requirement','Status','Target',''],c.jobs.map(j=>`<tr><td><strong>${esc(j.title)}</strong><small>${esc(j.jd_code)}</small></td><td>${pill(pretty(j.status))}</td><td>${esc(date(j.target_date))}</td><td><a href="/workspace-v12/jobs?job=${j.id}&view=pipeline">Open →</a></td></tr>`)):empty('No linked JDs','Create a JD and select this company.');
  else if(state.tab==='history')body=c.audit.length?c.audit.map(e=>`<article class="ats-history"><b>${esc(pretty(e.action))}</b><time>${esc(date(e.created_at))} IST</time><p>Recorded by ${esc(e.actor_name_snapshot||'Source import')} · ${esc(pretty(e.actor_verification_status||'Not attributed'))}</p><details><summary>View recorded changes</summary><pre>${esc(JSON.stringify({before:e.before_json,after:e.after_json},null,2))}</pre></details></article>`).join(''):empty('No company edits recorded','Existing company records were preserved without inventing past audit events.');
  else body=`<dl class="v12-company-facts">${[['Address',c.address_line],['City',c.city],['State',c.state],['Postal code',c.postal_code],['General phones',c.general_phone_numbers.join(', ')]].map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v||'Not recorded')}</dd></div>`).join('')}</dl><h3>Company contacts</h3>${c.contacts.length?table(['Contact','Designation','Phone','Email'],c.contacts.map(r=>`<tr><td>${esc(r.contact_name||'Not recorded')}</td><td>${esc(r.designation||'Not recorded')}</td><td>${esc((r.phone_numbers||[]).join(', ')||'Not recorded')}</td><td>${esc(r.email||'Not recorded')}${r.is_primary_email?'<small>Primary email contact</small>':''}</td></tr>`)):empty('No contacts recorded')}<button class="ats-btn ats-secondary" id="v12-edit-company" type="button">Edit details & contact emails</button>`;
  $('#v12-company-detail').innerHTML=`<div class="v12-detail-title"><div><p>COMPANY WORKSPACE</p><h2>${esc(c.company_name)}</h2><p>${esc([c.city,c.state].filter(Boolean).join(', ')||'Location not recorded')}</p></div>${pill(c.is_active?'Active':'Archived',c.is_active?'ats-green':'')}</div><label class="ats-check"><input type="checkbox" id="v12-report-scope" ${state.scope?'checked':''}> Show dashboard for this company</label><div class="v12-company-tabs" role="tablist" aria-label="Company views">${[['placements','Placement register'],['jobs','Linked JDs'],['details','Details & contacts'],['history','Audit history']].map(([k,label])=>`<button type="button" role="tab" data-company-tab="${k}" aria-selected="${state.tab===k}">${label}</button>`).join('')}</div><div>${body}</div>`;
  $('#v12-report-scope').onchange=bindErrors(async e=>{state.scope=e.target.checked;await analytics();});
  if($('#v12-edit-company'))$('#v12-edit-company').onclick=editCompany;
}

async function chooseCompany(id){
  state.companyId=id;state.company=await v12('/companies/'+encodeURIComponent(id));details();if(state.scope)await analytics();
  const url=new URL(location.href);url.searchParams.set('company',id);history.replaceState(null,'',url.pathname+url.search);await directory();
}

function editCompany(){
  const c=state.company,requestKey=key();
  dialog('Company details & contact emails',`<div class="ats-form-grid">${field('company_name','Company name',c.company_name,{required:true,span:true})}${field('address_line','Address',c.address_line||'',{span:true})}${field('city','City',c.city||'')}${field('state','State',c.state||'')}${field('postal_code','Postal code',c.postal_code||'')}${actorField()}</div><h3>Contact email addresses</h3><p class="ats-hint">Only email fields are edited here. Existing contact IDs, names, designations and phone arrays are retained.</p>${c.contacts.map(r=>field('email_'+r.id,r.contact_name||'Contact',r.email||'',{type:'email'})).join('')}<h3>Add a contact · optional</h3>${field('new_contact_name','Contact name')}${field('new_contact_email','Contact email','',{type:'email'})}${field('primary','Primary email contact',c.contacts.find(r=>r.is_primary_email)?.id||'',{choices:[['','None'],...c.contacts.map(r=>[r.id,r.contact_name||'Contact'])]})}`,'Save company',async data=>{
    const contacts=c.contacts.map(r=>({id:r.id,email:data['email_'+r.id]||null,is_primary_email:data.primary===r.id}));
    const values=Object.fromEntries(['company_name','address_line','city','state','postal_code','actor_name'].map(k=>[k,data[k]||null]));
    await v12save('/companies/'+c.id,{...values,contacts,new_contacts:data.new_contact_name?[{contact_name:data.new_contact_name,email:data.new_contact_email||null}]:[],idempotency_key:requestKey},'PATCH');await chooseCompany(c.id);notice('Company details saved with an audit record.');
  });
}

$('#v12-period').onchange=()=>$$('.v12-custom').forEach(e=>e.hidden=$('#v12-period').value!=='custom');
$('#v12-period-form').onsubmit=bindErrors(async e=>{e.preventDefault();await analytics();});
$('#v12-company-search').onsubmit=bindErrors(async e=>{e.preventDefault();state.q=e.target.elements.q.value;state.page=1;await directory();});
document.addEventListener('click',bindErrors(async e=>{
  const company=e.target.closest('[data-company]'),page=e.target.closest('[data-company-page]'),tab=e.target.closest('[data-company-tab]');
  if(company)await chooseCompany(company.dataset.company);
  if(page){state.page=Number(page.dataset.companyPage);await directory();}
  if(tab){state.tab=tab.dataset.companyTab;details();}
}));
$('#v12-company-search').elements.q.value=state.q;
Promise.all([directory(),analytics(),state.companyId?chooseCompany(state.companyId):Promise.resolve()]).catch(error);

$('#v12-new-company').onclick=()=>{
  const requestKey=key();dialog('Add company',`<div class="ats-form-grid">${field('company_name','Company name','',{required:true,span:true})}${field('city','City')}${field('state','State')}${field('address_line','Address','',{span:true})}${actorField()}</div><h3>First contact · optional</h3>${field('contact_name','Contact name')}${field('contact_email','Contact email','',{type:'email'})}`,'Create company',async data=>{
    const company=await v12save('/companies',{company_name:data.company_name,city:data.city||null,state:data.state||null,address_line:data.address_line||null,actor_name:data.actor_name,idempotency_key:requestKey,contacts:data.contact_name?[{contact_name:data.contact_name,email:data.contact_email||null}]:[]});
    state.page=1;state.q='';$('#v12-company-search').reset();await chooseCompany(company.id);notice('Company created in the canonical workspace with audit history.');
  });
};

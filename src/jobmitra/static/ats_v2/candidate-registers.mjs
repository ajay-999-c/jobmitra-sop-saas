// Registration statistics and basic directory; advanced recruitment matching stays separate.
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const periods=[['ALL','All Time'],['TODAY','Today'],['WEEK','This Week'],['MONTH','This Month'],['YEAR','This Year'],['CUSTOM','Custom Date Range']];
export function registrationDate(value){if(!value)return 'Not recorded';const d=new Date(value);return Number.isNaN(d.valueOf())?'Not recorded':new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(d);}
export function installCandidateRegisters(native,root,experience){
 const $=id=>root.getElementById(id),initial=()=>({period:'ALL',source:'',date_from:'',date_to:'',q:'',page:1,page_size:20});
 const state={dashboard:initial(),directory:initial()},epochs={dashboard:0,directory:0};
 const style=document.createElement('style');style.textContent=`.candidate-reg-toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:end;padding:14px;margin-bottom:12px;border:1px solid #e3e8f0;border-radius:10px;background:#fff}.candidate-reg-toolbar .field{flex:1;min-width:145px}.candidate-reg-toolbar .reg-query{flex:2;min-width:220px}.candidate-reg-toolbar .control{min-height:36px;font-size:12px}.candidate-reg-toolbar [hidden]{display:none!important}.candidate-reg-toolbar .reg-custom{display:flex;flex-wrap:wrap;gap:8px;flex:2}.candidate-reg-status{font-size:12px;color:#68778d;padding:0 14px 10px}.candidate-reg-pages{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px 14px;border-top:1px solid #e3e8f0}.candidate-reg-pages select{width:auto}.candidate-reg-empty{padding:20px;color:#68778d}@media(max-width:650px){.candidate-reg-toolbar{padding:10px;gap:8px}.candidate-reg-toolbar .field,.candidate-reg-toolbar .reg-query{min-width:0;flex-basis:100%}.candidate-reg-toolbar .reg-custom{flex-basis:100%}.candidate-reg-pages{justify-content:space-between}.candidate-reg-pages select{max-width:120px}}`;root.append(style);
 function toolbar(area){
  const s=state[area],prefix='reg-'+area;
  return `<form class="candidate-reg-toolbar" id="${prefix}-filters" aria-label="${area==='directory'?'Candidates Directory':'Candidate Dashboard'} filters">${area==='directory'?`<div class="field reg-query"><label for="${prefix}-q">Search Candidate</label><input class="control" id="${prefix}-q" type="search" value="${esc(s.q)}" maxlength="300" placeholder="Name, mobile, email or job title"></div>`:''}<div class="field"><label for="${prefix}-period">Date Added</label><select class="control" id="${prefix}-period">${periods.map(([v,t])=>`<option value="${v}" ${v===s.period?'selected':''}>${t}</option>`).join('')}</select></div><div class="field"><label for="${prefix}-source">Candidate Source</label><select class="control" id="${prefix}-source"><option value="">All Sources</option>${(native.snapshot.candidate_sources||[]).map(o=>`<option value="${o.value}" ${o.value===s.source?'selected':''}>${esc(o.label)}</option>`).join('')}</select></div><div class="reg-custom" ${s.period==='CUSTOM'?'':'hidden'}><div class="field"><label for="${prefix}-from">From date</label><input class="control" type="date" id="${prefix}-from" value="${s.date_from}"></div><div class="field"><label for="${prefix}-to">To date · inclusive</label><input class="control" type="date" id="${prefix}-to" value="${s.date_to}"></div></div><button class="btn primary" type="submit">Apply Filters</button><button class="btn outline" type="button" data-clear-register="${area}">Clear Filters</button></form><div class="candidate-reg-status" id="${prefix}-status" role="status" aria-live="polite"></div>`;
 }
 function bind(area){
  const prefix='reg-'+area,form=$(prefix+'-filters');let timer;
  const apply=()=>{clearTimeout(timer);const s=state[area];s.period=$(prefix+'-period').value;s.source=$(prefix+'-source').value;s.date_from=$(prefix+'-from').value;s.date_to=$(prefix+'-to').value;if(area==='directory')s.q=$(prefix+'-q').value;s.page=1;form.querySelector('.reg-custom').hidden=s.period!=='CUSTOM';if(s.period==='CUSTOM'&&(!s.date_from||!s.date_to||s.date_from>s.date_to)){$(prefix+'-status').textContent='Choose both dates in order. Both dates are included.';++epochs[area];return;}load(area);};
  form.onsubmit=e=>{e.preventDefault();apply();};form.onchange=apply;
  if(area==='directory')$(prefix+'-q').oninput=()=>{clearTimeout(timer);timer=setTimeout(apply,300);};
  form.querySelector('[data-clear-register]').onclick=()=>{clearTimeout(timer);state[area]=initial();$(prefix+'-period').value='ALL';$(prefix+'-source').value='';$(prefix+'-from').value='';$(prefix+'-to').value='';if(area==='directory')$(prefix+'-q').value='';form.querySelector('.reg-custom').hidden=true;load(area);};
 }
 async function load(area){
  const epoch=++epochs[area],s=state[area],prefix='reg-'+area,status=$(prefix+'-status');if(!status)return;
  const query=new URLSearchParams({period:s.period});if(s.source)query.set('source',s.source);if(s.period==='CUSTOM'){if(!s.date_from||!s.date_to){status.textContent='Choose both dates.';return;}query.set('date_from',s.date_from);query.set('date_to',s.date_to);}
  if(area==='directory'){query.set('q',s.q);query.set('page',s.page);query.set('page_size',s.page_size);}
  status.textContent='Loading registrations…';
  try{
   const result=await native.api('/api/v12/approved/candidate-'+(area==='directory'?'directory':'dashboard')+'?'+query);
   if(epoch!==epochs[area]||!status.isConnected)return;
   if(area==='dashboard'){
    const linked=new Set(native.jobs.flatMap(j=>j.candidates.map(c=>c.id))),unknown=native.people.filter(c=>!c.skills.length).length;
    const stats=[['Total Candidates (All Time)',result.total_candidates_all_time,'All registered candidates'],['Linked to a JD',linked.size,'Across active and archived requirements'],['New Candidates (Selected Period)',result.new_candidates_selected_period,'Date and source filters combined'],['Skills to enrich',unknown,'All profiles without recorded skills']];
    $('dashboardStats').innerHTML=stats.map(([label,n,sub])=>`<div class="box today-stat"><strong>${n}</strong><small>${esc(label)}</small><div class="help" style="margin-top:7px">${esc(sub)}</div></div>`).join('');
    $('recentCandidates').innerHTML=result.recent.map(c=>`<div class="recent-row"><div><strong>${esc(c.full_name)}</strong><small>${esc(c.job_title||'Job title not recorded')} · Registered ${esc(registrationDate(c.created_at))}</small></div><button type="button" class="btn tiny outline" data-open-history="${c.id}">View →</button></div>`).join('')||'<p class="candidate-reg-empty">No registrations match these filters.</p>';
    $('recentCandidates').closest('section').querySelector('h2').textContent='Recently registered candidates';
    $('dashboardAttention').innerHTML=`<div class="miniStat"><strong>${unknown}</strong><span>Profiles needing skills enrichment</span></div><div class="miniStat"><strong>${native.people.filter(c=>!c.salary).length}</strong><span>Expected salary not recorded</span></div>`;
    status.textContent=result.new_candidates_selected_period+' registrations · '+(result.calendar.start_date?result.calendar.start_date+' to '+result.calendar.end_date:'All Time')+' · Asia/Kolkata';
   }else{
    $('registrationDirectoryRows').innerHTML=result.items.map(c=>`<div class="simple-row"><div><strong>${esc(c.full_name)}</strong><small>${esc(c.job_title||'Not recorded')} · ${esc(experience(c.experience_years))} · ${esc(c.current_city||'Location unknown')} · Added ${esc(registrationDate(c.created_at))}</small></div><button class="btn tiny outline" type="button" data-open-history="${c.id}">Full Candidate Profile →</button></div>`).join('')||'<p class="candidate-reg-empty">No candidates match these filters.</p>';
    status.textContent=result.total+' candidate'+(result.total===1?'':'s')+' found · Newest registered first';
    $('registrationDirectoryPages').innerHTML=`<button class="btn tiny outline" type="button" data-reg-page="previous" ${s.page<=1?'disabled':''}>Previous</button><span>Page ${s.page} of ${result.pages}</span><label>Per page <select class="control" aria-label="Candidates per page">${[20,50,100].map(n=>`<option ${n===s.page_size?'selected':''}>${n}</option>`).join('')}</select></label><button class="btn tiny outline" type="button" data-reg-page="next" ${s.page>=result.pages?'disabled':''}>Next</button>`;
    $('registrationDirectoryPages').querySelectorAll('[data-reg-page]').forEach(b=>b.onclick=()=>{s.page+=b.dataset.regPage==='next'?1:-1;load(area);});
    $('registrationDirectoryPages').querySelector('select').onchange=e=>{s.page_size=Number(e.target.value);s.page=1;load(area);};
   }
  }catch(error){if(epoch===epochs[area])status.textContent=error.message;}
 }
 function dashboard(){if(!$('reg-dashboard-filters')){const host=document.createElement('div');host.innerHTML=toolbar('dashboard');$('dashboardStats').before(host);bind('dashboard');}return load('dashboard');}
 function directory(){if(!$('reg-directory-filters')){$('candidateTable').innerHTML=toolbar('directory')+'<div id="registrationDirectoryRows"></div><div class="candidate-reg-pages" id="registrationDirectoryPages"></div>';bind('directory');}return load('directory');}
 return{dashboard,directory};
}

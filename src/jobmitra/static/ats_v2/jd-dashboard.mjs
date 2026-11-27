// Approved compact JD overview; canonical server filtering and metric rules remain authoritative.
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const defaults=()=>({q:'',company_id:'',assigned_recruiter_id:'',status:'',period:'ALL',date_from:'',date_to:'',target:'',sort:'NEWEST',page:1,page_size:20});
const periods=[['ALL','All Time'],['TODAY','Today'],['WEEK','This Week'],['MONTH','This Month'],['YEAR','This Year'],['CUSTOM','Custom Date Range']];
export function installJDDashboard(native,bridge){
 const root=bridge.root,$=id=>root.getElementById(id);let state=defaults(),epoch=0,timer,advanced=false,pending=0,signature='';
 const options=(value,list)=>list.map(([v,label])=>`<option value="${esc(v)}" ${String(value)===String(v)?'selected':''}>${esc(label)}</option>`).join('');
 const field=(label,key,values)=>`<div class="field"><label for="jd-${key}">${label}</label><select class="control" id="jd-${key}">${options(state[key],values)}</select></div>`;
 function toolbar(){return `<form class="jd-filter-toolbar" id="jdDashboardFilters" aria-label="JD Dashboard filters"><div class="jd-primary-filters"><input type="search" class="control" id="jd-q" maxlength="300" aria-label="Search JDs" value="${esc(state.q)}" placeholder="Search title, company, JD code or recruiter...">${field('JD Status','status',[['','All Statuses'],['DRAFT','Draft'],['ACTIVE','Active'],['ON_HOLD','On hold'],['CLOSED','Closed']])}${field('Hiring Target','target',[['','All Targets'],['TRACK','On Track'],['DUE','Due Soon'],['OVERDUE','Overdue']])}<button class="btn secondary small" id="jd-more-filters" type="button" aria-expanded="${advanced}" aria-controls="jdExtraFilters">Filters ${advanced?'▴':'▾'}</button><button class="btn secondary small" id="jd-clear" type="button">Clear</button></div><div class="jd-extra-filters" id="jdExtraFilters" ${advanced?'':'hidden'}>${field('Company','company_id',[['','All Companies']])}${field('Assigned Recruiter','assigned_recruiter_id',[['','All Recruiters'],['UNASSIGNED','Unassigned']])}${field('Created Date','period',periods)}<div class="jd-filter-custom" ${state.period==='CUSTOM'?'':'hidden'}><div class="field"><label for="jd-date_from">From</label><input class="control" type="date" id="jd-date_from" value="${esc(state.date_from)}"></div><div class="field"><label for="jd-date_to">To (inclusive)</label><input class="control" type="date" id="jd-date_to" value="${esc(state.date_to)}"></div></div>${field('Sort by','sort',[['NEWEST','Newest First'],['OLDEST','Oldest First'],['TARGET','Target Date — Nearest First'],['COMPANY','Company Name — A to Z'],['TITLE','Job Title — A to Z']])}</div></form>`;}
 async function load({passive=false}={}){
  if(passive&&pending)return false;
  const token=++epoch,status=$('jdDashboardStatus');if(!status)return;
  const query=new URLSearchParams();for(const [k,v]of Object.entries(state))if(v!==''&&(state.period==='CUSTOM'||!['date_from','date_to'].includes(k)))query.set(k,v);
  if(state.assigned_recruiter_id==='UNASSIGNED'){query.delete('assigned_recruiter_id');query.set('unassigned','true');}
  if(state.period==='CUSTOM'&&(!state.date_from||!state.date_to||state.date_from>state.date_to)){status.textContent='Choose both dates in order; the end date is inclusive.';$('jdDashboardCount').textContent='';$('jdDashboardRows').replaceChildren();$('jdDashboardPages').replaceChildren();return;}
  pending++;if(!passive)status.textContent='Loading JDs…';
  try{
   const cached=native.dashboardInitial;native.dashboardInitial=null;const result=cached&&JSON.stringify(state)===JSON.stringify(defaults())?cached:await native.api('/api/v12/approved/jd-dashboard?'+query);if(token!==epoch||!status.isConnected)return;native.adoptDashboard?.(result);const fresh=JSON.stringify(result);if(signature===fresh&&$('jdDashboardRows').children.length){status.textContent='';return false;}signature=fresh;
   if(state.page>result.pages){state.page=result.pages;return load();}
   const summary=(n,label,theme)=>`<div class="metric ${theme}"><p>${label}</p><strong>${n}</strong></div>`;
   $('jdDashboardStats').innerHTML=summary(result.summary.active,'Active JDs','')+summary(result.summary.overdue,'Target missed','red')+summary(result.summary.due_soon,'Due today / soon','amber')+summary(result.summary.filled_closed,'Closed / target filled','green');
   $('jd-company_id').innerHTML=options(state.company_id,[['','All Companies'],...result.companies.map(c=>[c.id,c.company_name])]);
   $('jd-assigned_recruiter_id').innerHTML=options(state.assigned_recruiter_id,[['','All Recruiters'],['UNASSIGNED','Unassigned'],...(result.employees||[]).map(e=>[e.id,e.display_name+(e.is_active?'':' (Inactive)')])]);
   $('jdDashboardCount').textContent=result.total+' matching requirement'+(result.total===1?'':'s');status.textContent='';
   $('jdDashboardRows').innerHTML=result.items.map(j=>{
    const item={id:String(j.id),title:j.title,company:j.company_name,status:j.status,createdAt:j.created_at,targetDate:j.target_date,vacancies:j.vacancies,joinedCount:j.joined_count},t=bridge.target(item);
    return `<tr class="jobrow" data-dashboard-open="${esc(j.id)}"><td><button class="jd-open" type="button" aria-label="Open ${esc(j.title)}: ${esc(t.label)}">${esc(j.title)}</button><br><small>${esc(j.jd_code||j.id)}</small></td><td>${esc(j.company_name)}</td><td class="recruiter">${esc(j.assigned_recruiter_name||'Unassigned')}${j.assigned_recruiter_name&&j.assigned_recruiter_active===false?' (Inactive)':''}</td><td><span class="pill ${j.status==='ACTIVE'?'green':j.status==='CLOSED'?'red':''}">${esc(({DRAFT:'Draft',ACTIVE:'Active',ON_HOLD:'On hold',CLOSED:'Closed'})[j.status]||j.status)}</span></td><td>${esc(bridge.created(item))}</td><td>${esc(bridge.date(j.target_date))}</td><td>${j.joined_count} / ${esc(j.vacancies??'Not set')}</td><td><span class="pill ${t.key==='overdue'?'red':t.key==='due'?'amber':t.key==='track'||t.key==='filled'?'green':''}">${esc(t.label)}</span><br><small>${esc(t.detail)}</small></td></tr>`;
   }).join('')||'<tr><td colspan="8">No JDs match these filters. Try different criteria or Clear.</td></tr>';
   $('jdDashboardRows').querySelectorAll('[data-dashboard-open]').forEach(row=>row.onclick=()=>bridge.open(row.dataset.dashboardOpen));
   $('jdDashboardPages').innerHTML=`<button class="btn secondary small" type="button" data-page="-1" ${state.page<=1?'disabled':''}>Previous</button><span>Page ${state.page} of ${result.pages}</span><label>Per page <select class="control" aria-label="JDs per page">${options(state.page_size,[[20,'20'],[50,'50'],[100,'100']])}</select></label><button class="btn secondary small" type="button" data-page="1" ${state.page>=result.pages?'disabled':''}>Next</button>`;
   $('jdDashboardPages').querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{state.page+=Number(b.dataset.page);void load();});
   $('jdDashboardPages').querySelector('select').onchange=e=>{state.page_size=Number(e.target.value);state.page=1;void load();};
  }catch(error){if(token===epoch&&status.isConnected){status.textContent=error.message||'Unable to load JDs. Check the filter values and try again.';$('jdDashboardCount').textContent='';$('jdDashboardRows').replaceChildren();$('jdDashboardPages').replaceChildren();}}finally{pending--;}
 }
 function render(){
  ++epoch;signature='';clearTimeout(timer);
  $('workspace').innerHTML=`<div class="jd-dashboard"><div class="row between titlebar"><h1>JD Dashboard</h1><div class="row"><button class="btn secondary small" id="jdDashboardRefresh" type="button" aria-label="Refresh dashboard">↻</button><button class="btn primary" id="newJDFromDashboard" type="button">＋ New JD</button></div></div><div class="metrics" id="jdDashboardStats"></div><section class="panel">${toolbar()}<div class="jd-dashboard-status" id="jdDashboardStatus" role="status"></div><div class="tablewrap"><table class="jd-dashboard-table"><thead><tr><th>Job title</th><th>Company</th><th>Assigned Recruiter</th><th>JD status</th><th>Creation date</th><th>Target date</th><th>Joined / vacancies</th><th>Deadline status</th></tr></thead><tbody id="jdDashboardRows"></tbody></table></div><div class="footer"><span id="jdDashboardCount"></span><div class="jd-dashboard-pages" id="jdDashboardPages"></div></div></section><p class="muted compact">Summary cards cover all JDs. Dates use India calendar time.</p></div>`;
  const form=$('jdDashboardFilters');
  const read=()=>{for(const key of Object.keys(state))if($('jd-'+key))state[key]=$('jd-'+key).value;state.page=1;form.querySelector('.jd-filter-custom').hidden=state.period!=='CUSTOM';};
  form.onsubmit=e=>{e.preventDefault();read();clearTimeout(timer);void load();};
  form.onchange=e=>{if(e.target.id==='jd-q')return;read();clearTimeout(timer);++epoch;void load();};
  $('jd-q').oninput=()=>{read();++epoch;clearTimeout(timer);$('jdDashboardStatus').textContent='Searching JDs…';$('jdDashboardRows').replaceChildren();$('jdDashboardCount').textContent='';timer=setTimeout(load,250);};
  $('jd-more-filters').onclick=()=>{advanced=!advanced;$('jdExtraFilters').hidden=!advanced;$('jd-more-filters').setAttribute('aria-expanded',String(advanced));$('jd-more-filters').textContent='Filters '+(advanced?'▴':'▾');};
  $('jd-clear').onclick=()=>{state=defaults();advanced=false;void render();};$('jdDashboardRefresh').onclick=()=>void load();
  return load();
 }
 return{render,refresh:load,state:()=>({...state}),invalidate:()=>{++epoch;}};
}

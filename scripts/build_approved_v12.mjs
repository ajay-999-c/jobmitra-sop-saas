// Rebuild the approved presentation without writing to its immutable source.
// Usage: npm ci --ignore-scripts && npm run build:v12 (or npm run check:v12)
import fs from 'node:fs';
import crypto from 'node:crypto';
import {cleanJDStyles,cleanJDMarkup} from './v12-clean-jd.mjs';
import {workspaceMarkup,workspaceStyles} from './v12-workspace-layout.mjs';
import {emailWorkspaceMarkup,emailWorkspaceStyles} from './v12-email.mjs';
import {createRequire} from 'node:module';
import {parse} from '@babel/parser';
import babelTraverse from '@babel/traverse';
const require=createRequire(import.meta.url);
const check=process.argv.includes('--check');
// Keep the earlier explicit parser argument compatible; normal builds use locked dependencies.
const legacyParser=process.argv[2]&&!process.argv[2].startsWith('--')?require(process.argv[2]):null;
const babelParse=legacyParser?.babelParse||((code,filename)=>parse(code,{sourceType:'script',sourceFilename:filename}));
const traverse=legacyParser?.traverse||babelTraverse;
const reference='Jobmitra_Unified_Workspace_V12_Companies_Integrated (1).html';
const bytes=fs.readFileSync(reference),hash=crypto.createHash('sha256').update(bytes).digest('hex');
if(hash!=='a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e')throw Error('Approved source hash mismatch.');
const html=bytes.toString('utf8'),match=html.match(/<script>([\s\S]*)<\/script>/);
let source=match[1];
const replacements={};
for(const area of ['candidates','jobs','companies']){
 const file=fs.readFileSync('scripts/v12-adapters/'+area+'.js','utf8');replacements[area]={};
 for(const n of babelParse(file,'adapter.js').program.body)if(n.type==='FunctionDeclaration')replacements[area][n.id.name]=file.slice(n.start,n.end);
}
const edits=[];
const area=n=>n.loc.start.line<516?'jobs':n.loc.start.line<966?'candidates':'companies';
const replace=(n,value)=>edits.push({start:n.start,end:n.end,value});
traverse(babelParse(source,'reference.js'),{
 ObjectProperty(p){if(p.node.key.name==='addCandidate'&&p.node.value.type==='ArrowFunctionExpression')replace(p.node.value,`async(person,jobId)=>{try{await native.addToPool(person.id,String(jobId),person);return{ok:true};}catch(error){return{ok:false,error:error.message};}}`);},
 FunctionDeclaration(p){const value=replacements[area(p.node)]?.[p.node.id.name];if(value)replace(p.node,value);},
 VariableDeclarator(p){if(p.node.id.name==='refStage'&&area(p.node)==='jobs')replace(p.node.init,`(key,name,roundId)=>{if(key==='ROUND'&&roundId)return 'ROUND:'+roundId;if(key&&key!=='ROUND')return key;const label=String(name||'').toLowerCase().trim(),aliases={'candidate pool':'POOL','candidate contact':'CONTACT','jobmitra screening':'SCREENING','company submission':'COMPANY_SUBMISSION','selected by company':'SELECTED','joined':'JOINED','not selected':'NOT_SELECTED'};if(aliases[label])return aliases[label];const rounds=draft.rounds.filter(r=>r.name?.toLowerCase()===label);return rounds.length===1?'ROUND:'+rounds[0].id:null;}`);if(p.node.id.name==='countJoined'&&area(p.node)==='jobs')replace(p.node.init,"j=>j.joinedCount??(j.candidates||[]).filter(c=>c.stageKey==='JOINED').length");if(p.node.id.name==='canEmail'&&area(p.node)==='jobs')replace(p.node.init,'canComposePipelineEmail(key)');if(['jdPrototypeDemo','jdFallbackJourney'].includes(p.node.id.name))replace(p.node.init,'{}');if(p.node.id.name==='persist')replace(p.node.init,'()=>{}');},
 AssignmentExpression(p){
  const left=source.slice(p.node.left.start,p.node.left.end),a=area(p.node),n=p.node.right;
  if(left==='jdShadow.innerHTML')replace(n,JSON.stringify(workspaceMarkup(cleanJDMarkup(n.value))));
  if(left==='candidateShadow.innerHTML'){const approved=n.value;if(typeof approved!=='string')throw Error('Candidate HTML boundary missing.');const foundit='<button class="tab" role="tab" aria-selected="false" data-tab="foundit" type="button">Foundit Paste</button>';let ui=approved.replace('<button data-tab="foundit" type="button">Foundit Paste</button>','');const marker='<button class="tab"';const pool=ui.indexOf('data-tab="pool"');const start=ui.lastIndexOf(marker,pool);if(start<0)throw Error('Foundit navigation insertion point missing.');ui=ui.slice(0,start)+foundit+ui.slice(start);replace(n,JSON.stringify(ui));}
  const handlers={
   "el('saveMilestone').onclick":`()=>native.run(async()=>{const button=el('saveMilestone'),value=el('milestoneValue').value,note=el('milestoneNote').value.trim();await native.activity(c.id,{job_id:Number(draft.id),activity_type:'FOLLOW_UP',notes:note||labels[key]+' · '+value,details:{kind:'PLACEMENT_MILESTONE',milestone:key,value,manual_fact_only:true,delivery_enabled:false,financial_transaction:false}},button);closeModal();await native.refresh();render();toast('Manual status recorded. No email, invoice or payment was sent.');},toast)`,
   "el('saveInterview').onclick":`()=>native.run(async()=>{const date=el('interviewDate').value;if(!date)throw Error('Choose the interview date and time.');const scheduledAt=new Date(date).toISOString(),mode=el('interviewMode').value,location=el('interviewLocation').value,notes=el('interviewNotes').value;await native.activity(c.id,{job_id:Number(draft.id),activity_type:'INTERVIEW',due_at:scheduledAt,notes:notes||'Interview scheduled',details:{kind:'INTERVIEW_SCHEDULED',scheduledAt,mode,location,round_id:c.stageId,round_name:round?.name,invitation_sent:false}},el('saveInterview'));closeModal();await native.refresh();render();toast('Interview schedule saved. No invitation was sent.');},toast)`,
   "$('#editProfileForm').onsubmit":`e=>{e.preventDefault();const owner=e.currentTarget;native.run(async()=>{await native.authorize();await native.api('/api/ats-v2/candidates/'+c.id,{skills:[...new Map($('#editSkills').value.split(',').map(x=>x.trim()).filter(Boolean).map(x=>[x.toLowerCase(),x])).values()],professional_summary:$('#editSummary').value},'PATCH',owner);$('#modalHost').innerHTML='';await native.refresh();await search();if(activeProfileCandidate===c.id)showFullProfilePanel(c.id,'overview');toast('Professional profile saved to SQLite.');},toast);}`,
   "$('#companyForm').onsubmit":`e=>{e.preventDefault();native.run(async()=>{collectContacts();const button=e.currentTarget;await native.api('/api/v12/approved/companies/'+c.id,{idempotency_key:native.key(button),actor_name:await native.authorize(),expected_revision:c.revision,name:$('#coName').value,phone:$('#coPhone').value,address:$('#coAddress').value,city:$('#coCity').value,state:$('#coState').value,postal:$('#coPostal').value,contacts},'PATCH',button);await native.refresh();toast('Company details and contact changes saved with audit history.');},toast);}`,
   "$('#deleteCompany').onclick":`()=>native.run(async()=>{if(!confirm('Archive this company? Original contacts, JDs and history will be retained.'))return;const button=$('#deleteCompany');await native.api('/api/v12/approved/companies/'+c.id,{idempotency_key:native.key(button),actor_name:await native.authorize(),expected_revision:c.revision,name:c.name,phone:c.phone,address:c.address,city:c.city,state:c.state,postal:c.postal,contacts:c.contacts,archive:true},'PATCH',button);await native.refresh();toast('Company archived; original records preserved.');},toast)`,
   "$('#markJoined').onclick":`()=>native.run(async()=>{const job=native.jobs.find(j=>j.id===p.jdId),person=job?.candidates.find(c=>c.id===p.candidateId);await native.outcome(job,person,'JOIN',$('#markJoined'));closeModal();await native.refresh();toast('Actual joining confirmed from canonical JD.');},toast)`,
   "$('#notJoined').onclick":`()=>native.run(async()=>{const job=native.jobs.find(j=>j.id===p.jdId),person=job?.candidates.find(c=>c.id===p.candidateId);await native.outcome(job,person,'NOT_JOINED',$('#notJoined'));closeModal();await native.refresh();toast('Not Joined recorded; eligibility recalculated.');},toast)`,
   "$('#resetDemo').onclick":`()=>native.run(async()=>{await native.refresh();toast('Canonical records reloaded. No records were reset.');},toast)`
  };
  if(handlers[left])replace(n,a==='jobs'?handlers[left].replaceAll('await native.refresh();','await native.refreshJD(draft.id,{force:true});'):handlers[left]);
  if(a==='companies'&&left==="$('#confirmDemoSelection').onclick"){} // Function replacement owns this handler.
 },
 CallExpression(p){const code=source.slice(p.node.callee.start,p.node.callee.end);
  if(code==="$('#addToPoolBtn').addEventListener"&&p.node.arguments[0]?.value==='click')replace(p.node.arguments[1],`()=>native.run(async()=>{if(!$('#selectActiveJD')?.value)throw Error('Choose a matching active JD from the list.');const current=job(selectedJob);if(!current||current.status!=='ACTIVE')throw Error('Select an active JD.');if(state.pools[selectedJob]?.[c.id]){closeDetail();native.openMembership(c.id,selectedJob);return;}await native.addToPool(c.id,selectedJob,$('#addToPoolBtn'));await search();toast('Candidate added at Candidate Contact.');},toast)`);
  if(code==="$('#officeVisitForm').addEventListener")replace(p.node.arguments[1],`e=>{e.preventDefault();native.run(async()=>{const cid=$('#visitCandidate').value,date=$('#visitDate').value;if(!cid||!date)throw Error('Select a candidate and visit date.');await native.activity(cid,{activity_type:'OFFICE_VISIT',occurred_at:date+'T12:00:00+05:30',notes:$('#visitNotes').value,details:{date,purpose:$('#visitPurpose').value}},e.currentTarget);await native.refresh();renderOfficeVisits();toast('Office visit saved.');},toast);}`);
  if(code==="$('#jobRequestForm').addEventListener")replace(p.node.arguments[1],`e=>{e.preventDefault();native.run(async()=>{const cid=$('#requestCandidate').value,role=$('#requestRole').value.trim();if(!cid||!role)throw Error('Select a candidate and preferred role.');await native.activity(cid,{activity_type:'JOB_SEARCH_REQUEST',notes:$('#requestNotes').value,status:['CLOSED','FULFILLED'].includes($('#requestStatus').value.toUpperCase())?'DONE':'OPEN',details:{role,location:$('#requestLocation').value,status:$('#requestStatus').value}},e.currentTarget);await native.refresh();renderJobRequests();toast('Job search request saved.');},toast);}`);
  if(code==="$('#resetBtn').addEventListener")replace(p.node.arguments[1],`()=>native.run(async()=>{await native.refresh();resetFilters();toast('Canonical records reloaded. Preserved documents were not deleted.');},toast)`);
  if(code==='options'&&source.slice(p.node.arguments[0]?.start,p.node.arguments[0]?.end)==='draft.company')replace(p.node,`options(draft.companyId,[['','Choose an existing company'],...native.companies.filter(c=>c.active).map(c=>[c.id,c.name])])`);
 }
});
// Outer function replacements own their nested handlers. Ignore overlapping edits.
const filtered=edits.filter(e=>!edits.some(o=>o!==e&&o.start<=e.start&&o.end>=e.end&&(o.start<e.start||o.end>e.end)));
for(const e of filtered.sort((a,b)=>b.start-a.start))source=source.slice(0,e.start)+e.value+source.slice(e.end);
source=source.replace('function header(){',replacements.jobs.cleanJD+'\nfunction header(){');
function section(start,end,value){const a=source.indexOf(start),b=source.indexOf(end,a);if(a<0||b<0)throw Error('Missing source boundary '+start);source=source.slice(0,a)+value+source.slice(b);}
section('    const demo=','    let selectedId=',`    let state={jobs:structuredClone(native.jobs),activeId:native.jobs[0]?.id||null};\n`);
source=source.replace("state.activeId||state.jobs[0].id","state.activeId||state.jobs[0]?.id||null");
source=source.replace("draft=clone(state.jobs.find(x=>x.id===selectedId)||state.jobs[0])","draft=clone(state.jobs.find(x=>x.id===selectedId)||state.jobs[0]||native.emptyJD())");
section('const candidates=[','function save(){',`const candidates=structuredClone(native.people),jobs=structuredClone(native.jobs);\nlet state={pools:native.pools(),events:native.snapshot.events.map(e=>({event:e.event_type,candidateId:String(e.candidate_id),jobId:String(e.job_id),at:e.created_at})),createdCandidates:[],profileEdits:{},officeVisits:native.historyActivities('OFFICE_VISIT'),jobSearchRequests:native.historyActivities('JOB_SEARCH_REQUEST')},tab='search',matchMode='any',selectedCandidate=null,selectedJob=jobs.find(j=>j.status==='ACTIVE')?.id||'',poolJob=jobs.find(j=>j.status==='ACTIVE')?.id||'',currentResults=[];\n`);
section('const sampleCompanies=','let toastTimer;',`let state={companies:structuredClone(native.companies),placements:structuredClone(native.placements),available:structuredClone(native.people),selectedCompany:native.companies[0]?.id||'',scope:'all',tab:'placements',period:'month',from:native.today.slice(0,7)+'-01',to:native.today,placementStatus:'ALL',placementQuery:''};\nfunction save(){}\n`);
source=source.replace("const day='2026-11-19';","const day=native.today;");
source=source.replaceAll("draft[t.name]=t.value;","if(t.name==='company'){draft.companyId=t.value;draft.company=native.companies.find(c=>c.id===t.value)?.name||'';}else draft[t.name]=t.value;");
source=source.replace('phone:row.querySelector(\'[data-field="phone"]\').value.trim(),primary:', 'phone:row.querySelector(\'[data-field="phone"]\').value.trim(),id:contacts[i]?.id||null,primary:');
// All V12 sourcing entry points open the committed membership's actual stage.
source=source.replace('openJD:(jobId)=>{activate(\'jd\');window.JobmitraUnifiedJD?.openJob(jobId);}', 'openJD:(jobId,stage)=>{activate(\'jd\');window.JobmitraUnifiedJD?.openJob(jobId,stage);}');
source=source.replace("openJob:(id)=>{const j=state.jobs.find(x=>x.id===id);if(j){switchJob(id);view='pipeline';stageFilter='POOL';render();return true;}return false;}", "openJob:(id,stage)=>{const j=state.jobs.find(x=>x.id===id);if(j){switchJob(id);view='pipeline';stageFilter=stage&&stageDefs().some(d=>d.key===stage)?stage:'POOL';cleanJD().stageChanged(stageFilter);render();return true;}return false;}");
// Attachment uses canonical Pool history followed by Candidate Contact.
source=source.replaceAll('Initial stage: Candidate Pool · No duplicate candidate registration','Initial stage: Candidate Contact · Candidate Pool history retained').replaceAll('Adding a candidate never triggers email, interview scheduling or automatic stage advancement.','Adding starts at Candidate Contact; it never sends email or schedules an interview.').replaceAll('Adding here does not register a new candidate, send an email, or change their recruitment stage.','Adding here retains Candidate Pool history and starts at Candidate Contact; it never registers a duplicate candidate or sends email.').replaceAll('Recruitment stage progression is managed on the JD Candidate Pipeline, not automatically when you add a candidate.','After the initial move to Candidate Contact, further progression is managed on the JD Candidate Pipeline.');
// Canonical numeric JD IDs still expose the approved Open control.
source=source.replaceAll("j.id.startsWith('JD-')","Boolean(j.id)");
source=source.replace('let foot=p.linkedFromJD?', 'let foot=false?').replace('if(p.linkedFromJD){$(\'#openLinkedJD\')','if(false&&p.linkedFromJD){$(\'#openLinkedJD\')');
source=source.replace("modal('Candidate placement record','Stage events & candidate availability',body,foot);", "if(p.linkedFromJD)foot+='<button class=\"btn primary\" id=\"openLinkedJD\">Open JD Pipeline</button>';modal('Candidate placement record','Stage events & candidate availability',body,foot);if(p.linkedFromJD)$('#openLinkedJD').onclick=()=>{closeModal();window.JobmitraUnified.openJD(p.jdId);};");
// Preserve distinct closed-selection facts using the approved terminal-state presentation.
source=source.replaceAll("['SELECTED','JOINED','NOT_SELECTED']","['SELECTED','JOINED','NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED']");
source=source.replaceAll("['NOT_SELECTED','JOINED']","['NOT_SELECTED','JOINED','NOT_JOINED','SELECTION_CANCELLED']");
source=source.replaceAll("k==='NOT_SELECTED'?'Not Selected':", "k==='NOT_SELECTED'?'Not Selected':k==='NOT_JOINED'?'Not Joined':k==='SELECTION_CANCELLED'?'Selection Cancelled':");
source=source.replaceAll("NOT_SELECTED:'Not Selected'", "NOT_SELECTED:'Not Selected',NOT_JOINED:'Not Joined',SELECTION_CANCELLED:'Selection Cancelled'");
source=source.replace('e=>e.feedback&&e.feedback.trim()',"e=>e.feedback&&e.feedback.trim()&&!['MILESTONE','INTERVIEW_SCHEDULED'].includes(e.type)");
// Retained round IDs resolve the same cumulative reach after rejection/rename.
source=source.replace('stageOf(c),c.rejection?.stageKey','stageOf(c),refStage(c.rejection?.stageKey,c.rejection?.stageName)');
source=source.replaceAll('refStage(ev.fromKey,ev.fromName)','refStage(ev.fromKey,ev.fromName,ev.fromRoundId)').replaceAll('refStage(ev.toKey,ev.toName)','refStage(ev.toKey,ev.toName,ev.toRoundId)').replaceAll('refStage(e.fromKey,e.fromName)','refStage(e.fromKey,e.fromName,e.fromRoundId)').replaceAll('refStage(e.toKey,e.toName)','refStage(e.toKey,e.toName,e.toRoundId)');
// Expose the canonical selection to the separate proposal adapter; no presentation changes.
source=source.replace('window.JobmitraUnifiedCompanies={refreshFromJD,getEligibility,','window.JobmitraUnifiedCompanies={getSelectedCompanyId:()=>state.selectedCompany,refreshFromJD,getEligibility,');
// Initialize and refresh each original component from canonical service projections.
source=source.replace('    render();\n  })();',`    const acceptUpdate=event=>{
      if(event.detail?.id&&String(event.detail.id)!==String(selectedId)){if(view==='dashboard')void native.jdDashboard?.refresh();return;}
      state.jobs=structuredClone(native.jobs);const current=state.jobs.find(j=>j.id===selectedId);
      if((detailsDirty()||workflowDirty()||el('modalHost')?.children.length)&&!event.detail?.force){
        let banner=el('jdRemoteChanges');if(!banner){banner=jdShadow.ownerDocument.createElement('div');banner.id='jdRemoteChanges';banner.className='banner amber';banner.setAttribute('role','status');el('workspace').before(banner);}
        banner.textContent='Server changes are available. Your unsaved edits are preserved. ';
        const review=jdShadow.ownerDocument.createElement('button');review.className='btn secondary small';review.textContent='Reload and review';review.onclick=()=>{if(!confirm('Discard unsaved JD changes and review the latest server record?'))return;closeModal();void native.refreshJD(selectedId,{force:true});};banner.append(review);return;
      }
      el('jdRemoteChanges')?.remove();
      const rail=el('workspace')?.querySelector('.rail'),left=rail?.scrollLeft||0,position=window.scrollY;
      const input=jdShadow.activeElement,focusId=input?.id,start=input?.selectionStart,end=input?.selectionEnd;
      if(current){draft=clone(current);isNew=false;}else if(!isNew){selectedId=null;draft=native.emptyJD();}
      if(view==='dashboard')void native.jdDashboard?.refresh();else{render();const next=el('workspace')?.querySelector('.rail');if(next)next.scrollLeft=left;if(focusId){const field=el(focusId);field?.focus({preventScroll:true});if(start!=null&&field?.setSelectionRange)field.setSelectionRange(start,end);}window.scrollTo({top:position});}
    };
    window.addEventListener('jobmitra-native-update',acceptUpdate);window.addEventListener('jobmitra-jd-update',acceptUpdate);
    installJDSync(native,{active:()=>!hostJD.hidden,view:()=>view,id:()=>selectedId,error:message=>{const status=el('jdSyncNotice');if(status)status.textContent='Refresh unavailable: '+message;}});
    if(!state.jobs.length)view='dashboard';render();
  })();`);
source=source.replace(' search();renderDetails();',` window.addEventListener('jobmitra-native-update',()=>{candidates.splice(0,candidates.length,...structuredClone(native.people));jobs.splice(0,jobs.length,...structuredClone(native.jobs));state.pools=native.pools();state.officeVisits=native.historyActivities('OFFICE_VISIT');state.jobSearchRequests=native.historyActivities('JOB_SEARCH_REQUEST');if(tab==='search')search();if(tab==='pool')renderPool();if(tab==='dashboard')renderDashboard();if(tab==='candidates'){renderCandidates();if(activeProfileCandidate)showFullProfilePanel(activeProfileCandidate,activeProfileSection);}if(tab==='resumes')renderResumes();if(tab==='visits')renderOfficeVisits();if(tab==='requests')renderJobRequests();});\n search();renderDetails();`);
source=source.replace('renderScope();renderAnalytics();renderDirectory();renderCompany();refreshFromJD();',`window.addEventListener('jobmitra-native-update',()=>{state.companies=structuredClone(native.companies);state.placements=structuredClone(native.placements);state.available=structuredClone(native.people);renderScope();renderAnalytics();renderDirectory();renderCompany();});renderScope();renderAnalytics();renderDirectory();renderCompany();`);
source=source.replace('return {name:master.name||c.name,experience:', 'return {id:c.id,name:master.name||c.name,experience:');
source=source.replace('getContacts?.(draft.company)', 'getContacts?.(draft.companyId)');source=source.replaceAll('getContacts?.(draft.company)', 'getContacts?.(draft.companyId)');
// Email remains a draft action at every supported pipeline stage, independent of editing gates.
if(!source.includes('canEmail:canComposePipelineEmail'))throw Error('Pipeline Email visibility adapter missing.');
// Only carry a recorded schedule for the candidate's current interview round.
source=source.replace("const interview=(c.journey||[]).find(e=>e.type==='INTERVIEW_SCHEDULED'&&e.scheduledAt);", "const interview=(c.journey||[]).find(e=>e.type==='INTERVIEW_SCHEDULED'&&e.scheduledAt&&e.round_id===c.stageId);");
source=source.replace('interviewDate,interviewTime,candidates:[master]', 'roundId:c.stageId||null,interviewDate,interviewTime,candidates:[master]');
section(' const emailOverlay=', ' /* JD local demo',` installEmailWorkspace(EMAIL_STUDIO_DOCUMENT);\n installContextualEmail(native,EMAIL_STUDIO_DOCUMENT,pipelineEmailContext);\n`);
source=source.replace('(function(){',`(async function(){\n await native.refresh(false);`);
source=source.replace(/activate\('companies'\);(?=\s*\}\)\(\);\s*$)/,`const section=window.document.body.dataset.section;activate(section==='email'?'email':section==='jobs'?'jd':section==='candidates'?'candidate':'companies');\n installWorkspaceSelectors(native,jdShadow);installWorkspaceSelectors(native,candidateShadow);\n native.renderAccess();`);
source=source.replace("showCandidateHistory:(id)=>showCandidateHistory(id),", "showCandidateHistory:(id)=>showCandidateHistory(id),showForPool:async(id)=>{setTab('search');resetFilters();await search();selectCandidate(id);},");
source=source.replace("b.onclick=()=>toast('Eligible in prototype. Actual JD assignment happens in Candidate Desk.')", "b.onclick=()=>{closeModal();window.JobmitraUnified.show('candidate');window.JobmitraUnifiedCandidate.showForPool(b.dataset.previewPool);}");
source=source.replace("toast('Navigation is a visual placeholder in this standalone demo.');", "if(target.id==='topStaff')toast('Staff has no approved native V12 replacement yet. Legacy backend data and APIs are preserved.');else window.JobmitraUnified.show('companies');");
source=source.replace("const area=which==='companies'?","const area=which==='email'?'email':which==='companies'?");
source=source.replace("hostJD.hidden=area!=='jd';","hostJD.hidden=area!=='jd';window.document.getElementById('emailHost').hidden=area!=='email';");
source=source.replaceAll("['unifiedJDTab','jd']","['unifiedJDTab','jd'],['unifiedEmailTab','email']");
source=source.replace("show:(where)=>activate(where==='jd'?","show:(where)=>activate(where==='email'?'email':where==='jd'?");
// Email shortcuts use canonical profiles/memberships without changing profile layout.
source=source.replace('<div class="profile-v9-actions">','<div class="profile-v9-actions"><button class="btn tiny outline" type="button" data-email-profile="${escapeHTML(c.id)}">Email</button>');
source=source.replace('Open JD pipeline →</button>','Open JD pipeline →</button><button class="btn tiny outline" type="button" data-email-job="${escapeHTML(r.jobId)}" data-email-candidate="${escapeHTML(c.id)}">Email</button>');
// Group immutable Gmail attempt/result facts into the existing profile history.
source=source.replace('return `<div class="profile-v9-section"><section class="profile-v9-card"><h3>JD Participation & History</h3>', 'return `<div class="profile-v9-section">${native.emailHistoryHTML(c.id)}<section class="profile-v9-card"><h3>JD Participation & History</h3>');
// The explicit JD-history shortcut must not fall back to the profile overview.
source=source.replace('>Open full JD history →</button>',' data-profile-section="history">Open full JD history →</button>');
source=source.replace("showCandidateHistory(history.dataset.openHistory,'overview')","showCandidateHistory(history.dataset.openHistory,history.dataset.profileSection||'overview')");
// Candidate-only additions retain the approved component and its other renderers.
source=source.replace("function setTab(next){tab=next;", "function setTab(next){tab=next;");
source=source.replace("document.querySelector('.more-tabs')?.removeAttribute('open');window.scrollTo", "document.querySelector('.more-tabs')?.removeAttribute('open');native.candidateDesk?.section(next);window.scrollTo");
const resumeStart=source.indexOf("if(section==='resumes')return"),resumeEnd=source.indexOf("if(section==='parsed')",resumeStart);
if(resumeStart<0||resumeEnd<0)throw Error('Candidate resume boundary missing.');
source=source.slice(0,resumeStart)+"if(section==='resumes')return native.candidateDesk.resumeHTML(c);\n  "+source.slice(resumeEnd);
const parsedStart=source.indexOf("if(section==='parsed')return"),parsedEnd=source.indexOf('\n  return `<div class="profile-v9-section"',parsedStart);
if(parsedStart<0||parsedEnd<0)throw Error('Candidate parsed section boundary missing.');
source=source.slice(0,parsedStart)+"if(section==='parsed')return native.candidateDesk.parsedHTML(c);"+source.slice(parsedEnd);
source=source.replace("$('#profileResumeForm')?.addEventListener('submit',e=>attachOriginalResume(e,id));", "$('#profileResumeForm')?.addEventListener('submit',e=>attachOriginalResume(e,id));native.candidateDesk.bindResume(id);");
source=source.replace("$('#profilePreviewParsed')?.addEventListener('click',()=>previewParsedJSON(id));", "$('#profilePreviewParsed')?.addEventListener('click',()=>previewParsedJSON(id));native.candidateDesk.bindParsed(id);");
source=source.replace("$('#detailUnderlay').classList.add('mobile-open');if(window.matchMedia", "$('#detailUnderlay').classList.add('mobile-open');native.candidateDesk.opened();if(window.matchMedia");
source=source.replace("function selectCandidate(id){", "function selectCandidate(id){native.candidateDesk.remember();");
source=source.replace("function closeDetail(){", "function closeDetail(){native.candidateDesk.closed();");
source=source.replace(" search();renderDetails();", ` native.candidateRegisters=installCandidateRegisters(native,candidateShadow,expLabel);native.candidateDesk=installCandidateDesk(native,{root:candidateShadow,tab:setTab,close:closeDetail,registration:showRegistration,toast,profile:(id,section='overview')=>{setTab('candidates');showFullProfilePanel(String(id),section);}});\n search();renderDetails();`);
source=source.replace('class="profile-v9-copy">${escapeHTML(x)}</p>', 'class="profile-v9-copy">${escapeHTML(native.candidateDesk.describe(x))}</p>');
source=source.replaceAll('Edit professional details','Edit Candidate Details').replaceAll('Edit details</button>','Edit Candidate Details</button>');
source=source.replace("kv('Current CTC',", "kv('Current salary',").replace("kv('Expected CTC',", "kv('Expected salary',");
source=source.replace('of ${state.companies.length} demo','of ${state.companies.length} companies');
source=source.replaceAll('Editable in this preview','Editable record').replaceAll('Browser preview only','Canonical SQLite').replaceAll('Delete company','Archive company').replaceAll('Company Master fields remain available. Contact email can later prefill Email Studio.','Company Master fields remain available. Contact email prefills Email Studio.');
source=source.replaceAll('demo joining','confirmed joining').replaceAll('Shows demo companies based on the Companies-page layout. Your original Company Master and contacts are not modified.','Canonical company records from SQLite. Historical contacts and JD events remain preserved.');
source=source.replaceAll('Browser-local interactive prototype · No real candidates, email or payments are modified','SQLite workspace · Candidate changes are audited · No email or payments are sent').replaceAll('Standalone preview of how pool restrictions will appear','Canonical candidates and allocation eligibility').replaceAll('recorded in this preview','recorded in this workspace');
source=source.replace("if(!c){c=state.companies[0];if(!c)return;", "if(!c){c=state.companies[0];if(!c){$('#companyTitle').textContent='No company selected';$('#companySubtitle').textContent='';$('#companyMeta').innerHTML='';$('#companyPanel').innerHTML='<div class=\"blank-state\">No company records. Use Add company to register a client.</div>';return;}");
// Three additive registration controls; the approved reference remains immutable.
source=source.replace('${kv(\'Name\',c.name)}', "${kv('Registration date',registrationDate(c.created))}${kv('Purpose of Visit / Registration',c.registrationPurpose)}${kv('Name',c.name)}");
source=source.replace('<option>Foundit</option><option>Walk-in</option>', '${(native.snapshot.candidate_sources||[]).filter(s=>[\'EMAIL\',\'MANUAL\',\'RESUME_UPLOAD\'].includes(s.value)).map(s=>\'<option>\'+escapeHTML(s.label)+\'</option>\').join(\'\')}<option>Foundit</option><option>Walk-in</option>');
// Native browser validation is rendered inside these two forms for consistent feedback.
source=source.replace('id="registrationForm" role=', 'id="registrationForm" novalidate role=');
source=source.replace('<form id="jdForm">', '<form id="jdForm" novalidate>');
source=source.replace('<div class="span2 resume-upload">', '<div class="field span2"><label for="regPurpose">Purpose of Visit / Registration (optional)</label><textarea class="control" id="regPurpose" name="registration_purpose" maxlength="2000" placeholder="e.g. Job enquiry, resume submission, follow-up or career consultation"></textarea></div><div class="span2 resume-upload">');
// These are truthful integration wording changes, not alternate UI components.
const wording=[['Reset preview data','Reload records'],['Current demo associations','Current canonical associations'],['All milestones are manual records in this prototype.','All milestones are manual records in this workspace.'],['↻ Reset preview','↻ Reload records'],['Reset local preview','Reload records'],['Reset demo','Reload records'],['＋ Simulate JD selection','＋ Record JD selection'],['Demo job requirements','Job requirements'],['Available (demo)','Available'],['Stored on this device','Stored on the server'],['Saving is local to this browser. This prototype does not update real candidate journeys or production data.','Saving updates the isolated SQLite workspace after validation. Historical records remain preserved.'],['This offline preview records filename only.','The original file is uploaded and preserved as a resume version.'],['Demo snapshot as of','Snapshot as of'],['saved locally','saved to SQLite']];
for(const [a,b] of wording)source=source.replaceAll(a,b);
source=source.replaceAll('Advance candidate to next stage','Move candidate to next stage').replaceAll('Save & Advance','Save & Move to Next Stage');
source=source.replace("const detailKeys=[","const detailKeys=['companyId','recruiterId',");
// Nullable canonical staff assignment; retain an inactive existing assignee visibly.

// Dashboard is independent of JD selection; source components remain canonical.
source=source.replace("selectedId=state.activeId||state.jobs[0]?.id||null,view='pipeline'", "selectedId=null,view='dashboard'");
source=source.replace("draft=clone(state.jobs.find(x=>x.id===selectedId)||state.jobs[0]||native.emptyJD())", "draft=native.emptyJD()");
source=source.replace('const detailsDirty=()=>isNew||', 'const detailsDirty=()=>isNew||!!selectedId&&');
source=source.replace('const workflowDirty=()=>', 'const workflowDirty=()=>!!selectedId&&');
source=source.replace("draft[name]||''", "draft[name]??''");
source=source.replace("if(n.length<3)return'Stage names must contain at least 3 characters.'", "if(n.length<3||n.length>80)return'Stage names must contain 3–80 characters.'");
source=source.replace("draft.workflowMode='CONFIGURED';draft.rounds=names.map","if(draft.rounds.some(r=>r.active)&&!confirm('Replace the unsaved interview rounds with this preset?'))return;draft.workflowMode='CONFIGURED';draft.rounds=names.map");
source=source.replace('Maximum 15 company interview rounds in this prototype.','Maximum 15 company interview rounds.');
// Backend-neutral statuses keep the approved presentation valid for either store.
const storageWording=[
 ['Canonical company records from SQLite.','Canonical company records from the workspace.'],
 ['· SQLite workspace ·','· Unified workspace ·'],
 ['Saved. Candidate and JD history reconciled from SQLite.','Saved. Candidate and JD history reconciled from the workspace.'],
 ['Saving updates the isolated SQLite workspace after validation.','Saving updates the workspace after validation.'],
 ['JD details saved to canonical SQLite.','JD details saved.'],
 ['Candidate registered in canonical SQLite','Candidate registered'],
 ['· Canonical SQLite','· Canonical workspace'],
 ['Company saved in canonical SQLite.','Company saved.'],
];
for(const [a,b] of storageWording)source=source.replaceAll(a,b);
// Remove local-document save/read implementations entirely; real services own those operations.
for(const name of ['storeCandidateDocument','readCandidateDocument','persistCandidateChanges']){
 const ast=babelParse(source,'integrated.js');let n;traverse(ast,{FunctionDeclaration(p){if(p.node.id.name===name)n=p.node;}});if(n)source=source.slice(0,n.start)+`function ${name}(){throw Error('Use the canonical service adapter.');}`+source.slice(n.end);
}
// Keep the approved presentation but replace factually false prototype help paragraphs.
source=source.replace(/Offline preview: file bytes[\s\S]*?require backend integration\./,'Original resume versions are stored privately by the FastAPI service. Earlier versions and historical references remain preserved.');
source=source.replace(/This preview reads JSON locally[\s\S]*?confidential candidate data in this demo\./,'Review the extracted professional fields before applying. The service preserves the original JSON text, creates a version and updates only approved fields and search evidence.');
source=source.replace(/No document filenames in this standalone preview/g,'No resumes recorded');
if(/localStorage\.|indexedDB\./.test(source))throw Error('Browser persistence remains: '+source.match(/.{0,70}(?:localStorage\.|indexedDB\.).{0,70}/g)?.join('\n'));
const emailPattern=/const EMAIL_STUDIO_DOCUMENT=("(?:\\.|[^"\\])*");/;
if(JSON.parse(match[1].match(emailPattern)[1])!==JSON.parse(source.match(emailPattern)[1]))throw Error('Approved embedded Email Studio changed.');
source=source.replace('native.renderAccess();','native.renderAccess();installEmployees(native);');
const generated='// Generated from immutable approved V12 HTML. Source SHA-256: '+hash+'\nimport {native} from "./approved-api.mjs";\nimport {installEmployees} from "./employees.mjs";\nimport {installJDDashboard} from "./jd-dashboard.mjs";\nimport {installJDSync} from "./jd-sync.mjs";\nimport {installCleanJD} from "./jd-clean.mjs";\nimport {installWorkspaceSelectors} from "./workspace-selectors.mjs";\nimport {installEmailWorkspace,installContextualEmail} from "./email-studio.mjs";\nimport {canComposePipelineEmail,pipelineEmailContext} from "./pipeline-email.mjs";\nimport {submitCreation,nativeFieldErrors,candidatePeriodErrors} from "./creation-forms.mjs";\nimport {installCandidateDesk} from "./candidate-desk.mjs";\nimport {installCandidateRegisters,registrationDate} from "./candidate-registers.mjs";\n'+source;
let shell=html.slice(0,match.index)+`<script type="module" src="/static/ats-v2/approved.mjs"></script>\n</body></html>`;
shell=shell.replace('<body>','<body data-section="{{ workspace_section }}">').replace('INTERACTIVE HTML PREVIEW</b> · Local demo data','SQLITE WORKSPACE</b> · Loading records').replace('<title>','<link rel="icon" href="/static/stage2/favicon.svg" type="image/svg+xml"><title>');
shell=shell.replace('</head>','<link rel="stylesheet" href="/static/ats-v2/email-workspace.css"></head>').replace('JD Tracking</button>','JD Tracking</button><button id="unifiedEmailTab" type="button" role="tab" aria-selected="false">Email</button>').replace('<div id="emailStudioOverlay"',emailWorkspaceMarkup()+'<div id="emailStudioOverlay"').replace('three independent workspaces','four independent workspaces');
// Approved position-only change: keep logo, dimensions and tab styling intact.
shell=shell.replace('.unified-header{display:flex;justify-content:space-between;', '.unified-header{display:flex;justify-content:flex-start;');
// CSS selectors such as `{#emailStudioOverlay` are literal CSS, not Jinja comments.
shell='{% raw %}'+shell.replace('{{ workspace_section }}','{% endraw %}{{ workspace_section }}{% raw %}')+'{% endraw %}';
shell=shell.replace(/(<div role="tablist" class="unified-switcher" aria-label="Recruitment workspaces">)([\s\S]*?)(<\/div>)/,(_,open,body,close)=>{
 const buttons=Object.fromEntries([...body.matchAll(/<button id="([^"]+)"[^>]*>[\s\S]*?<\/button>/g)].map(m=>[m[1],m[0].replace(/aria-selected="(?:true|false)"/,`aria-selected="${m[1]==='unifiedJDTab'}"`)]));
 buttons.unifiedEmployeesTab='<button id="unifiedEmployeesTab" type="button" role="tab" aria-selected="false">Employees</button>';
 return open+['unifiedJDTab','unifiedCandidateTab','unifiedEmailTab','unifiedCompaniesTab','unifiedEmployeesTab'].map(id=>buttons[id]).join('')+close;
});
shell=shell.replace('</style>','\n.unified-header{height:62px;min-height:62px;padding:0 24px;gap:24px}.unified-brand{font-size:25px}.unified-switcher{height:62px;align-items:stretch}.unified-switcher{background:white;border-radius:0;padding:0}.unified-switcher button{background:white;border-radius:0;box-shadow:none;padding:0 17px;border-bottom:3px solid transparent}.unified-switcher button[aria-selected="true"]{box-shadow:none;border-bottom-color:#ce2333}@media(max-width:700px){.unified-header{height:auto;padding:10px 12px}.unified-switcher{height:35px}}\n</style>');
const outputs=[['src/jobmitra/static/ats_v2/approved.mjs',generated],['src/jobmitra/templates/v12/approved.html',shell],['src/jobmitra/static/ats_v2/jd-clean.css',cleanJDStyles()],['src/jobmitra/static/ats_v2/jd-workspace.css',workspaceStyles()],['src/jobmitra/static/ats_v2/email-workspace.css',emailWorkspaceStyles()]];
if(check){
 for(const [path,contents] of outputs)if(!fs.readFileSync(path).equals(Buffer.from(contents)))throw Error('Generated artifact differs: '+path);
 console.log('Approved reference and generated artifacts verified byte-for-byte.');
}else{
 for(const [path,contents] of outputs)fs.writeFileSync(path,contents);
 fs.mkdirSync('runtime/v12-parity',{recursive:true});
fs.writeFileSync('runtime/v12-parity/generation-report.json',JSON.stringify({source:reference,sha256:hash,functionsReplaced:filtered.length,originalBytesUnchanged:fs.readFileSync(reference).equals(bytes)},null,2));
console.log('Generated approved shell and component runtime. Immutable reference preserved.');
}

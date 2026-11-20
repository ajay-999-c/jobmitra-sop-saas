// Small integrations around the approved UI; original components and composers stay intact.
const workspaces=[['unifiedCompaniesTab','companies','companies'],['unifiedCandidateTab','candidates','candidate'],['unifiedJDTab','jobs','jd']];
export function installWorkspaceShell(native){
 const nav=document.querySelector('[aria-label="Recruitment workspaces"]');
 if(!nav)return;
 let initialized=false,proposal=null,proposalRequest=0;
 const current=()=>workspaces.find(([id])=>document.getElementById(id)?.getAttribute('aria-selected')==='true');
 const sync=()=>{
  const item=current();if(!item||!window.JobmitraUnified)return;
  const path='/workspace-v12/'+item[1];
  if(location.pathname!==path)history[initialized?'pushState':'replaceState']({workspace:item[1]},'',path);
  initialized=true;installProposalButton();
 };
 new MutationObserver(sync).observe(nav,{subtree:true,attributes:true,attributeFilter:['aria-selected']});
 window.addEventListener('popstate',()=>{
  const section=location.pathname.match(/^\/workspace-v12\/(companies|candidates|jobs)\/?$/)?.[1];
  const item=workspaces.find(x=>x[1]===section);if(item)window.JobmitraUnified?.show(item[2]);
 });
 function installProposalButton(){
  const root=document.getElementById('companiesHost')?.shadowRoot;
  const anchor=root?.getElementById('companyShowJDs');if(!anchor)return;
  let button=root.getElementById('prepareCompanyProposal');
  if(!button){
   button=document.createElement('button');button.id='prepareCompanyProposal';button.type='button';
   button.className=anchor.className;button.textContent='Prepare Proposal';anchor.after(button);
   button.addEventListener('click',()=>native.run(()=>openProposal(window.JobmitraUnifiedCompanies.getSelectedCompanyId(),button)));
  }
  button.disabled=!native.companies.some(c=>c.id===window.JobmitraUnifiedCompanies?.getSelectedCompanyId());
 }
 window.addEventListener('jobmitra-native-update',installProposalButton);
 if(window.JobmitraUnified)sync();
 const overlay=document.getElementById('emailStudioOverlay'),frame=document.getElementById('emailStudioFrame');
 if(!overlay||!frame)return;
 const heading=overlay.querySelector('.studio-head strong'),originalHeading=heading.textContent;
 window.JobmitraProposalAuthorize=()=>native.authorize();
 const restore=()=>{
  if(!proposal)return;const state=proposal;proposal=null;++proposalRequest;
  frame.removeAttribute('src');frame.inert=false;frame.onload=null;
  heading.textContent=originalHeading;state.opener.focus();
 };
 new MutationObserver(()=>{if(overlay.hidden)restore();}).observe(overlay,{attributes:true,attributeFilter:['hidden']});
 async function openProposal(companyId,opener){
  if(!companyId)throw Error('Choose an existing company first.');
  const request=++proposalRequest;
  const context=await native.api('/api/v12/approved/companies/'+encodeURIComponent(companyId)+'/proposal-context');
  if(request!==proposalRequest)return;
  proposal={opener};heading.textContent='Email Studio · Company Proposal · '+context.company_name;
  frame.onload=null;frame.inert=false;frame.removeAttribute('srcdoc');
  frame.src='/api/v12/approved/companies/'+encodeURIComponent(companyId)+'/proposal-workspace';
  overlay.hidden=false;document.getElementById('closeEmailStudio').focus();
 }
}

// Split the existing integrated components, preserving their markup and handlers.
// The immutable preview supplies design; none of its prototype persistence is used.
import {parse} from '@babel/parser';
import crypto from 'node:crypto';
export const fingerprint=text=>crypto.createHash('sha256').update(text).digest('hex').slice(0,16);
export function lazyWorkspace(source,imports){
 const ast=parse(source,{sourceType:'script'}),outer=ast.program.body.find(n=>n.type==='ExpressionStatement').expression.callee;
 const nodes=outer.body.body,code=n=>source.slice(n.start,n.end).replace(/^[ \t]+$/gm,''),find=prefix=>{const n=nodes.find(n=>code(n).startsWith(prefix));if(!n)throw Error('Missing lazy component boundary '+prefix);return code(n);};
 const iifes=nodes.filter(n=>n.type==='ExpressionStatement'&&/^(\(\(\)=>|\(\(root\)=>)/.test(code(n)));
 if(iifes.length!==3)throw Error('Expected three existing workspace components');
 const importNodes=parse(imports,{sourceType:'module'}).program.body;
 const needed=body=>importNodes.filter(n=>n.type==='ImportDeclaration'&&n.specifiers.some(s=>new RegExp('\\b'+s.local.name+'\\b').test(body))).map(n=>imports.slice(n.start,n.end)).join('\n');
 const context='{hostCompanies,hostCandidate,hostJD,candidateShadow,jdShadow,companyShadow,activate}';
 const parts={
  jd:[find('jdShadow.innerHTML'),find('const jmAmberStyle='),find('jmAmberStyle.textContent='),find('jdShadow.appendChild'),code(iifes[0]),'installWorkspaceSelectors(native,jdShadow);'].join('\n'),
  candidate:[find('candidateShadow.innerHTML'),code(iifes[1]),'installWorkspaceSelectors(native,candidateShadow);'].join('\n'),
  companies:[find('companyShadow.innerHTML'),code(iifes[2])].join('\n'),
  email:[find('const EMAIL_STUDIO_DOCUMENT='),find('installEmailWorkspace('),find('installContextualEmail(')].join('\n')
 };
 const modules=Object.entries(parts).map(([area,body])=>[`src/jobmitra/static/ats_v2/approved-${area}.mjs`,needed(body)+'\nexport function mount('+context+'){\n'+body+'\n}\n']);
 const urls=Object.fromEntries(modules.map(([path,body])=>[path.match(/approved-(.*)\.mjs/)[1],'./'+path.split('/').at(-1)+'?v='+fingerprint(body)]));
 const bootstrap=`import {native} from './approved-api.mjs';
const paths=${JSON.stringify(urls)},loaded=new Map();let epoch=0;
const hostCompanies=document.getElementById('companiesHost'),hostCandidate=document.getElementById('candidateHost'),hostJD=document.getElementById('jdHost');
const candidateShadow=hostCandidate.attachShadow({mode:'open'}),jdShadow=hostJD.attachShadow({mode:'open'}),companyShadow=hostCompanies.attachShadow({mode:'open'});
const context={hostCompanies,hostCandidate,hostJD,candidateShadow,jdShadow,companyShadow,activate};
async function ensure(area){if(!loaded.has(area))loaded.set(area,(async()=>{if(['candidate','companies'].includes(area))await native.refresh();const module=await import(paths[area]);module.mount(context);})().catch(error=>{loaded.delete(area);throw error;}));return loaded.get(area);}
async function activate(which){const area=which==='email'?'email':which==='companies'?'companies':which==='jd'?'jd':'candidate',ticket=++epoch;await ensure(area);if(ticket!==epoch)return false;
 hostCompanies.hidden=area!=='companies';hostCandidate.hidden=area!=='candidate';hostJD.hidden=area!=='jd';document.getElementById('emailHost').hidden=area!=='email';const employees=document.getElementById('employeesHost');if(employees)employees.hidden=true;
 for(const [id,key]of [['unifiedCompaniesTab','companies'],['unifiedCandidateTab','candidate'],['unifiedJDTab','jd'],['unifiedEmailTab','email'],['unifiedEmployeesTab','employees']])document.getElementById(id).setAttribute('aria-selected',String(area===key));
 if(area==='candidate')window.JobmitraUnifiedCandidate?.refreshJobs?.();if(area==='companies')window.JobmitraUnifiedCompanies?.refreshFromJD?.();window.scrollTo({top:0,behavior:'instant'});return true;
}
window.JobmitraUnified={openCandidate:async id=>{await activate('candidate');window.JobmitraUnifiedCandidate?.showCandidateHistory(id);},openJD:async(id,stage)=>{await activate('jd');await window.JobmitraUnifiedJD?.openJob(String(id),stage);},openCompany:async id=>{await activate('companies');window.JobmitraUnifiedCompanies?.showCompany?.(id);},show:where=>activate(where==='email'?'email':where==='jd'?'jd':where==='companies'?'companies':'candidate')};
window.JobmitraUnified.openEmailStudio=async context=>{await ensure('email');return window.JobmitraUnified.openEmailStudio(context);};
window.JobmitraUnified.openProfileEmail=async id=>{await ensure('email');return window.JobmitraUnified.openProfileEmail(id);};
candidateShadow.addEventListener('click',event=>{const b=event.target.closest('button');if(!b||loaded.has('email'))return;if(b.dataset.emailProfile){event.stopImmediatePropagation();void window.JobmitraUnified.openProfileEmail(b.dataset.emailProfile);}else if(b.dataset.emailJob){event.stopImmediatePropagation();void window.JobmitraUnified.openEmailStudio({jobId:b.dataset.emailJob,candidates:[{id:b.dataset.emailCandidate}]});}});
for(const [id,area]of [['unifiedJDTab','jd'],['unifiedCandidateTab','candidate'],['unifiedCompaniesTab','companies'],['unifiedEmailTab','email']])document.getElementById(id).addEventListener('click',()=>native.run(()=>activate(area)));
let employeeModule;async function employees(){++epoch;if(!employeeModule){const m=await import('./employees.mjs');employeeModule=m.installEmployees(native);}if(document.getElementById('employeesHost')?.hidden)employeeModule.show();}
document.getElementById('unifiedEmployeesTab').addEventListener('click',()=>native.run(employees),{once:true});
${find('function syncHeaderOffset')}
syncHeaderOffset();window.addEventListener('resize',syncHeaderOffset);
(async()=>{await native.loadAccess();await native.bootstrap();native.renderAccess();const section=document.body.dataset.section;if(section==='employees')await employees();else await activate(section==='jobs'?'jd':section==='candidates'?'candidate':section==='email'?'email':'companies');})().catch(error=>{hostJD.hidden=false;hostJD.textContent='Workspace could not load: '+error.message;});
`;
 return {bootstrap,modules};
}

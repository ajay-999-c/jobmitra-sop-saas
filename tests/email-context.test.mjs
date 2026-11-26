import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import {contextualEmailDocument} from '../src/jobmitra/static/ats_v2/email-context.mjs';
import {pipelineEmailContext} from '../src/jobmitra/static/ats_v2/pipeline-email.mjs';
const source=fs.readFileSync('Jobmitra_Unified_Workspace_V12_Companies_Integrated (1).html','utf8');
const approved=JSON.parse(source.match(/const EMAIL_STUDIO_DOCUMENT=("(?:\\.|[^"\\])*");/)[1]);
const corrected=contextualEmailDocument(approved);
test('context correction preserves approved HTML/CSS, table rendering and logo bytes',()=>{
 assert.equal(corrected.replace(/<script>[\s\S]*?<\/script>/,''),approved.replace(/<script>[\s\S]*?<\/script>/,''));
 assert.equal(corrected.slice(corrected.indexOf('function detailRow'),corrected.indexOf('function updateStageFields')).replace('`Dear <strong>${escapeHtml(companyRecipient())}</strong>,`','`Hi <strong>${data.company}</strong>,`'),approved.slice(approved.indexOf('function detailRow'),approved.indexOf('function updateStageFields')));
 new Function(corrected.match(/<script>([\s\S]*?)<\/script>/)[1]);
});
function render(status,complete=false){
 const fields={candidateStatus:status,candidateName:'Synthetic Candidate',companyName:'Synthetic Client Company',jobPosition:'Synthetic Engineer',jobLocation:'Test City',roundName:'Portfolio Discussion',interviewDate:'2030-01-01',interviewTime:'10:00',f2fDate:'2030-01-01',f2fTime:'10:00',f2fVenue:'Test Venue',technicalDate:'2030-01-01',technicalTime:'10:00',finalDate:'2030-01-01',finalTime:'10:00',interviewMode:'Face-to-Face',recipientEmail:'hr@example.test'};
 const escapeHtml=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;');
 const ctx=vm.createContext({get:id=>fields[id]||'',val:(id,fallback)=>escapeHtml(fields[id]||fallback),escapeHtml,joinDateTime:()=>'',formatDate:x=>x,formatTime:x=>x,formatNumericDate:x=>x,formatWeekday:()=> 'Tuesday',getMeetingUrl:()=>'',companyInterviewReadinessHtml:()=>'',companyContactOptions:[{name:'Synthetic HR',email:'hr@example.test'}],integratedContext:{roundCompleted:complete,nextRoundName:'Owner Discussion'},completedCustom:()=>status==='custom_round'&&complete,discloseCompany:s=>!['jobmitra_screening','screening_completed','screening_cleared','not_selected'].includes(s),LOGO_DATA_URL:'approved-logo',WEBSITE_URL:'https://www.jobmitra.com/',REVIEW_URL:'https://g.page/review',companyRecipient:()=> 'Synthetic HR'});
 vm.runInContext(corrected.slice(corrected.indexOf('function stageContent'),corrected.indexOf('function updateStageFields')),ctx);
 const data={name:fields.candidateName,role:fields.jobPosition,company:fields.companyName,location:fields.jobLocation,status};
 const content=ctx.stageContent(data);return {content,html:ctx.makeEmailHTML(data,content)};
}
for(const status of ['round1_completed','round1_cleared','round2_completed','round2_cleared','custom_round'])test(status+' retains canonical company without placeholders',()=>{
 const {html}=render(status,true);assert.ok(html.includes('Synthetic Client Company'));assert.ok(html.includes('Synthetic Candidate'));assert.ok(!html.includes('[Company]'));if(status==='custom_round'){assert.ok(html.includes('Portfolio Discussion'));assert.ok(html.includes('Owner Discussion'));assert.ok(!html.includes('INTERVIEW INVITATION'));}
});
test('F2F separates candidate, hiring company and contact salutation',()=>{const {html}=render('f2f_company');assert.ok(html.includes('Dear <strong>Synthetic HR</strong>'));assert.ok(html.includes('confirm that <strong>Synthetic Candidate</strong>'));assert.ok(html.includes('position at <strong>Synthetic Client Company</strong>'));});
test('F2F shortcut requests company audience and retains canonical candidate',async()=>{
 let audience;const context=await pipelineEmailContext({api:async path=>{audience=new URL('http://fixture'+path).searchParams.get('audience');return {candidate_id:1,job_id:2,company_id:'canonical-company',candidate_name:'Synthetic Candidate',candidate_email:'sample@example.test',company_name:'Synthetic Client Company',company_disclosed:true,recipient_name:'Synthetic HR',company_contact_name:'Synthetic HR',company_contact_email:'hr@example.test',job_title:'Synthetic Engineer',stage:'ROUND',round_id:'r',round_name:'Owner Discussion',contacts:[{id:'c',name:'Synthetic HR',email:'hr@example.test'}],selected_contact_id:'c'};}},{jobId:'2',status:'f2f_company',candidates:[{id:'1'}]});assert.equal(audience,'COMPANY');assert.equal(context.status,'f2f_company');assert.equal(context.candidateName,'Synthetic Candidate');assert.equal(context.companyContactName,'Synthetic HR');
});

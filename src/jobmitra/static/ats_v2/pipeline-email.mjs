// Resolve the existing Email Studio draft against canonical JD membership facts.
export function canComposePipelineEmail(stage){
 return ['POOL','CONTACT','SCREENING','COMPANY_SUBMISSION','SELECTED','JOINED','NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED'].includes(stage)||stage.startsWith('ROUND:');
}
export async function pipelineEmailContext(native,context){
 const people=context.candidates||[],ids=people.map(c=>c.id).filter(Boolean);
 if(!ids.length)throw Error('Choose a canonical JD membership.');
 let audience=context.status==='candidate_submission'?'COMPANY':'CANDIDATE';
 const load=()=>Promise.all(ids.map(id=>native.api('/api/v12/email-context?'+new URLSearchParams({candidate_id:id,job_id:context.jobId,audience}))));
 let facts=await load();
 // A row may have advanced since the pipeline snapshot was loaded.
 if(audience==='CANDIDATE'&&facts[0].stage==='COMPANY_SUBMISSION'){audience='COMPANY';facts=await load();}
 if(facts.some(f=>['NOT_JOINED','SELECTION_CANCELLED'].includes(f.selection_outcome)))throw Error('The approved Email Studio has no Not Joined or Selection Cancelled template. No misleading rejection/selection preview was generated.');
 const first=facts[0],status=audience==='COMPANY'?'candidate_submission':first.stage==='JOINED'?'joined':first.selection_outcome==='PENDING_JOINING'?'selected':first.stage==='NOT_SELECTED'?'not_selected':first.stage==='ROUND'?'custom_round':'jobmitra_screening';
 const sameRound=first.stage==='ROUND'&&first.round_id===context.roundId;
 return {...context,status,jobId:String(first.job_id),candidateId:String(first.candidate_id),candidateStage:first.stage,candidateName:first.candidate_name,companyName:first.company_name||'',jobTitle:first.job_title,location:first.location||'',candidateEmail:audience==='CANDIDATE'?(first.recipient_email||''):'',joiningDate:first.joined_on||'',roundName:first.round_name||'',interviewDate:sameRound?context.interviewDate||'':'',interviewTime:sameRound?context.interviewTime||'':'',companyContacts:first.contacts.map(c=>({id:c.id,name:c.name,email:c.email,is_primary:c.id===first.selected_contact_id})),candidates:people.map((p,i)=>({...p,id:String(facts[i].candidate_id),name:facts[i].candidate_name}))};
}

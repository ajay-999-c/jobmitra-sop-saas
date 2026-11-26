// Correct contextual fields/wording inside the immutable approved composer.
// The document's HTML/CSS, centered tables, logo and MIME adapter stay unchanged.
export function contextualEmailDocument(html){
 const replace=(before,after)=>{if(!html.includes(before)||html.indexOf(before)!==html.lastIndexOf(before))throw Error('Approved email context boundary changed.');html=html.replace(before,after);};
 replace("let isDemo = false;",`let isDemo = false;
 let integratedContext={};
 const companyTemplates=new Set(['interview_scheduled','technical_interview','custom_round','round1_completed','round1_cleared','round2_completed','round2_cleared','final_completed','selected','offer_received','joined']);
 const discloseCompany=s=>companyTemplates.has(s);
 const completedCustom=()=>get('candidateStatus')==='custom_round'&&integratedContext.roundCompleted===true;
 const companyRecipient=()=>companyContactOptions.find(c=>c.email.toLowerCase()===get('recipientEmail').toLowerCase())?.name||(integratedContext.companyEmail?.toLowerCase()===get('recipientEmail').toLowerCase()?integratedContext.companyContactName:'')||'Hiring Team';`);
 replace('      clearRecipientState();\n      // Context may',`      clearRecipientState();
      integratedContext={...ctx};
      for(const id of ['candidateName','jobPosition','companyName','jobLocation','roundName','interviewDate','interviewTime','joiningDate','technicalDate','technicalTime','technicalMeetingLink','technicalMeetingId','finalDate','finalTime','finalMeetingLink','finalMeetingId','f2fDate','f2fTime','f2fVenue','nextDate','nextTime','personalNote'])$(id).value='';
      $('roundName').value=ctx.roundName||'';
      $('submissionContact').value=ctx.companyContactName||'';
      // Context may`);
 const required=html.match(/    const getRequiredFields = \(\) =>[^\n]+;/)?.[0];
 if(!required)throw Error('Approved required-field boundary changed.');
 replace(required,required.replace('getRequiredFields','originalRequiredFields')+`
    const getRequiredFields=()=>{const s=get('candidateStatus'),fields=originalRequiredFields().filter(id=>!completedCustom()||!['interviewDate','interviewTime'].includes(id));if(discloseCompany(s))fields.push('companyName');if(['interview_scheduled','round1_completed','round1_cleared','round2_completed','round2_cleared','selected','offer_received','joined'].includes(s))fields.push('jobLocation');return [...new Set(fields)];};`);
 replace("const companyDisclosed = ['selected','offer_received','joined'].includes(status);",'const companyDisclosed = discloseCompany(status);');
 replace("if(!first && !['selected','offer_received','joined','f2f_company','candidate_submission'].includes(s)){","if(!first && !discloseCompany(s) && !['f2f_company','candidate_submission'].includes(s)){");
 replace("if(['interview_scheduled','jobmitra_screening','custom_round'].includes(s))requiredFields.push('interviewDate','interviewTime');","if(['interview_scheduled','jobmitra_screening','custom_round'].includes(s)&&!completedCustom())requiredFields.push('interviewDate','interviewTime');");
 replace("$('candidatePrivacyNotice').classList.toggle('hidden',['candidate_submission','f2f_company','selected','offer_received','joined'].includes(s));","$('candidatePrivacyNotice').classList.toggle('hidden',discloseCompany(s)||['candidate_submission','f2f_company'].includes(s));");
 replace("$('companyNameField').classList.toggle('hidden',!['candidate_submission','f2f_company','selected','offer_received','joined'].includes(s));","$('companyNameField').classList.toggle('hidden',!discloseCompany(s)&&!['candidate_submission','f2f_company'].includes(s));");
 replace("$('jobLocationField').classList.toggle('hidden',s!=='f2f_company'&&s!=='selected'&&s!=='offer_received'&&s!=='joined');","$('jobLocationField').classList.toggle('hidden',!discloseCompany(s)&&s!=='f2f_company');");
 replace("$('interviewScheduleFields').classList.toggle('hidden',!['interview_scheduled','jobmitra_screening','custom_round'].includes(s));","$('interviewScheduleFields').classList.toggle('hidden',completedCustom()||!['interview_scheduled','jobmitra_screening','custom_round'].includes(s));");
 replace("const companyInvitation=['interview_scheduled','technical_interview','custom_round'].includes(status);",`if(status==='custom_round'&&completedCustom()){
          const round=val('roundName','[Interview Round]'),next=escapeHtml(integratedContext.nextRoundName||'');
          content={...content,subject:get('roundName')+' Completed | '+get('jobPosition')+' — '+get('companyName'),eyebrow:'INTERVIEW PROGRESS',title:get('roundName')+' completed',sub:'Your recruitment progress update.',intro:'You have completed <strong>'+round+'</strong> for the <strong>'+role+'</strong> position at <strong>'+company+'</strong>.',statusLabel:get('roundName')+' Completed',details:[{label:'Position',value:role},{label:'Completed round',value:round},...(next?[{label:'Next round',value:next}]:[])],body:next?'The next configured interview round is <strong>'+next+'</strong>. Its schedule will be shared once confirmed.':'Our team will share the next confirmed recruitment update.',next:'Thank you for your time and effort.'};
        }
        const companyInvitation=['interview_scheduled','technical_interview','custom_round'].includes(status)&&!completedCustom();`);
 replace('position on <strong>${f2fDay}, ${f2fDate}</strong>.','position at <strong>${company}</strong> on <strong>${f2fDay}, ${f2fDate}</strong>.');
 replace("{label:'Candidate',value:name},","{label:'Candidate',value:name},\n              {label:'Hiring company',value:company},");
 replace('`Hi <strong>${data.company}</strong>,`','`Dear <strong>${escapeHtml(companyRecipient())}</strong>,`');
 // Same validator is used by Copy and Gmail Send; no separate rendered body.
 replace('    function validate() {','    function originalValidate() {');
 replace('    function originalValidate() {',`    function validate(){
      if(!originalValidate())return false;
      const s=get('candidateStatus'),body=$('emailBody').innerText,subject=$('emailSubject').value;
      if(integratedContext.candidateId&&get('candidateName')!==integratedContext.candidateName){showToast('Candidate name does not match this canonical profile. Reload candidate details.',true);return false;}
      if(integratedContext.jobId&&(discloseCompany(s)||['candidate_submission','f2f_company'].includes(s))&&(!integratedContext.companyDisclosed||get('companyName')!==integratedContext.companyName)){showToast('Hiring company is unavailable or differs from the selected JD. Open the correct interview context.',true);return false;}
      if(integratedContext.jobId&&get('jobPosition')!==integratedContext.jobTitle){showToast('Job title does not match the selected JD. Reload candidate details.',true);return false;}
      if(/\\[(?:company|candidate name|position|location|interview round|interview date|interview time|date|time|day)\\]/i.test(subject+' '+body)){showToast('Complete the missing contextual fields shown in brackets before copying or sending.',true);return false;}
      return true;
    }
    function originalValidate() {`);
 return html;
}

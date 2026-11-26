// Shared, form-local feedback for the approved registration and JD editors.
// State is memory-only; unchanged retries retain their key and committed result.
const states=new WeakMap(),active=new Set();
const candidateFields={phone:'mobile',job_title:'role',current_city:'location',experience_years:'months',current_salary_inr:'current_salary',current_salary_period:'current_period',expected_salary_inr:'expected_salary',expected_salary_period:'expected_period',notice_days:'notice',filename:'resume',file_base64:'resume'};
const jobFields={company_id:'company',target_date:'targetDate',company_contact:'companyContact',work_mode:'workMode',experience_min:'experienceMin',experience_max:'experienceMax',salary_min_inr:'salaryMin',salary_max_inr:'salaryMax',salary_period:'salaryPeriod',salary_basis:'salaryBasis',requirement_notes:'notes',full_jd:'fullJD'};
export function creationScope(path,method,body){return JSON.stringify([path,method,body]);}
export function clearFormErrors(form){
 for(const node of form.querySelectorAll('[data-creation-error]'))node.remove();
 for(const control of form.querySelectorAll('[data-creation-invalid]')){
  control.removeAttribute('aria-invalid');control.removeAttribute('aria-errormessage');control.removeAttribute('data-creation-invalid');control.style.removeProperty('border-color');
 }
}
export function showFormErrors(form,kind,errors,message='Please correct the highlighted fields.'){
 clearFormErrors(form);
 const summary=document.createElement('div');summary.dataset.creationError='';summary.className='field-note';summary.setAttribute('role','alert');summary.tabIndex=-1;summary.textContent=message;summary.style.cssText='color:#b91c1c;padding:12px;border:1px solid #efb4b4;border-radius:8px;margin:8px 0;grid-column:1 / -1';
 (form.querySelector('.reg-body')||form).prepend(summary);
 let first;
 for(const [index,error] of errors.entries()){
  const name=(kind==='candidate'?candidateFields:jobFields)[error.field]||error.field;
  const canonical=form.elements.namedItem(error.field)||form.elements.namedItem('extra.'+error.field)||form.elements.namedItem(name);if(!canonical||!canonical.setAttribute)continue;
  const control=canonical.matches?.('select')&&canonical.closest('.searchable-select')?.querySelector('[role=combobox]')||canonical;
  for(let parent=control.parentElement;parent&&parent!==form;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
  const note=document.createElement('span');note.id=form.id+'-error-'+index;note.dataset.creationError='';note.textContent=error.message;note.style.cssText='display:block;color:#b91c1c;font-size:12px;margin-top:4px';
  control.setAttribute('aria-invalid','true');control.setAttribute('data-creation-invalid','');control.setAttribute('aria-errormessage',note.id);control.style.borderColor='#b91c1c';control.insertAdjacentElement('afterend',note);
  first||=control;
 }
 const target=first||summary;target.scrollIntoView({block:'center'});target.focus({preventScroll:true});
}
export function nativeFieldErrors(form){
 return [...form.elements].filter(c=>c.willValidate&&!c.validity.valid).map(c=>({field:c.dataset?.canonicalField||c.name,message:c.validity.valueMissing?'Please complete this required field.':c.validity.typeMismatch?'Please enter a valid email address.':'Please enter a valid value within the allowed range.'})).filter((e,i,rows)=>rows.findIndex(r=>r.field===e.field)===i);
}
export function candidatePeriodErrors(form){
 return ['current','expected'].filter(p=>form.elements[p+'_salary'].value!==''&&!form.elements[p+'_period'].value).map(p=>({field:p+'_period',message:'Please select the '+p+' salary period.'}));
}
export async function submitCreation(form,kind,action,onError){
 if(!form||active.has(kind))return null;
 active.add(kind);clearFormErrors(form);form.noValidate=true;
 const buttons=[...form.querySelectorAll('button[type="submit"]')],disabled=buttons.map(b=>b.disabled);
 buttons.forEach(b=>b.disabled=true);form.setAttribute('aria-busy','true');
 if(!states.has(form))states.set(form,{results:new Map(),committed:false});
 const state=states.get(form);
 try{
  return await action({
   validate(errors){if(errors.length){showFormErrors(form,kind,errors);return false;}return true;},
   async request(native,path,body,method='POST'){
    const scope=creationScope(path,method,body);
    if(!state.results.has(scope))state.results.set(scope,await native.api(path,body,method,form,scope));
    state.committed=true;return state.results.get(scope);
   }
  });
 }catch(error){
  const errors=error.fieldErrors||[];
  const message=state.committed?'The record was saved, but a follow-up step failed. Retry to finish loading it.':error.userFacing?error.message:'Unable to save the '+(kind==='candidate'?'candidate':'JD')+'. Please try again.';
  showFormErrors(form,kind,errors,message);onError?.(error);return null;
 }finally{
  active.delete(kind);form.removeAttribute('aria-busy');buttons.forEach((b,i)=>b.disabled=disabled[i]);
 }
}

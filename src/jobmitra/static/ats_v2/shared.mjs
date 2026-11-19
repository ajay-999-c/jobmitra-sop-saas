export const $ = (selector, root=document) => root.querySelector(selector);
export const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
export const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export const words = value => String(value || '').split(',').map(item=>item.trim()).filter(Boolean);
export const money = value => value == null ? 'Not recorded' : '₹'+Number(value).toLocaleString('en-IN');
export const date = value => value ? new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',...(String(value).includes('T')?{hour:'2-digit',minute:'2-digit'}:{})}).format(new Date(String(value).includes('T')?value:value+'T12:00:00+05:30')) : 'Not recorded';
export const pretty = value => String(value || '').toLowerCase().replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
export const pill = (value,tone='') => `<span class="ats-pill ${esc(tone)}">${esc(value)}</span>`;
export const empty = (title,detail='') => `<div class="ats-empty"><strong>${esc(title)}</strong>${esc(detail)}</div>`;
export const list = value => Array.isArray(value)?value:[];
export async function api(path,options={}) {
  const response=await fetch('/api/ats-v2'+path,{credentials:'same-origin',cache:'no-store',...options,headers:{'X-Jobmitra-UI':'1',...options.headers}});
  let data;
  try {data=await response.json();} catch {throw Error('The server returned an unreadable response. Reload and try again.');}
  if(!response.ok) {
    const detail=data.detail;
    throw Error(Array.isArray(detail)?detail.map(item=>`${item.loc?.slice(1).join(' / ') || 'Value'}: ${item.msg}`).join('\n'):typeof detail==='string'?detail:detail?.message||'This operation could not be completed.');
  }
  return data;
}
export const save = (path,data,method='POST') => api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
export function error(err){$('#ats-error').textContent=err.message||String(err);$('#ats-error').hidden=false;$('#ats-error').scrollIntoView({behavior:'smooth',block:'nearest'});}
export function clear(){ $('#ats-error').hidden=true;$('#ats-notice').hidden=true; }
export function notice(message){$('#ats-notice').textContent=message;$('#ats-notice').hidden=false;}
export function bindErrors(handler){return async event=>{try{await handler(event);}catch(err){error(err);}};}
export function field(name,label,value='',options={}) {
  const {type='text',required=false,span=false,choices=null,step=null,min=null,max=null}=options;
  let input;
  const attr=`name="${esc(name)}" ${required?'required':''}`;
  if(choices) input=`<select ${attr}>${choices.map(item=>{const [v,t]=Array.isArray(item)?item:[item,pretty(item)];return `<option value="${esc(v)}" ${String(v)===String(value??'')?'selected':''}>${esc(t)}</option>`;}).join('')}</select>`;
  else if(type==='textarea') input=`<textarea ${attr} maxlength="30000">${esc(value)}</textarea>`;
  else input=`<input ${attr} type="${esc(type)}" value="${esc(value)}" ${type==='number'?'': 'maxlength="400"'} ${step!==null?`step="${esc(step)}"`:''} ${min!==null?`min="${esc(min)}"`:''} ${max!==null?`max="${esc(max)}"`:''}>`;
  return `<label class="${span?'ats-span':''}">${esc(label)}${required?' *':''}${input}</label>`;
}
export function values(form){return Object.fromEntries(new FormData(form));}
export function numberOrNull(value){return value===''||value==null?null:Number(value);}
export function dialog(title,body,submitLabel='Save',handler=null){
  const host=$('#ats-dialog');
  $('#ats-dialog-content').innerHTML=`<div class="ats-dialog-head"><h2 id="ats-dialog-title">${esc(title)}</h2><button type="button" class="ats-btn ats-secondary ats-small" id="ats-dialog-close" aria-label="Close dialog">✕</button></div><form id="ats-dialog-form" class="ats-dialog-body">${body}<p id="ats-dialog-error" class="ats-alert ats-error" role="alert" hidden></p><div class="ats-form-footer"><span class="ats-hint">Changes are saved to the new workspace.</span><div class="ats-actions"><button type="button" class="ats-btn ats-secondary" id="ats-dialog-cancel">Cancel</button>${handler?`<button class="ats-btn" type="submit">${esc(submitLabel)}</button>`:''}</div></div></form>`;
  $('#ats-dialog-close').onclick=()=>host.close();$('#ats-dialog-cancel').onclick=()=>host.close();
  if(handler) $('#ats-dialog-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;$('#ats-dialog-error').hidden=true;try {await handler(values(event.target),event.target);host.close();}catch(err){$('#ats-dialog-error').textContent=err.message;$('#ats-dialog-error').hidden=false;}finally{button.disabled=false;}};
  if(!host.open)host.showModal();
  return host;
}
export function history(items){
  if(!items?.length)return empty('No history yet','Saved changes and candidate movements will appear here.');
  return items.map(item=>`<article class="ats-history"><b>${esc(pretty(item.event_type))}</b><time datetime="${esc(item.created_at)}">${esc(date(item.created_at))} IST</time>${item.from_label_snapshot||item.to_label_snapshot?`<p>${esc(item.from_label_snapshot||'')} ${item.to_label_snapshot?'→ '+esc(item.to_label_snapshot):''}</p>`:''}${item.feedback?`<p>${esc(item.feedback)}${item.feedback_source?' · '+esc(pretty(item.feedback_source)):''}</p>`:''}${item.before_json||item.after_json?`<details><summary>View recorded changes</summary><pre>${esc(JSON.stringify({before:item.before_json,after:item.after_json},null,2))}</pre></details>`:''}</article>`).join('');
}

export function resumeVersion(resume){
  const parsed=resume.resume_kind==='PARSED_TEXT';
  const imported=resume.historical_parsed_json!=null;
  const label=imported?'View imported parsed JSON':'View saved professional JSON';
  const content=parsed?`<button class="ats-link" type="button" data-resume-json="${esc(resume.id)}">${esc(label)}</button>`:resume.downloadable?`<a class="ats-link" href="/api/ats-v2/resumes/${esc(resume.id)}/download" target="_blank" rel="noopener noreferrer">${esc(resume.original_filename||'Download version')}</a>`:`<span class="ats-muted">Source file unavailable · metadata preserved</span>${resume.file_status?`<p class="ats-hint">File status: ${esc(pretty(resume.file_status))}</p>`:''}`;
  return `<div class="ats-resume-row"><strong>${esc(pretty(resume.resume_kind))}</strong> ${resume.is_current?pill('Current','ats-green'):pill('Preserved')}${resume.requires_review?' '+pill('Review required','ats-amber'):''}<br>${content}${resume.requires_review?'<p class="ats-hint">Imported historical evidence. Review against the original before using it for a new standardized resume.</p>':''}<p class="ats-hint">Version #${esc(resume.id)} · ${esc(date(resume.created_at))} IST</p></div>`;
}

const raw = document.querySelector('#foundit-raw');
const form = document.querySelector('#foundit-review');
const fields = document.querySelector('#foundit-fields');
const status = document.querySelector('#foundit-status');
const error = document.querySelector('#foundit-error');
const confirmed = document.querySelector('#foundit-confirm');
const results = document.querySelector('#foundit-results');
const save = document.querySelector('#foundit-save');
let draftExtras = false, parsedSource = ''; 
let linked = null, busy = false, dirty = false, previewReady = false, matchSerial = 0;
const editedFields = new Set();
const inputs = [...form.querySelectorAll('[name]')];
const labels = Object.fromEntries([...form.querySelectorAll('[data-review-field]')].map(el => [el.dataset.reviewField, el.querySelector('label').firstChild.textContent.trim()]));
function value(input) {
  const text = input.value.trim();
  if (input.dataset.valueKind === 'boolean') return text === '' ? null : text === 'true';
  if (input.dataset.valueKind === 'array') return [...new Map(text.split(/[,\n]/).map(s => s.trim().replace(/\s+/g,' ')).filter(Boolean).map(s => [s.toLowerCase(),s])).values()];
  if (input.dataset.valueKind === 'number') return text === '' ? null : Number(text);
  return text || null;
}
function values() { return Object.fromEntries(inputs.map(input => [input.name, value(input)])); }
function display(v) { return Array.isArray(v) ? v.join(', ') : v == null ? 'Not recorded' : String(v); }
function fail(message) { error.textContent = message; error.hidden = false; status.textContent = 'Failed — nothing confirmed saved. ' + message; }
async function api(url, method='GET', body) {
  const response = await fetch(url,{method,cache:'no-store',headers:{'Content-Type':'application/json','X-Jobmitra-UI':'1'}, ...(body ? {body:JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw Error(Array.isArray(data.detail) ? data.detail.map(e => e.loc.slice(1).join(' ') + ': ' + e.msg).join('\n') : data.detail || 'Request failed.');
  return data;
}
async function action(work) {
  if (busy) return;
  busy = true; error.hidden = true; fields.disabled = true;
  document.querySelector('#foundit-parse').disabled = true;
  document.querySelector('#foundit-clear').disabled = true;
  try { await work(); } catch(e) { fail(e.message || 'Network unavailable. Check the candidate before retrying.'); }
  finally { busy = false; fields.disabled = !previewReady; document.querySelector('#foundit-parse').disabled = false; document.querySelector('#foundit-clear').disabled = false; }
}
function comparisons() {
  form.querySelectorAll('[data-review-field]').forEach(box => {
    const old = box.querySelector('[data-existing]'); old.hidden = !linked;
    box.querySelector('[data-accept-label]').hidden = !linked;
    old.textContent = linked ? 'Current: ' + display(linked[box.dataset.reviewField]) : '';
  });
  document.querySelector('#foundit-accept-domain').hidden = !linked;
  const domainInfo = document.querySelector('#foundit-existing-domain'); domainInfo.hidden = !linked;
  const optionName = (name, id) => [...form.elements[name].options].find(o=>o.value === id)?.textContent || id || 'Not recorded';
  domainInfo.textContent = linked ? `Current domain: ${optionName('domain_id',linked.domain_id)} / ${optionName('subdomain_id',linked.subdomain_id)}. Only change this pair after review.` : '';
  document.querySelector('#foundit-linked').textContent = linked ? `Linked for review: ${linked.full_name} · ${linked.mobile}. Version ${linked.version}.` : 'No candidate linked.';
  save.textContent = linked ? 'Save Reviewed Changes' : 'Create New Candidate';
  const link = document.querySelector('#foundit-profile'); link.hidden = !linked;
  if (linked) link.href = '/candidates/' + linked.id;
}
async function showMatches(rows) {
  results.replaceChildren();
  const p = document.createElement('p'); p.textContent = rows.length ? 'Possible matches. Link a profile only after verifying identity. No fields have been changed.' : 'No matching profile found. The server checks again on save.'; results.append(p);
  for(const row of rows) {
    const item = document.createElement('article'); const text = document.createElement('p'); text.textContent = `${row.full_name} · ${row.mobile} · ${row.email || 'No email'}`;
    const button = document.createElement('button'); button.type='button'; button.className='secondary'; button.textContent='Link for review';
    button.addEventListener('click', () => action(async () => {
      linked = await api('/api/candidates/' + row.id);
      form.querySelectorAll('[data-accept]').forEach(el=>el.checked=false); confirmed.checked=false;
      comparisons(); status.textContent='Linked for review. Select the fields to update; nothing saved.';
    })); item.append(text,button); results.append(item);
  }
}
async function matchContacts() {
  const data=values(), serial=++matchSerial;
  const params = new URLSearchParams();
  if(data.mobile) params.set('mobile',data.mobile);
  if(data.email) params.set('email',data.email);
  const rows = await api('/api/candidates/duplicates?' + params);
  if(serial === matchSerial) await showMatches(rows);
  return rows;
}
function renderPreview(preview) {
  for(const input of inputs) {
    const v=preview.fields[input.name]; input.value = Array.isArray(v) ? v.join('\n') : v ?? (input.name === 'current_salary_period' ? 'Unknown' : '');
  }
  form.querySelector('[data-catalog-picker]').dispatchEvent(new CustomEvent('catalog-select', {detail:{}}));
  const evidence=document.querySelector('#foundit-evidence'); evidence.replaceChildren();
  form.querySelectorAll('[data-warning]').forEach(el=>{el.hidden=true;el.textContent='';});
  for(const item of preview.evidence) {
    const box = form.querySelector(`[data-review-field="${item.field}"] [data-warning]`);
    if(box && /ambiguous|invalid|incomplete|possible|conflicting|unclear|multiple/i.test(item.note)) {box.hidden=false;box.textContent=item.note;} 
    const p=document.createElement('p'); const b=document.createElement('strong'); b.textContent=(labels[item.field] || item.field) + ': ';
    p.append(b,document.createTextNode(item.note + '\nSource: ' + item.raw)); evidence.append(p);
  }
  const extras=document.querySelector('#foundit-extra'); extras.replaceChildren();
  document.querySelector('#foundit-industry').replaceChildren();document.querySelector('#foundit-education').replaceChildren();
  function draftField(parent, key, labelText, v) {
    const label=document.createElement('label'); label.textContent=labelText;
    const input=document.createElement('textarea'); input.rows=2; input.value=v || ''; input.dataset.draftKey=key;
    label.append(input);parent.append(label);
  }
  for(const [key,labelText] of [['industry','Current industry'],['past_industry','Past industry'],['institution','University / institution'],['education_year','Education year']]) {
    const target=key === 'industry' ? document.querySelector('#foundit-industry') : ['institution','education_year'].includes(key) ? document.querySelector('#foundit-education') : extras;
    draftField(target,key,labelText+' (draft only)',preview.preview_only[key]);
  }
  preview.employment_history.forEach((record,index)=>{
    const section=document.createElement('section'); const heading=document.createElement('h4');heading.textContent=record.kind+' employment '+(index+1);section.append(heading);
    const warning=document.createElement('p');warning.className='foundit-warning';warning.textContent=record.warning;section.append(warning);
    for(const key of ['role','employer','start','end','industry','raw']) draftField(section,`employment.${index}.${key}`,key === 'raw' ? 'Original employment wording' : key,record[key]);
    extras.append(section);
  });
  draftExtras=true;
  for(const key of preview.missing) {
    const warning=form.querySelector(`[data-review-field="${key}"] [data-warning]`);
    if(warning) {warning.hidden=false;warning.textContent='Missing — enter a confirmed value.';}
  }
  previewReady=true; dirty=true; linked=null; editedFields.clear(); confirmed.checked=false;
  form.querySelectorAll('[data-accept]').forEach(el=>el.checked=false);
  comparisons(); results.replaceChildren();
  status.textContent='Needs confirmation. Nothing saved.' + (preview.missing.length ? ' Missing: ' + preview.missing.join(', ') + '.' : ' Verify all contact details.');
}
document.querySelector('#foundit-parse').addEventListener('click',()=>action(async()=>{
  if(dirty && !window.confirm('Replace this unsaved review draft?')) return;
  status.textContent='Parsing locally…';
  const source=raw.value;
  const preview=await api('/api/candidates/foundit/preview','POST',{raw:source});
  parsedSource=source; renderPreview(preview);
}));
document.querySelector('#foundit-clear').addEventListener('click',()=>{
  if(busy || (dirty && !window.confirm('Discard this unsaved draft?'))) return;
  draftExtras=false; form.reset(); raw.value=''; linked=null; dirty=false; editedFields.clear(); previewReady=false; fields.disabled=true;
  document.querySelector('#foundit-evidence').replaceChildren(); document.querySelector('#foundit-extra').replaceChildren();document.querySelector('#foundit-industry').replaceChildren();document.querySelector('#foundit-education').replaceChildren(); results.replaceChildren(); error.hidden=true; comparisons(); status.textContent='Draft cleared. Saved candidate records are unchanged.';
});
form.addEventListener('input', event=>{
  if(event.target !== confirmed && !event.target.hasAttribute('data-accept')) { if(event.target.dataset.draftKey) draftExtras=true; if(event.target.name) editedFields.add(event.target.name); confirmed.checked=false; dirty=true; status.textContent='Unsaved review changes. Confirm before saving.'; }
});
form.addEventListener('change', event=>{
  if(event.target.matches('select[name]')) { editedFields.add(event.target.name); confirmed.checked=false; dirty=true; }
});
document.querySelector('#foundit-matches').addEventListener('click',()=>action(matchContacts));
document.querySelector('#foundit-search').addEventListener('keydown', event => {
  if(event.key === 'Enter') { event.preventDefault(); document.querySelector('#foundit-find').click(); }
});
document.querySelector('#foundit-find').addEventListener('click',()=>action(async()=>{
  const q=document.querySelector('#foundit-search').value.trim(); if(!q) throw Error('Enter a name or contact to search.');
  await showMatches(await api('/api/candidates?q='+encodeURIComponent(q)));
}));
form.addEventListener('submit',event=>{
  event.preventDefault(); action(async()=>{
    if(!confirmed.checked) throw Error('Confirm identity, contacts and reviewed values before saving.');
    const actor=document.querySelector('#recording-as').value;
    if(!actor) throw Error('Choose Working as before saving.');
    const data=values(); let payload={confirmed:true,recorded_by_staff_id:actor};
    if(linked) {
      const selected=[...form.querySelectorAll('[data-accept]:checked')].map(el=>el.dataset.accept);
      if(!selected.length) throw Error('Select at least one reviewed field to update.');
      for(const key of selected) payload[key]=data[key];
      if(selected.includes('domain_id')) payload.subdomain_id=data.subdomain_id;
      payload.version=linked.version;
    } else {
      if(!data.full_name || !data.mobile) throw Error('Confirmed name and mobile are required.');
      if((await matchContacts()).length) throw Error('Matching contacts exist. Link and review an existing profile; no duplicate was created.');
      payload={...payload,...data,source:'Foundit'};
    }
    status.textContent='Saving…';
    const saved=await api(linked ? `/api/candidates/foundit/${linked.id}/confirm` : '/api/candidates/foundit/confirm', linked ? 'PATCH' : 'POST',payload);
    linked=saved; Object.keys(payload).forEach(key=>editedFields.delete(key)); dirty=editedFields.size>0 || draftExtras; confirmed.checked=false; form.querySelectorAll('[data-accept]').forEach(el=>el.checked=false);
    comparisons(); status.textContent=`Saved · ${saved.full_name} · version ${saved.version}. Only submitted fields were saved. Industry, employment, institution/year and source text are draft only; download to retain them.${editedFields.size ? " Other edited fields remain unsaved." : ""}`;
  });
});
window.addEventListener('beforeunload',event=>{ if(dirty) {event.preventDefault();event.returnValue='';} });

document.querySelector('#foundit-download').addEventListener('click',()=>{
  const draft={source:'Foundit',raw:parsedSource,reviewed_fields:values(),candidate_id:linked?.id || null,
    draft_only:Object.fromEntries([...form.querySelectorAll('[data-draft-key]')].map(input=>[input.dataset.draftKey,input.value])),
    evidence:document.querySelector('#foundit-evidence').textContent};
  const url=URL.createObjectURL(new Blob([JSON.stringify(draft,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='foundit-reviewed-draft.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  draftExtras=false; dirty=!linked || editedFields.size>0; status.textContent='Draft download prepared. Draft-only details have not been saved to the candidate database.';
});

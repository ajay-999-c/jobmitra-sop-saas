const raw = document.querySelector('#foundit-raw');
const form = document.querySelector('#foundit-review');
const fields = document.querySelector('#foundit-fields');
const status = document.querySelector('#foundit-status');
const error = document.querySelector('#foundit-error');
const results = document.querySelector('#foundit-results');
const save = document.querySelector('#foundit-save');
const additional = document.querySelector('#foundit-additional');
let linked = null, savedId = null, busy = false, dirty = false, previewReady = false;
let parsedSource = '', draftExtras = false, separatePerson = false;
const editedFields = new Set();
const inputs = [...form.querySelectorAll('[name]')];
const labels = Object.fromEntries([...form.querySelectorAll('[data-review-field]')].map(el => [el.dataset.reviewField, el.querySelector('label').textContent.trim()]));
function value(input) {
  const text = input.value.trim();
  if (input.dataset.valueKind === 'boolean') return text === '' ? null : text === 'true';
  if (input.dataset.valueKind === 'array') return [...new Map(text.split(/[,\n]/).map(s => s.trim().replace(/\s+/g, ' ')).filter(Boolean).map(s => [s.toLowerCase(), s])).values()];
  if (input.dataset.valueKind === 'number') return text === '' ? null : Number(text);
  return text || null;
}
function values() { return Object.fromEntries(inputs.map(input => [input.name, value(input)])); }
function display(v) { return Array.isArray(v) ? v.join(', ') : v == null ? 'Not recorded' : String(v); }
function clearErrors() {
  error.hidden = true;
  form.querySelectorAll('[data-field-error]').forEach(el => { el.hidden = true; el.textContent = ''; });
  inputs.forEach(input => input.removeAttribute('aria-invalid'));
  document.querySelector('#foundit-domain-error').hidden = true;
}
function fieldError(name, message) {
  const input = form.elements.namedItem(name);
  const box = document.getElementById('error-' + name);
  if (box) { box.textContent = message; box.hidden = false; }
  if (input) { input.setAttribute('aria-invalid', 'true'); if (additional.contains(input)) additional.open = true; }
  if (['domain_id', 'subdomain_id'].includes(name)) {
    additional.open = true;
    const domainError = document.querySelector('#foundit-domain-error'); domainError.hidden = false; domainError.textContent = message;
  }
}
function fail(message) {
  error.textContent = message; error.hidden = false;
  status.textContent = 'Save not confirmed. Your edits are still here.';
  error.scrollIntoView({block:'nearest'});
}
async function api(url, method = 'GET', body) {
  const response = await fetch(url, {method, cache:'no-store', headers:{'Content-Type':'application/json', 'X-Jobmitra-UI':'1'}, ...(body ? {body:JSON.stringify(body)} : {})});
  let data;
  try { data = await response.json(); }
  catch { throw Error('Unexpected server response. Check the Candidate Directory before retrying. Your edits are kept.'); }
  if (!response.ok) {
    if (Array.isArray(data.detail)) {
      data.detail.forEach(item => fieldError(item.loc[1], item.msg));
      throw Error('Check the highlighted fields. Nothing was saved.');
    }
    const problem = Error(data.detail || 'Save failed. Your edits are kept.'); problem.status = response.status; throw problem;
  }
  return data;
}
async function action(work) {
  if (busy) return;
  busy = true; clearErrors(); fields.disabled = true;
  document.querySelector('#foundit-parse').disabled = true;
  document.querySelector('#foundit-clear').disabled = true;
  try { await work(); }
  catch (e) { fail(e.message || 'Connection interrupted. Check the Candidate Directory before retrying; your edits are kept.'); }
  finally {
    busy = false; fields.disabled = !previewReady;
    document.querySelector('#foundit-parse').disabled = false;
    document.querySelector('#foundit-clear').disabled = false;
  }
}
function comparisons() {
  form.querySelectorAll('[data-review-field]').forEach(box => {
    const old = box.querySelector('[data-existing]'); old.hidden = !linked;
    box.querySelector('[data-accept-label]').hidden = !linked;
    old.textContent = linked ? 'Saved value: ' + display(linked[box.dataset.reviewField]) : '';
  });
  document.querySelector('#foundit-accept-domain').hidden = !linked;
  const domainInfo = document.querySelector('#foundit-existing-domain'); domainInfo.hidden = !linked;
  const optionName = (name, id) => [...form.elements[name].options].find(o => o.value === id)?.textContent || id || 'Not recorded';
  domainInfo.textContent = linked ? `Saved domain: ${optionName('domain_id', linked.domain_id)} / ${optionName('subdomain_id', linked.subdomain_id)}` : '';
  const linkInfo = document.querySelector('#foundit-linked'); linkInfo.hidden = !linked;
  linkInfo.textContent = linked ? `Updating ${linked.full_name}. Check only the fields you want to change, then Save Candidate.` : '';
  const link = document.querySelector('#foundit-profile'); link.hidden = !savedId;
  if (savedId) link.href = '/candidates/' + savedId;
}
async function matches() {
  const data = values(), params = new URLSearchParams();
  if (data.mobile) params.set('mobile', data.mobile);
  if (data.email) params.set('email', data.email);
  return api('/api/candidates/duplicates?' + params);
}
function showMatches(rows) {
  results.replaceChildren();
  const p = document.createElement('p'); p.textContent = 'Matching contacts found. Choose Update Existing or explicitly create a separate person. Nothing saved.'; results.append(p);
  for (const row of rows) {
    const item = document.createElement('article'), text = document.createElement('p');
    text.textContent = `${row.full_name} · ${row.mobile} · ${row.email || 'No email'}`;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = 'Update Existing';
    button.addEventListener('click', () => action(async () => {
      linked = await api('/api/candidates/' + row.id);
      form.querySelectorAll('[data-accept]').forEach(el => el.checked = false);
      comparisons(); status.textContent = 'Select the fields to update, then Save Candidate. No changes saved yet.';
    }));
    item.append(text, button); results.append(item);
  }
  const create = document.createElement('button'); create.type = 'button'; create.className = 'secondary'; create.textContent = 'Create New — separate person';
  create.addEventListener('click', () => {
    if (!window.confirm('These contacts already match a candidate. Create a separate person anyway?')) return;
    linked = null; separatePerson = true; comparisons(); form.requestSubmit();
  });
  results.append(create); results.scrollIntoView({block:'nearest'});
}
function renderPreview(preview) {
  for (const input of inputs) {
    const v = preview.fields[input.name]; input.value = Array.isArray(v) ? v.join('\n') : v ?? (input.name === 'current_salary_period' ? 'Unknown' : '');
  }
  document.querySelector('#foundit-notice').hidden = !preview.fields.notice_period_text;
  form.querySelector('[data-catalog-picker]').dispatchEvent(new CustomEvent('catalog-select', {detail:{}}));
  const evidence = document.querySelector('#foundit-evidence'); evidence.replaceChildren();
  document.querySelector('#foundit-source').textContent = parsedSource;
  for (const item of preview.evidence) {
    const p = document.createElement('p'); p.textContent = `${labels[item.field] || item.field}: ${item.note}\nSource: ${item.raw}`; evidence.append(p);
  }
  const extras = document.querySelector('#foundit-extra'); extras.replaceChildren();
  document.querySelector('#foundit-industry').replaceChildren(); document.querySelector('#foundit-education').replaceChildren();
  function draftField(parent, key, labelText, v) {
    const label = document.createElement('label'); label.textContent = labelText;
    const input = document.createElement('textarea'); input.rows = 2; input.value = v || ''; input.dataset.draftKey = key;
    label.append(input); parent.append(label);
  }
  for (const [key, labelText] of [['industry','Current industry'], ['past_industry','Past industry'], ['institution','University / institution'], ['education_year','Education year']]) {
    const target = ['industry','past_industry'].includes(key) ? document.querySelector('#foundit-industry') : document.querySelector('#foundit-education');
    draftField(target, key, labelText + ' (draft only)', preview.preview_only[key]);
  }
  preview.employment_history.forEach((record, index) => {
    const section = document.createElement('section'), heading = document.createElement('h4'); heading.textContent = `Source label: ${record.kind} · employment ${index + 1} (draft only)`; section.append(heading);
    const warning = document.createElement('p'); warning.className = 'foundit-warning'; warning.textContent = record.warning; section.append(warning);
    for (const key of ['role','employer','start','end','industry','raw']) draftField(section, `employment.${index}.${key}`, key === 'raw' ? 'Original employment wording' : key, record[key]);
    extras.append(section);
  });
  draftExtras = true; previewReady = true; dirty = true; linked = null; savedId = null; separatePerson = false; editedFields.clear();
  form.querySelectorAll('[data-accept]').forEach(el => el.checked = false);
  additional.open = false; comparisons(); results.replaceChildren();
  status.textContent = 'Review the fields, then Save Candidate.';
}
document.querySelector('#foundit-parse').addEventListener('click', () => action(async () => {
  if (dirty && !window.confirm('Replace this unsaved review draft?')) return;
  status.textContent = 'Parsing locally…';
  const source = raw.value, preview = await api('/api/candidates/foundit/preview', 'POST', {raw:source});
  parsedSource = source; renderPreview(preview);
}));
document.querySelector('#foundit-clear').addEventListener('click', () => {
  if (busy || (dirty && !window.confirm('Discard this unsaved draft?'))) return;
  form.reset(); raw.value = ''; parsedSource = ''; linked = null; savedId = null; dirty = false; draftExtras = false;
  editedFields.clear(); previewReady = false; fields.disabled = true; additional.open = false;
  ['evidence','source','extra','industry','education'].forEach(id => document.querySelector('#foundit-' + id).replaceChildren());
  results.replaceChildren(); clearErrors(); comparisons(); status.textContent = 'Draft cleared. Saved candidates are unchanged.';
});
form.addEventListener('input', event => {
  if (event.target.hasAttribute('data-accept')) return;
  if (event.target.dataset.draftKey) draftExtras = true;
  if (event.target.name) {
    editedFields.add(event.target.name);
    const fieldMessage = document.getElementById('error-' + event.target.name);
    if (fieldMessage) fieldMessage.hidden = true;
    event.target.removeAttribute('aria-invalid');
    error.hidden = true;
  }
  dirty = true; status.textContent = 'Unsaved edits.';
});
form.addEventListener('change', event => {
  if (event.target.matches('select[name]')) { editedFields.add(event.target.name); dirty = true; }
});
function validate(data, keys) {
  let valid = true;
  for (const key of keys) {
    const input = form.elements.namedItem(key);
    let message = '';
    if (['full_name','mobile'].includes(key) && !data[key]) message = 'This field is required.';
    else if (key === 'mobile' && !/^(?:91)?[6-9]\d{9}$/.test(String(data.mobile).replace(/[ +().-]/g, ''))) message = 'Enter a valid 10-digit Indian mobile, optionally prefixed with +91.';
    else if (input && !input.checkValidity()) message = input.validationMessage;
    if (message) { fieldError(key, message); valid = false; }
  }
  if (!valid) { fail('Check the highlighted fields. Your edits are kept.'); form.querySelector('[aria-invalid=true]')?.focus(); }
  return valid;
}
form.addEventListener('submit', event => {
  event.preventDefault(); if (busy || !previewReady) return;
  clearErrors(); const data = values(), allowSeparate = separatePerson; separatePerson = false;
  const selected = [...form.querySelectorAll('[data-accept]:checked')].map(el => el.dataset.accept);
  if (linked && !selected.length) { fail('This candidate already exists. Select the fields to update; no additional candidate was created.'); return; }
  if (!validate(data, linked ? selected : inputs.map(input => input.name))) return;
  action(async () => {
    const actor = document.querySelector('#recording-as').value || null;
    let payload = {confirmed:true, recorded_by_staff_id:actor};
    if (linked) {
      for (const key of selected) payload[key] = data[key];
      if (selected.includes('domain_id')) payload.subdomain_id = data.subdomain_id;
      payload.version = linked.version;
    } else {
      status.textContent = 'Checking matching contacts…';
      const rows = await matches();
      if (rows.length && !allowSeparate) { showMatches(rows); status.textContent = 'Matching candidate found. Choose how to continue.'; return; }
      payload = {...payload, ...data, source:'Foundit', confirm_duplicate:allowSeparate};
    }
    status.textContent = 'Saving…';
    let saved;
    try { saved = await api(linked ? `/api/candidates/foundit/${linked.id}/confirm` : '/api/candidates/foundit/confirm', linked ? 'PATCH' : 'POST', payload); }
    catch (problem) {
      if (problem.status === 409) { showMatches(await matches()); }
      throw problem;
    }
    linked = saved; savedId = saved.id;
    Object.keys(payload).forEach(key => editedFields.delete(key)); dirty = editedFields.size > 0 || draftExtras;
    form.querySelectorAll('[data-accept]').forEach(el => el.checked = false); results.replaceChildren(); comparisons();
    status.textContent = 'Candidate saved successfully.' + (editedFields.size ? ' Other edited fields remain unsaved.' : '');
  });
});
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
document.querySelector('#foundit-download').addEventListener('click', () => {
  const draft = {source:'Foundit', raw:parsedSource, reviewed_fields:values(), candidate_id:linked?.id || null,
    draft_only:Object.fromEntries([...form.querySelectorAll('[data-draft-key]')].map(input => [input.dataset.draftKey, input.value])), evidence:document.querySelector('#foundit-evidence').textContent};
  const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], {type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = 'foundit-reviewed-draft.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  draftExtras = false; dirty = !savedId || editedFields.size > 0;
  status.textContent = 'Draft download prepared. Draft-only details are not stored in the candidate database.';
});

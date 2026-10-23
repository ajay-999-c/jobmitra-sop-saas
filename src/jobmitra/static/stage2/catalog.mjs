// Shared native, keyboard-accessible selects. Search text is never a saved UUID.
function filterPicker(picker) {
  const q = picker.querySelector('[data-picker-search]').value.trim().toLocaleLowerCase();
  for (const option of picker.querySelector('select').options) {
    option.hidden = !!option.value && !option.selected && !option.textContent.toLocaleLowerCase().includes(q);
  }
}
document.querySelectorAll('[data-search-picker]').forEach(picker => {
  picker.querySelector('[data-picker-search]').addEventListener('input', () => filterPicker(picker));
  picker.querySelector('[data-picker-search]').addEventListener('keydown', event => { if(event.key === 'Enter') event.preventDefault(); });
});
document.querySelectorAll('[data-catalog-picker]').forEach(box => {
  const domain = box.querySelector('[data-domain-select]');
  const sub = box.querySelector('[data-subdomain-select]');
  const status = box.querySelector('[data-catalog-status]');
  let options = [...sub.options].slice(1).map(o => o.cloneNode(true));
  function sync(selected = '') {
    sub.replaceChildren(new Option('Not specified', ''), ...options.filter(o => o.dataset.parent === domain.value).map(o => o.cloneNode(true)));
    sub.value = selected;
    box.querySelectorAll('[data-search-picker]').forEach(filterPicker);
  }
  sync(sub.dataset.selected);
  domain.addEventListener('change', () => { sync(); sub.dispatchEvent(new Event('change', {bubbles:true})); });
  box.addEventListener('catalog-select', event => {
    domain.value = event.detail.domain_id || '';
    sync(event.detail.subdomain_id || '');
  });
  async function refresh() {
    const response = await fetch('/api/domains?active=false', {cache:'no-store'});
    if (!response.ok) throw Error('Could not refresh catalog. Your current selections were kept.');
    const data = await response.json(), oldDomain = domain.value, oldSub = sub.value;
    domain.replaceChildren(new Option('Not specified', ''), ...data.domains.filter(d => d.is_active || d.id === oldDomain).map(d => new Option(d.name + (d.is_active ? '' : ' (inactive)'), d.id)));
    domain.value = oldDomain;
    const activeParents = new Set(data.domains.filter(d=>d.is_active).map(d=>d.id));
    options = data.subdomains.filter(s => (s.is_active && activeParents.has(s.domain_id)) || s.id === oldSub).map(s => {
      const option = new Option(s.name + (s.is_active ? '' : ' (inactive)'), s.id); option.dataset.parent = s.domain_id; return option;
    });
    sync(oldSub);
  }
  box.querySelector('[data-refresh-catalog]')?.addEventListener('click', async () => {
    try { await refresh(); status.textContent = 'Catalog refreshed.'; } catch(e) { status.textContent=e.message; }
  });
  box.querySelectorAll('[data-add-catalog]').forEach(button => button.addEventListener('click', async () => {
    const name = box.querySelector('[data-catalog-name]').value.trim();
    const kind = button.dataset.addCatalog;
    if (!name || (kind === 'subdomain' && !domain.value)) { status.textContent = 'Enter a label and choose the parent domain for a sub-domain.'; return; }
    button.disabled = true; status.textContent = 'Saving catalog label…';
    try {
      const response = await fetch(kind === 'domain' ? '/api/domains' : '/api/subdomains', {method:'POST', headers:{'Content-Type':'application/json','X-Jobmitra-UI':'1'}, body:JSON.stringify(kind === 'domain' ? {name} : {name,domain_id:domain.value})});
      const data = await response.json();
      if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Check the label. A matching label may already exist.');
      await refresh();
      if (kind === 'domain') { domain.value = data.id; sync(); domain.dispatchEvent(new Event('change', {bubbles:true})); }
      else { sub.value = data.id; sub.dispatchEvent(new Event('change', {bubbles:true})); }
      box.querySelector('[data-catalog-name]').value = ''; status.textContent='Saved and selected. Save the form to assign it.';
    } catch(e) { status.textContent = e.message; } finally { button.disabled=false; }
  }));
});

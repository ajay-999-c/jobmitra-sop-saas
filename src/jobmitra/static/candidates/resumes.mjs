// Prototype resume operations; authentication can later be shared at the router boundary.
async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options, cache: 'no-store',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Error(typeof data.detail === 'string' ? data.detail : 'Resume request failed. Please retry.');
  }
  return response;
}
export function selectedResume(form) {
  const input = form.querySelector('[data-resume-file]');
  const file = input?.files[0];
  if (!file) return null;
  if (!/\.(pdf|docx)$/i.test(file.name)) throw Error('Choose a PDF or DOCX resume.');
  if (!file.size || file.size > Number(input.dataset.maxBytes))
    throw Error('Resume is empty or exceeds the displayed upload limit.');
  return file;
}
document.querySelectorAll('[data-optional-resume]').forEach(box => {
  const input = box.querySelector('[data-resume-file]');
  const remove = box.querySelector('[data-remove-resume]');
  function show() {
    box.querySelector('[data-resume-filename]').textContent = input.files[0]?.name || 'No resume selected';
    remove.hidden = !input.files.length;
  }
  input.addEventListener('change', show);
  remove.addEventListener('click', () => { input.value = ''; show(); });
});
export async function uploadResume(candidateId, file) {
  return (await request(`/api/candidates/${candidateId}/resumes`, {
    method: 'POST', headers: {
      'X-Jobmitra-UI': '1', 'X-Document-Filename': encodeURIComponent(file.name),
      'Content-Type': 'application/octet-stream',
    }, body: file,
  })).json();
}

const panel = document.querySelector('[data-resume-panel]');
function panelError(error) {
  const box = panel.querySelector('[data-resume-error]');
  box.hidden = false;
  box.textContent = error.message;
}
function element(tag, text) {
  const el = document.createElement(tag); el.textContent = text; return el;
}
async function loadHistory() {
  const rows = await (await request(`/api/candidates/${panel.dataset.candidateId}/resumes`)).json();
  panel.querySelector('[data-resume-error]').hidden = true;
  const container = panel.querySelector('[data-resume-history]');
  container.replaceChildren();
  if (!rows.length) container.append(element('p', 'No resume uploaded yet'));
  for (const row of rows) {
    const card = element('article', ''); card.className = 'card';
    card.append(element('h3', `Original Resume${row.is_active ? ' · Active' : ' · Previous version'}`));
    card.append(element('p', `${row.original_filename} · ${new Date(row.uploaded_at).toLocaleString()} · ${row.mime_type === 'application/pdf' ? 'PDF' : 'DOCX'}`));
    for (const action of row.mime_type === 'application/pdf' ? ['download', 'preview'] : ['download']) {
      const button = element('button', action === 'preview' ? 'View PDF' : 'Download');
      button.type = 'button'; button.className = 'secondary';
      button.addEventListener('click', async () => {
        button.disabled = true;
        // Open synchronously to avoid popup blockers after the file fetch.
        const viewer = action === 'preview' ? window.open('about:blank', '_blank') : null;
        if (viewer) viewer.opener = null;
        try {
          const response = await request(`/api/candidates/${row.candidate_id}/resumes/${row.id}/${action}`);
          const url = URL.createObjectURL(await response.blob());
          if (action === 'preview' && viewer) viewer.location.replace(url);
          else {
            const link = document.createElement('a');
            link.href = url; link.download = row.original_filename; link.click();
          }
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (error) { viewer?.close(); panelError(error); }
        finally { button.disabled = false; }
      });
      card.append(button);
    }
    card.append(element('h4', 'Parsed Resume'));
    const states = { not_parsed: 'Not parsed yet', processing: 'Processing', failed: 'Parsing failed' };
    card.append(element('p', states[row.parsing_status] || 'Parsed'));
    if (row.parsed_json !== null) card.append(element('pre', JSON.stringify(row.parsed_json, null, 2)));
    // Parser error strings may contain internal paths; present a generic failure state.
    container.append(card);
  }
  panel.querySelector('[data-new-resume]').hidden = false;
  panel.querySelector('[data-load-resumes]').textContent = 'Refresh resumes';
}
panel?.querySelector('[data-load-resumes]').addEventListener('click', () => loadHistory().catch(panelError));
panel?.querySelector('[data-new-resume]').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target, button = form.querySelector('[type=submit]');
  button.disabled = true;
  try {
    const file = selectedResume(form);
    if (!file) throw Error('Choose a resume first.');
    await uploadResume(panel.dataset.candidateId, file);
    form.querySelector('[data-remove-resume]').click();
    await loadHistory();
  } catch (error) { panelError(error); }
  finally { button.disabled = false; }
});

if (panel) loadHistory().catch(panelError);

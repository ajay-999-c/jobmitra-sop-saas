import { createSearchIndex, searchCompanies } from "./search.mjs";

const $ = (id) => document.getElementById(id);
const form = $("company-form");
const search = $("company-search");
const list = $("company-list");
let index = createSearchIndex(JSON.parse($("directory-data").textContent));
let current = null;
let dirty = false;
let busy = false;
let detailRequest = null;
let refreshRequest = null;
let lastRefresh = Date.now();
let directoryNeedsRefresh = false;
const FRESHNESS_MS = 30_000;

function notice(message, error = false) {
  $("form-error").hidden = !error;
  $("form-error").textContent = error ? message : "";
  $("detail-status").textContent = error ? "" : message;
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options, cache: "no-store", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Jobmitra-UI": "1", ...options.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const message = typeof data.detail === "string" ? data.detail : "Check the form values and try again.";
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function renderList() {
  const matches = searchCompanies(index, search.value);
  const fragment = document.createDocumentFragment();
  for (const company of matches) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.companyId = company.id;
    button.textContent = company.company_name;
    if (current?.id === company.id) button.setAttribute("aria-current", "true");
    item.append(button);
    fragment.append(item);
  }
  list.replaceChildren(fragment);
  $("match-count").textContent = search.value.trim()
    ? `${matches.length} of ${index.length} companies` : `${matches.length} companies`;
  $("list-empty").hidden = matches.length > 0;
  $("list-empty").textContent = search.value.trim()
    ? "No matching companies." : "No companies yet. Add your first company.";
}

async function refreshDirectory() {
  if (refreshRequest) return refreshRequest;
  $("refresh-directory").disabled = true;
  refreshRequest = (async () => {
    try {
      index = createSearchIndex(await request("/api/companies"));
      lastRefresh = Date.now();
      directoryNeedsRefresh = false;
      $("directory-error").hidden = true;
      renderList();
      return true;
    } catch {
      directoryNeedsRefresh = true;
      $("directory-error").textContent = "List refresh failed. Showing the last loaded list. Try Refresh.";
      $("directory-error").hidden = false;
      return false;
    } finally {
      $("refresh-directory").disabled = false;
      refreshRequest = null;
    }
  })();
  return refreshRequest;
}

function updateContactHint() {
  $("no-contacts").hidden = $("contact-list").children.length > 0;
}

function appendContact(contact = {}) {
  const card = $("contact-template").content.firstElementChild.cloneNode(true);
  if (contact.id) card.dataset.contactId = contact.id;
  card.querySelector('[name="contact_name"]').value = contact.contact_name ?? "";
  card.querySelector('[name="designation"]').value = contact.designation ?? "";
  card.querySelector('[name="phone_numbers"]').value = (contact.phone_numbers ?? []).join("\n");
  $("contact-list").append(card);
  updateContactHint();
}

function showForm(company = null) {
  current = company;
  form.reset();
  $("contact-list").replaceChildren();
  for (const name of ["company_name", "address_line", "city", "state", "postal_code"]) {
    form.elements[name].value = company?.[name] ?? "";
  }
  form.elements.general_phone_numbers.value = (company?.general_phone_numbers ?? []).join("\n");
  for (const contact of company?.contacts ?? []) appendContact(contact);
  updateContactHint();
  $("form-title").textContent = company?.company_name ?? "Add company";
  $("form-mode").textContent = company ? "COMPANY DETAILS" : "NEW COMPANY";
  $("delete-company").hidden = !company;
  $("reload-details").hidden = !company;
  $("source-references").hidden = !(company?.source_register_ids?.length);
  $("source-references").textContent = `Source IDs: ${(company?.source_register_ids ?? []).join(", ")}`;
  $("detail-placeholder").hidden = true;
  form.hidden = false;
  $("details").scrollTop = 0;
  dirty = false;
  renderList();
}

function canLeave() {
  return !busy && (!dirty || window.confirm("Discard your unsaved changes?"));
}

async function openCompany(id) {
  if (!canLeave()) return;
  detailRequest?.abort();
  const controller = new AbortController();
  detailRequest = controller;
  setBusy(true);
  notice("Loading company…");
  try {
    const company = await request(`/api/companies/${id}`, { signal: controller.signal });
    if (controller.signal.aborted) return;
    showForm(company);
    notice("");
  } catch (error) {
    if (error.name !== "AbortError") notice(error.message, true);
  } finally {
    if (detailRequest === controller) setBusy(false);
  }
}

const optional = (value) => value.trim() || null;
const phones = (value) => [...new Set(value.split(/\r?\n/u).map((s) => s.trim()).filter(Boolean))];
function payload() {
  const data = Object.fromEntries(["company_name", "address_line", "city", "state", "postal_code"]
    .map((name) => [name, optional(form.elements[name].value)]));
  data.general_phone_numbers = phones(form.elements.general_phone_numbers.value);
  data.contacts = [...$("contact-list").children].map((card) => ({
    ...(card.dataset.contactId ? { id: card.dataset.contactId } : {}),
    contact_name: optional(card.querySelector('[name="contact_name"]').value),
    designation: optional(card.querySelector('[name="designation"]').value),
    phone_numbers: phones(card.querySelector('[name="phone_numbers"]').value),
  }));
  if (current) data.updated_at = current.updated_at;
  return data;
}

function setBusy(value) {
  busy = value;
  $("company-fields").disabled = value;
  for (const id of ["save-company", "delete-company", "cancel-edit", "reload-details", "add-company"]) {
    $(id).disabled = value;
  }
}

search.addEventListener("input", () => {
  renderList(); // Pure in-memory search: never calls fetch.
  list.scrollTop = 0;
});
list.addEventListener("click", (event) => {
  const button = event.target.closest("[data-company-id]");
  if (button) openCompany(button.dataset.companyId);
});
$("refresh-directory").addEventListener("click", refreshDirectory);
$("add-company").addEventListener("click", () => {
  if (!canLeave()) return;
  detailRequest?.abort();
  showForm();
  notice("");
  form.elements.company_name.focus();
});
$("add-contact").addEventListener("click", () => { appendContact(); dirty = true; });
$("contact-list").addEventListener("click", (event) => {
  if (event.target.closest("[data-remove-contact]")) {
    event.target.closest(".contact-card").remove();
    dirty = true;
    updateContactHint();
  }
});
form.addEventListener("input", () => { dirty = true; });
$("reload-details").addEventListener("click", () => openCompany(current.id));
$("cancel-edit").addEventListener("click", () => {
  if (!canLeave()) return;
  detailRequest?.abort();
  if (current) showForm(current);
  else { form.hidden = true; $("detail-placeholder").hidden = false; dirty = false; }
  notice("");
});
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const data = payload();
  setBusy(true);
  notice("Saving…");
  try {
    const saved = await request(current ? `/api/companies/${current.id}` : "/api/companies", {
      method: current ? "PUT" : "POST", body: JSON.stringify(data),
    });
    // An older focus/manual refresh must finish before the post-write refresh starts.
    if (refreshRequest) await refreshRequest;
    // Patch immediately, then revalidate the complete lightweight snapshot once.
    const companies = index.map((entry) => entry.company).filter((c) => c.id !== saved.id);
    index = createSearchIndex([...companies, { id: saved.id, company_name: saved.company_name }]);
    showForm(saved);
    notice("Company saved.");
    await refreshDirectory();
  } catch (error) { notice(error.message, true); }
  finally { setBusy(false); }
});
$("delete-company").addEventListener("click", async () => {
  if (busy || !current || !window.confirm(`Delete “${current.company_name}” and its contacts? This cannot be undone.`)) return;
  setBusy(true);
  try {
    await request(`/api/companies/${current.id}`, {
      method: "DELETE", body: JSON.stringify({ updated_at: current.updated_at }),
    });
    if (refreshRequest) await refreshRequest;
    index = createSearchIndex(index.map((entry) => entry.company).filter((c) => c.id !== current.id));
    current = null;
    dirty = false;
    form.hidden = true;
    $("detail-placeholder").hidden = false;
    renderList();
    notice("Company deleted.");
    await refreshDirectory();
  } catch (error) { notice(error.message, true); }
  finally { setBusy(false); }
});

function refreshOnReturn() {
  if (document.visibilityState === "visible"
    && (directoryNeedsRefresh || Date.now() - lastRefresh >= FRESHNESS_MS)) refreshDirectory();
}
window.addEventListener("focus", refreshOnReturn);
document.addEventListener("visibilitychange", refreshOnReturn);
window.addEventListener("pageshow", (event) => { if (event.persisted) refreshDirectory(); });
window.addEventListener("beforeunload", (event) => {
  if (dirty || busy) { event.preventDefault(); event.returnValue = ""; }
});
renderList();

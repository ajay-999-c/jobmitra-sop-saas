// Keep the current section visible inside the scrollable mobile navigation.
const globalNav = document.querySelector(".global-nav");
const activeSection = globalNav?.querySelector('[aria-current="page"]');
if (activeSection && globalNav.scrollWidth > globalNav.clientWidth) {
  globalNav.scrollLeft += activeSection.getBoundingClientRect().left
    - globalNav.getBoundingClientRect().left
    - (globalNav.clientWidth - activeSection.offsetWidth) / 2;
}
const recorder = document.querySelector("#recording-as");
const errorBox = document.querySelector("#workflow-error");
const initial = JSON.parse(
  document.querySelector("#job-data")?.textContent || "null",
);
const storageKey = "jobmitra-recording-as";
function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  errorBox.scrollIntoView({ block: "nearest" });
}
try {
  if (recorder) recorder.value = sessionStorage.getItem(storageKey) || "";
} catch {}
recorder?.addEventListener("change", () => {
  try {
    sessionStorage.setItem(storageKey, recorder.value);
  } catch {}
});
function activateTab(name) {
  const panels = [...document.querySelectorAll("[data-panel]")];
  if (!panels.some((panel) => panel.dataset.panel === name)) name = "overview";
  panels.forEach((panel) => (panel.hidden = panel.dataset.panel !== name));
  document
    .querySelectorAll("[data-tab]")
    .forEach((button) =>
      button.setAttribute("aria-selected", String(button.dataset.tab === name)),
    );
}
activateTab(location.hash.slice(1));
document.querySelectorAll("[data-tab]").forEach((button) =>
  button.addEventListener("click", () => {
    history.replaceState(null, "", `#${button.dataset.tab}`);
    activateTab(button.dataset.tab);
  }),
);
document.querySelector("#my-tasks")?.addEventListener("click", () => {
  if (!recorder.value) return showError("Choose Recording as first.");
  location.href = `/tasks?staff_id=${encodeURIComponent(recorder.value)}`;
});
function valueOf(input) {
  const raw = input.value.trim();
  if (input.dataset.kind === "checkbox") return input.checked;
  if (input.dataset.kind === "boolean") return raw === "true";
  if (input.dataset.kind === "skills") {
    const seen = new Set();
    return raw.split(/[,\r\n]/).map((value) => value.trim().replace(/\s+/g, " "))
      .filter((value) => {
        const key = value.toLowerCase();
        if (!value || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }
  if (input.dataset.kind === "integer") return raw === "" ? null : Number(raw);
  if (input.dataset.kind === "json") return JSON.parse(raw);
  if (input.dataset.kind === "datetime")
    return raw ? new Date(raw).toISOString() : null;
  return raw === "" ? null : raw;
}
function localDatetime(iso) {
  const date = new Date(iso);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
document.querySelectorAll("[data-kind=datetime]").forEach((input) => {
  if (initial?.[input.name]) input.value = localDatetime(initial[input.name]);
});
const salaryPeriod = document.querySelector('[name="salary_period"]');
if (salaryPeriod && !salaryPeriod.disabled) {
  let previous = salaryPeriod.value;
  salaryPeriod.addEventListener("change", () => {
    if (["Monthly", "Annual"].includes(previous)
        && ["Monthly", "Annual"].includes(salaryPeriod.value)
        && salaryPeriod.value !== previous) {
      const factor = salaryPeriod.value === "Annual" ? 12 : 1 / 12;
      for (const name of ["salary_min", "salary_max"]) {
        const input = salaryPeriod.form.elements[name];
        if (input?.value) input.value = (Number(input.value) * factor).toFixed(2);
      }
    }
    previous = salaryPeriod.value;
  });
}
const baselines = new WeakMap();
document
  .querySelectorAll("form[data-diff] [name]")
  .forEach((input) => baselines.set(input, JSON.stringify(valueOf(input))));
document.querySelectorAll("[data-status-select]").forEach((select) => {
  const reason = select.form.elements.closure_reason;
  const sync = () => {
    reason.required = select.value === "Closed";
    reason.disabled = select.value !== "Closed";
  };
  select.addEventListener("change", sync);
  sync();
});
const companySelect = document.querySelector("#company-select");
let contactRequest = 0;
async function loadContacts(first = false) {
  const select = document.querySelector("#company-contact");
  const request = ++contactRequest;
  select.disabled = true;
  select.replaceChildren(new Option("No contact selected", ""));
  if (!companySelect.value) {
    select.disabled = false;
    return;
  }
  try {
    const response = await fetch(
      `/api/companies/${encodeURIComponent(companySelect.value)}`,
      { cache: "no-store" },
    );
    if (!response.ok)
      throw new Error("Could not load company contacts. Reload before saving.");
    const data = await response.json();
    if (request !== contactRequest) return;
    data.contacts.forEach((contact) =>
      select.add(
        new Option(
          contact.contact_name || contact.designation || "Unnamed contact",
          contact.id,
        ),
      ),
    );
    if (first) select.value = select.dataset.initial || "";
    if (first) baselines.set(select, JSON.stringify(valueOf(select)));
    select.disabled = false;
  } catch (error) {
    if (request === contactRequest) showError(error.message);
  }
}
if (companySelect) {
  companySelect.addEventListener("change", () => loadContacts());
  loadContacts(true);
}
document.addEventListener("submit", async (event) => {
  const form = event.target.closest("form[data-endpoint]");
  if (!form) return;
  event.preventDefault();
  errorBox.hidden = true;
  const buttons = [...form.querySelectorAll("button")];
  try {
    const body = {};
    if (form.hasAttribute("data-recruiters"))
      body.staff_ids = [
        ...form.querySelectorAll("[name=staff_ids]:checked"),
      ].map((input) => input.value);
    else
      for (const input of form.elements) {
        if (!input.name || input.disabled || input.tagName === "BUTTON")
          continue;
        const value = valueOf(input);
        if (
          !form.hasAttribute("data-diff") ||
          JSON.stringify(value) !== baselines.get(input)
        )
          body[input.name] = value;
      }
    if (!form.hasAttribute("data-staff")) {
      if (!recorder.value)
        throw new Error(
          "Choose Recording as before saving. This is self-selected, unverified attribution.",
        );
      body.actor_staff_id = recorder.value;
      const version = form.dataset.version || initial?.version;
      if (version) body.version = Number(version);
    }
    buttons.forEach((button) => (button.disabled = true));
    const response = await fetch(form.dataset.endpoint, {
      method: form.dataset.method,
      headers: { "Content-Type": "application/json", "X-Jobmitra-UI": "1" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        Array.isArray(data.detail)
          ? data.detail
              .map((item) => `${item.loc.slice(1).join(" ")}: ${item.msg}`)
              .join("\n")
          : data.detail ||
            "The change could not be saved. Reload before retrying.",
      );
    if (form.hasAttribute("data-create-job"))
      location.href = `/requirements/${data.id}`;
    else if (form.hasAttribute("data-staff"))
      location.href = `/staff${data.duplicate_name_warning ? "?duplicate=1" : ""}`;
    else location.reload();
  } catch (error) {
    showError(
      error.message ||
        "Network unavailable. Your change was not confirmed; reload before retrying.",
    );
  } finally {
    buttons.forEach((button) => (button.disabled = false));
  }
});
document.addEventListener("htmx:responseError", () =>
  showError("The list could not be refreshed. Check connectivity and reload."),
);

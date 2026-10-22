const recorder = document.querySelector("#recording-as");
function error(form, message) {
  const el = form.querySelector("[data-form-error]");
  el.textContent = message;
  el.hidden = false;
  el.scrollIntoView({ block: "nearest" });
}
function value(input) {
  if (input.dataset.type === "boolean") return input.checked;
  const raw = input.value.trim();
  if (input.dataset.type === "array")
    return raw
      ? raw
          .split(/[,\n]/)
          .map((x) => x.trim())
          .filter(Boolean)
      : [];
  if (input.dataset.type === "nullable-bool")
    return raw ? raw === "true" : null;
  if (input.dataset.type === "json") {
    if (new TextEncoder().encode(raw).length > 262144)
      throw Error("JSON exceeds 256 KiB");
    return JSON.parse(raw);
  }
  if (input.dataset.type === "datetime")
    return raw ? new Date(raw).toISOString() : null;
  if (input.dataset.type === "number" || input.name === "experience_months")
    return raw ? Number(raw) : null;
  return raw || null; // Keep Decimal salary amounts as strings; no floating conversion.
}
const baselines = new WeakMap();
document
  .querySelectorAll("[data-profile-form] [name]")
  .forEach((el) => baselines.set(el, JSON.stringify(value(el))));
document
  .querySelectorAll("[data-open-dialog]")
  .forEach((button) =>
    button.addEventListener("click", () =>
      document.getElementById(button.dataset.openDialog).showModal(),
    ),
  );
document
  .querySelectorAll("[data-close-dialog]")
  .forEach((button) =>
    button.addEventListener("click", () => button.closest("dialog").close()),
  );
document
  .querySelectorAll("dialog[data-auto-open=true]")
  .forEach((dialog) => dialog.showModal());
document.querySelectorAll("[data-now]").forEach((input) => {
  const d = new Date();
  input.value = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
});
document
  .querySelector("[data-create-search]")
  ?.addEventListener("change", (event) => {
    const panel = document.querySelector("[data-initial-search]");
    panel.hidden = !event.target.checked;
    panel
      .querySelectorAll("input,select")
      .forEach((el) => (el.required = event.target.checked));
  });
let duplicateTimer,
  duplicateSerial = 0;
const mobile = document.querySelector("[data-profile-form] [name=mobile]");
mobile?.addEventListener("input", () => {
  clearTimeout(duplicateTimer);
  const serial = ++duplicateSerial;
  duplicateTimer = setTimeout(async () => {
    const form = mobile.form,
      box = form.querySelector("[data-duplicate-results]");
    const query = new URLSearchParams({ mobile: mobile.value });
    if (form.dataset.candidateId)
      query.set("exclude_id", form.dataset.candidateId);
    try {
      const response = await fetch("/api/candidates/duplicates?" + query, {
        cache: "no-store",
      });
      if (!response.ok) throw Error();
      const rows = await response.json();
      if (serial !== duplicateSerial) return;
      box.replaceChildren();
      box.hidden = !rows.length;
      if (rows.length)
        box.append(
          document.createTextNode(
            "Possible existing profiles. Open one or confirm a separate person below.",
          ),
        );
      for (const row of rows) {
        const a = document.createElement("a");
        a.href = "/candidates/" + row.id;
        a.textContent = row.full_name + " · " + row.mobile;
        box.append(a);
      }
    } catch {
      if (serial === duplicateSerial) {
        box.hidden = false;
        box.textContent =
          "Duplicate check unavailable. The server will check when saving.";
      }
    }
  }, 250);
});
document.querySelectorAll("[data-candidate-search]").forEach((input) =>
  input.addEventListener("input", () => {
    const select = input.parentElement.querySelector("[data-candidate-picker]");
    const q = input.value.toLowerCase();
    for (const option of select.options)
      option.hidden =
        !!option.value && !option.textContent.toLowerCase().includes(q);
  }),
);
async function responseData(response) {
  const data = await response.json();
  if (!response.ok)
    throw Error(
      Array.isArray(data.detail)
        ? data.detail
            .map((x) => x.loc.slice(1).join(" ") + ": " + x.msg)
            .join("\n")
        : data.detail || "Could not save. Reload before retrying.",
    );
  return data;
}
document.addEventListener("submit", async (event) => {
  const form = event.target.closest(
    "form[data-desk-endpoint],form[data-upload-endpoint]",
  );
  if (!form) return;
  event.preventDefault();
  const buttons = [...form.querySelectorAll("button")];
  buttons.forEach((b) => (b.disabled = true));
  form.querySelector("[data-form-error]").hidden = true;
  try {
    let endpoint = form.dataset.deskEndpoint,
      body = {},
      result;
    if (form.dataset.uploadEndpoint) {
      const file = form.elements.file.files[0];
      if (!file) throw Error("Choose a file");
      const params = new URLSearchParams({
        kind: form.elements.kind.value,
        reviewed: form.elements.reviewed.checked,
      });
      if (recorder.value) params.set("staff_id", recorder.value);
      if (form.elements.source_document_id.value)
        params.set(
          "source_document_id",
          form.elements.source_document_id.value,
        );
      result = await responseData(
        await fetch(form.dataset.uploadEndpoint + "?" + params, {
          method: "POST",
          headers: {
            "X-Jobmitra-UI": "1",
            "X-Document-Filename": encodeURIComponent(file.name),
            "Content-Type": "application/octet-stream",
          },
          body: file,
        }),
      );
    } else {
      for (const input of form.elements) {
        if (!input.name || input.disabled || input.type === "submit") continue;
        const v = value(input);
        if (
          form.hasAttribute("data-profile-form") &&
          form.dataset.method === "PATCH" &&
          !["version", "confirm_duplicate"].includes(input.name) &&
          JSON.stringify(v) === baselines.get(input)
        )
          continue;
        body[input.name] = v;
      }
      if (
        form.hasAttribute("data-profile-form") &&
        form.dataset.method === "POST"
      ) {
        body.recorded_by_staff_id = recorder.value || null;
        if (form.querySelector("[data-create-search]")?.checked) {
          body.initial_job_search = {
            desired_role: form.querySelector("[data-search-role]").value,
            assigned_staff_id: form.querySelector("[data-search-staff]").value,
            preferred_locations: body.preferred_locations,
          };
        }
      }
      if (form.hasAttribute("data-paste-parse"))
        body.pasted_by_staff_id = recorder.value || null;
      if (form.hasAttribute("data-review-parse")) {
        if (!recorder.value)
          throw Error("Select Recording as before reviewing");
        body.reviewed_by_staff_id = recorder.value;
      }
      if (endpoint.includes("__candidate__")) {
        const id = form.querySelector("[data-candidate-picker]").value;
        if (!id) throw Error("Choose an existing profile");
        endpoint = endpoint.replace("__candidate__", encodeURIComponent(id));
      }
      result = await responseData(
        await fetch(endpoint, {
          method: form.dataset.method,
          headers: { "Content-Type": "application/json", "X-Jobmitra-UI": "1" },
          body: JSON.stringify(body),
          cache: "no-store",
        }),
      );
    }
    if (form.hasAttribute("data-profile-form"))
      location.href = "/candidates/" + result.id;
    else location.reload();
  } catch (e) {
    error(
      form,
      e.message ||
        "Network unavailable; save was not confirmed. Reload before retrying.",
    );
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
});

import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../Jobmitra_candidate_submission_final (1).html", import.meta.url), "utf8");
const functions = html.slice(html.indexOf("function legacyRichCopy("), html.indexOf("async function copySubject("));

function setup(mode) {
  const body = { outerHTML: "<table><tr><td>Synthetic Candidate</td></tr></table>", innerText: "Synthetic Candidate" };
  const clipboard = { "text/plain": "Previous email subject" };
  const handlers = new Map(), messages = [];
  let legacyCalls = 0;
  const selection = { rangeCount: 0, removeAllRanges() {}, addRange() {} };
  const document = {
    createRange: () => ({ selectNode() {} }),
    addEventListener: (name, fn) => handlers.set(name, fn),
    removeEventListener: (name) => handlers.delete(name),
    execCommand() {
      legacyCalls++;
      if (mode === "no-copy-event") return true;
      handlers.get("copy")({
        clipboardData: { setData: (type, value) => { clipboard[type] = value; } },
        preventDefault() {},
      });
      return true;
    },
  };
  class ClipboardItem { constructor(values) { this.values = values; } }
  const context = vm.createContext({
    document, Blob, ClipboardItem,
    window: { getSelection: () => selection, ClipboardItem },
    navigator: mode === "http" || mode === "no-copy-event" ? {} : {
      clipboard: { write: async ([item]) => {
        if (mode === "denied") throw Error("Denied");
        for (const [type, blob] of Object.entries(item.values)) clipboard[type] = await blob.text();
      } },
    },
    $: () => ({ firstElementChild: body }),
    validate: () => true,
    toast: (message) => messages.push(message),
  });
  vm.runInContext(functions, context);
  return { context, clipboard, handlers, messages, get legacyCalls() { return legacyCalls; } };
}

for (const mode of ["modern", "http", "denied"]) {
  test("copies body, never stale subject: " + mode, async () => {
    const state = setup(mode);
    await state.context.copyEmail();
    assert.equal(state.clipboard["text/plain"], "Synthetic Candidate");
    assert.match(state.clipboard["text/html"], /<table>/);
    assert.equal(state.handlers.size, 0);
    assert.equal(state.legacyCalls, mode === "modern" ? 0 : 1);
    assert.match(state.messages[0], /Formatted email copied/);
  });
}
test("does not claim success when legacy copy never supplies the body", async () => {
  const state = setup("no-copy-event");
  await state.context.copyEmail();
  assert.match(state.messages[0], /Copy unavailable/);
  assert.equal(state.handlers.size, 0);
});

for (const count of [1, 5, 10]) {
  test("shared job role and expected CTC for " + count + " candidates", () => {
    const context = vm.createContext({
      candidates: Array.from({ length: count }, (_, i) => ({
        name: "Synthetic " + i, experience: "2 years", notice: "30 days",
        ctc: i ? "" : "₹5 LPA", expectedCtc: i ? "" : "₹60,000/month",
      })),
      escapeHtml: value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;"),
      inputVal: () => "QA Automation",
    });
    vm.runInContext(html.slice(html.indexOf("function candidateTableRows()"), html.indexOf("function getEmailHTML()")), context);
    const table = context.candidateTableRows();
    assert.match(table, /EXPECTED CTC/);
    assert.match(table, /₹60,000\/month/);
    assert.match(table, /CURRENT CTC/);
    assert.equal((table.match(/<tr>/g) || []).length, count + 1);
    assert.doesNotMatch(table, /POSITION|Job Title/);
    assert.equal(context.getSubject(), "Candidate Profiles for Review | QA Automation | Jobmitra");
    context.candidates[0].ctc = "";
    assert.doesNotMatch(context.candidateTableRows(), /CURRENT CTC/);
  });
}
test("per-candidate forms have expected CTC instead of job titles", () => {
  assert.match(html, /data-field="expectedCtc"/);
  assert.doesNotMatch(html, /data-field="title"|c\.title/);
});

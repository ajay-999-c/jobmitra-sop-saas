import test from "node:test";
import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";
import { createSearchIndex, searchCompanies } from "../src/jobmitra/modules/companies/static/search.mjs";

const company = (id, company_name) => ({ id, company_name });
const companies = [
  company("a", "Radhe Industries"), company("b", "Radhesham Industry"),
  company("c", "Radhe Exports"), company("d", "Shree Radhe Metals"),
  company("e", "Radhe"), company("f", "Alpha Works"),
];

test("initial list is complete and alphabetically sorted", () => {
  assert.deepEqual(searchCompanies(createSearchIndex(companies)).map((c) => c.company_name), [
    "Alpha Works", "Radhe", "Radhe Exports", "Radhe Industries", "Radhesham Industry", "Shree Radhe Metals",
  ]);
});
test("case-insensitive exact, prefix, contains ranking matches the requested example", () => {
  assert.deepEqual(searchCompanies(createSearchIndex(companies), " RADHE ").map((c) => c.company_name), [
    "Radhe", "Radhe Exports", "Radhe Industries", "Radhesham Industry", "Shree Radhe Metals",
  ]);
});
test("matches substrings anywhere, empty query and no-match query", () => {
  const index = createSearchIndex(companies);
  assert.deepEqual(searchCompanies(index, "dhesham").map((c) => c.id), ["b"]);
  assert.equal(searchCompanies(index, "   ").length, companies.length);
  assert.deepEqual(searchCompanies(index, "nonexistent"), []);
});
test("names remain text and contact search can be added through the same boundary", () => {
  const data = [company("x", '<script>alert("x")</script>')];
  assert.equal(searchCompanies(createSearchIndex(data), "script")[0].company_name, data[0].company_name);
  const row = { ...company("y", "Acme"), contact_name: "Example Contact" };
  assert.equal(searchCompanies(createSearchIndex([row]), "example").length, 0);
  assert.equal(searchCompanies(createSearchIndex([row], ["company_name", "contact_name"]), "example").length, 1);
});
test("search is pure: no fetch and no mutation of the source snapshot", () => {
  const original = JSON.stringify(companies);
  const before = globalThis.fetch;
  globalThis.fetch = () => { throw new Error("Search must never fetch"); };
  try {
    const index = createSearchIndex(companies);
    for (const query of ["r", "ra", "rad", "radhe", "", "industr"]) searchCompanies(index, query);
    assert.equal(JSON.stringify(companies), original);
  } finally { globalThis.fetch = before; }
});
test("166-company search timing (informational, no brittle timing assertion)", (context) => {
  const index = createSearchIndex(Array.from({ length: 166 }, (_, i) => company(String(i), `Company ${i} Industries`)));
  const start = performance.now();
  for (let i = 0; i < 1000; i++) searchCompanies(index, i % 2 ? "industr" : "company 1");
  context.diagnostic(`Mean search across 166 companies: ${((performance.now() - start) / 1000).toFixed(3)} ms`);
  assert.equal(index.length, 166);
});

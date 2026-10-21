// Pure search boundary: replace its caller with server search if the directory grows.
export const normalize = (value) => String(value ?? "").normalize("NFKC")
  .toLowerCase().trim().replace(/\s+/gu, " ");

const collator = new Intl.Collator("en", { sensitivity: "base", numeric: true });
const alphabetically = (a, b) => collator.compare(a.company.company_name, b.company.company_name)
  || String(a.company.id).localeCompare(String(b.company.id));

// Add searchable fields here only when included deliberately in the lightweight snapshot.
export function createSearchIndex(companies, fields = ["company_name"]) {
  return companies.map((company) => ({
    company,
    name: normalize(company.company_name),
    searchText: fields.map((field) => normalize(company[field])).join("\n"),
  })).sort(alphabetically);
}

export function searchCompanies(index, query = "") {
  const needle = normalize(query);
  if (!needle) return index.map((entry) => entry.company);
  const rank = (entry) => entry.name === needle ? 0 : entry.name.startsWith(needle) ? 1 : 2;
  return index.filter((entry) => entry.searchText.includes(needle))
    .sort((a, b) => rank(a) - rank(b) || alphabetically(a, b))
    .map((entry) => entry.company);
}

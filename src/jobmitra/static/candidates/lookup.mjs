// Server-rendered search using the existing directory route and access policy.
document.querySelectorAll("[data-candidate-lookup]").forEach((root) => {
  const form = root.querySelector("form");
  const input = form.elements.q;
  const status = root.querySelector("[data-lookup-status]");
  const results = root.querySelector("[data-lookup-results]");
  let timer, controller, serial = 0;

  function cancel() {
    clearTimeout(timer);
    controller?.abort();
    serial += 1;
    results.setAttribute("aria-busy", "false");
  }

  async function search(url) {
    cancel();
    const current = serial;
    controller = new AbortController();
    status.textContent = "Loading candidates…";
    results.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(url, {
        headers: { "HX-Request": "true" },
        signal: controller.signal,
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Search failed");
      const html = await response.text();
      if (current !== serial) return;
      results.innerHTML = html;
      status.textContent = "";
    } catch (error) {
      if (current !== serial || error.name === "AbortError") return;
      status.textContent = "Could not load candidates. Please try Search again.";
      results.replaceChildren();
    } finally {
      if (current === serial) results.setAttribute("aria-busy", "false");
    }
  }

  function url() {
    return "/candidates?" + new URLSearchParams({ q: input.value.trim() });
  }

  input.addEventListener("input", () => {
    cancel();
    status.textContent = "Waiting to search…";
    timer = setTimeout(() => search(url()), 300);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    search(url());
  });
  results.addEventListener("click", (event) => {
    const link = event.target.closest("[data-search-page]");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    search(link.href);
  });
});

/* FireLab M2 paper panel. External metadata is rendered only with textContent. */
(() => {
  "use strict";

  const form = document.getElementById("paper-search-form");
  if (!form) return;

  const queryInput = document.getElementById("paper-search-query");
  const submitButton = document.getElementById("paper-search-submit");
  const statusNode = document.getElementById("paper-search-status");
  const resultsNode = document.getElementById("paper-search-results");
  const modeNode = document.getElementById("paper-search-mode");
  const noticeNode = document.getElementById("paper-search-notice");
  let sessionToken = null;
  let offlineMode = false;

  function setStatus(message, state = "") {
    statusNode.textContent = message;
    statusNode.dataset.state = state;
  }

  function appendText(parent, tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    parent.append(node);
    return node;
  }

  function safeExternalUrl(value) {
    if (typeof value !== "string" || value.length > 2048) return null;
    try {
      const parsed = new URL(value);
      if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password) return null;
      return parsed.href;
    } catch (_error) {
      return null;
    }
  }

  function renderPaper(paper) {
    const card = document.createElement("article");
    card.className = "paper-result-card";
    appendText(card, "h3", "paper-result-title", paper.title || "Untitled paper");

    const metadata = [];
    if (Number.isInteger(paper.year)) metadata.push(String(paper.year));
    const providers = Array.isArray(paper.providers)
      ? paper.providers.filter((provider) => typeof provider === "string")
      : [];
    if (providers.length) metadata.push(`Provider(s): ${providers.join(", ")}`);
    else if (typeof paper.provider === "string") metadata.push(`Provider: ${paper.provider}`);
    if (typeof paper.retrieved_at === "string") metadata.push(`Retrieved: ${paper.retrieved_at}`);
    appendText(card, "p", "paper-result-meta", metadata.join(" · "));

    if (Array.isArray(paper.authors) && paper.authors.length) {
      appendText(card, "p", "paper-result-authors", paper.authors.join(", "));
    }

    // A visible DOI label must link to the DOI resolver, not a provider-specific URL.
    const doi = typeof paper.doi === "string" ? paper.doi.trim() : "";
    const validDoi = /^10\.\d{4,9}\/\S+$/i.test(doi);
    const encodedDoi = validDoi
      ? encodeURIComponent(doi).replace(/%2F/gi, "/")
      : "";
    const doiUrl = encodedDoi ? safeExternalUrl(`https://doi.org/${encodedDoi}`) : null;
    const recordUrl = safeExternalUrl(paper.url);
    const linkUrl = doiUrl || recordUrl;
    if (linkUrl) {
      const link = document.createElement("a");
      link.className = "paper-result-link";
      link.href = linkUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = doiUrl ? `DOI: ${doi}` : "Open paper record";
      card.append(link);
    }

    const terms = Array.isArray(paper.matched_terms) ? paper.matched_terms.filter((term) => typeof term === "string") : [];
    if (terms.length) appendText(card, "p", "paper-result-terms", `Matched title/abstract terms: ${terms.join(", ")}`);
    if (typeof paper.abstract === "string" && paper.abstract) {
      appendText(card, "p", "paper-result-abstract", paper.abstract);
    } else {
      appendText(card, "p", "paper-result-no-abstract", "No abstract provided by the source.");
    }
    return card;
  }

  function renderResponse(data) {
    resultsNode.replaceChildren();
    const state = data.state;
    const retrieved = data.retrieved_at ? ` Retrieved on ${data.retrieved_at}.` : "";
    const sourceCount = Array.isArray(data.papers) ? data.papers.length : 0;
    const statusText = {
      fresh: `Retrieved papers · Retrieved sources: ${sourceCount}.${retrieved}`,
      cache_hit: `Retrieved papers · Retrieved sources: ${sourceCount} from the local cache.${retrieved}`,
      cache_stale: `Showing a cached result older than 30 days.${retrieved}`,
      no_results: "No paper records were returned by the available scholarly providers.",
      cache_miss_offline: "This query is not in the offline cache. No network request was made.",
      unavailable: "Scholarly sources are temporarily unavailable.",
      timeout: "The research request timed out.",
      busy: "Research capacity is busy. Please retry shortly."
    };
    setStatus(data.message || statusText[state] || "The research request could not be completed.", state);
    if (data.partial) appendText(resultsNode, "p", "paper-search-partial", "This retrieved set may be incomplete because a provider reported a partial result.");
    if (Array.isArray(data.papers)) {
      for (const paper of data.papers.slice(0, 3)) {
        if (paper && typeof paper === "object") resultsNode.append(renderPaper(paper));
      }
    }
  }

  async function bootstrap() {
    try {
      const response = await fetch("/api/session", { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) throw new Error("session unavailable");
      const payload = await response.json();
      if (typeof payload.token !== "string" || !payload.token) throw new Error("invalid session");
      sessionToken = payload.token;
      offlineMode = payload.offline === true;
      modeNode.textContent = offlineMode ? "OFFLINE CACHE ONLY" : "CACHE FIRST · FREE PROVIDERS";
      noticeNode.textContent = offlineMode
        ? "Offline mode: results come only from this machine's local cache. No scholarly API request will be made."
        : "Retrieve up to three paper records from scholarly metadata providers. Your query is sent to external scholarly APIs. Do not enter private information.";
      setStatus(offlineMode ? "Offline mode is active. Only locally cached papers can be shown." : "Ready to retrieve up to three scholarly paper records.", "ready");
      submitButton.disabled = false;
    } catch (_error) {
      setStatus("The local FireLab research service is unavailable. Start the M2 server to use this panel.", "unavailable");
      submitButton.disabled = true;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!sessionToken) {
      setStatus("The local research session is not ready.", "unavailable");
      return;
    }
    const query = queryInput.value.trim();
    if (query.length < 3 || query.length > 200) {
      setStatus("Enter a keyword query containing 3 to 200 characters.", "invalid");
      return;
    }
    submitButton.disabled = true;
    setStatus("Searching the local cache and approved scholarly providers…", "loading");
    resultsNode.replaceChildren();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 32000);
    try {
      const response = await fetch("/api/papers/search", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-FireLab-Session": sessionToken
        },
        body: JSON.stringify({ query }),
        signal: controller.signal
      });
      let data = {};
      try { data = await response.json(); } catch (_error) { data = {}; }
      if (response.status === 429) {
        renderResponse({ state: "busy", papers: [] });
      } else if (!response.ok) {
        renderResponse({ state: "unavailable", papers: [] });
      } else {
        renderResponse(data);
      }
    } catch (error) {
      if (error && error.name === "AbortError") renderResponse({ state: "timeout", papers: [] });
      else renderResponse({ state: "unavailable", papers: [] });
    } finally {
      window.clearTimeout(timeout);
      submitButton.disabled = false;
    }
  });

  submitButton.disabled = true;
  bootstrap();
})();

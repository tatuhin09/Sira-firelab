(function attachSourceLabel(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FireLabSourceLabel = api;
})(typeof globalThis === "object" ? globalThis : this, function createSourceLabel() {
  "use strict";

  function formatNasaReleaseLabel(release) {
    const value = String(release || "").trim();
    if (!value) return "NASA PSI-69";
    return /^NASA\b/i.test(value) ? value : `NASA ${value}`;
  }

  return { formatNasaReleaseLabel };
});

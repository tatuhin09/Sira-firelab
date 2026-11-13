const test = require("node:test");
const assert = require("node:assert/strict");
const { formatNasaReleaseLabel } = require("../firelab_site/source-label.js");

test("formats the NASA release once whether or not the input already has the agency name", () => {
  assert.equal(formatNasaReleaseLabel("PSI-69 Version 5"), "NASA PSI-69 Version 5");
  assert.equal(formatNasaReleaseLabel("NASA PSI-69 Version 5"), "NASA PSI-69 Version 5");
});

test("uses the dataset fallback when the release name is empty", () => {
  assert.equal(formatNasaReleaseLabel(""), "NASA PSI-69");
});

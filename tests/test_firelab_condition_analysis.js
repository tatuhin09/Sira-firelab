const test = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const analysis = require("../firelab_site/condition-analysis.js");

const records = JSON.parse(readFileSync(path.join(__dirname, "../firelab_site/data/records.json"), "utf8"));
const baseline = {
  pressureMin: 750,
  pressureMax: 770,
  oxygenMoleFraction: 0.21,
  coSourceMoleFraction: 0,
  heliumMoleFraction: 0,
};

test("matches exact condition values and keeps the 0.21 baseline sample sizes", () => {
  const result = analysis.filterRecords(records, baseline);
  assert.equal(result.error, null);
  assert.equal(result.rows.length, 25);
  const groups = analysis.summarizeByFuel(result.rows);
  assert.deepEqual(groups.map((group) => [group.fuel, group.n]), [["Heptane", 13], ["Methanol", 12]]);
});

test("reports the broader baseline slice when oxygen is unrestricted", () => {
  const result = analysis.filterRecords(records, { ...baseline, oxygenMoleFraction: null });
  const groups = analysis.summarizeByFuel(result.rows);
  assert.equal(result.rows.length, 64);
  assert.deepEqual(groups.map((group) => [group.fuel, group.n]), [["Methanol", 35], ["Heptane", 29]]);
});

test("separates outcome counts and extinction-diameter sample size", () => {
  const result = analysis.filterRecords(records, baseline);
  const groups = analysis.summarizeByFuel(result.rows);
  const methanol = groups.find((group) => group.fuel === "Methanol");
  const heptane = groups.find((group) => group.fuel === "Heptane");
  assert.deepEqual(methanol.outcomes, { Extinction: 9, Disruption: 3, Completion: 0 });
  assert.deepEqual(heptane.outcomes, { Extinction: 4, Disruption: 7, Completion: 2 });
  assert.equal(methanol.extinctionDiameter.exact, 8);
  assert.equal(methanol.extinctionDiameter.missing, 1);
  assert.ok(Math.abs(methanol.extinctionDiameter.median - 1.18) < 1e-12);
  assert.equal(heptane.extinctionDiameter.exact, 4);
});

test("does not let approximate conditions satisfy exact filters", () => {
  const record = {
    ambientPressureMmHg: 760,
    oxygenMoleFraction: 0.21,
    coSourceMoleFraction: 0,
    heliumMoleFraction: 0,
    quality: {
      ambientPressureMmHg: "exact",
      oxygenMoleFraction: "exact",
      coSourceMoleFraction: "approximate",
      heliumMoleFraction: "exact",
    },
  };
  const result = analysis.filterRecords([record], baseline);
  assert.equal(result.rows.length, 0);
});

test("Wilson intervals stay finite for zero and full proportions", () => {
  const zero = analysis.wilsonInterval(0, 12);
  const full = analysis.wilsonInterval(12, 12);
  assert.ok(Number.isFinite(zero.low) && Number.isFinite(zero.high));
  assert.ok(Number.isFinite(full.low) && Number.isFinite(full.high));
  assert.equal(zero.low, 0);
  assert.equal(full.high, 1);
  assert.ok(zero.high > 0 && full.low < 1);
});

test("invalid pressure bounds return a clear error without filtering", () => {
  const result = analysis.filterRecords(records, { ...baseline, pressureMin: 800 });
  assert.equal(result.rows.length, 0);
  assert.match(result.error, /minimum pressure/i);
});

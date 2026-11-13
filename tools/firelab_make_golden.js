#!/usr/bin/env node
"use strict";
// Generates tests/fixtures/firelab_golden.json from the REAL browser JavaScript.
// Python parity tests compare firelab_service/engine.py against this file.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const siteDir = path.join(root, "firelab_site");
const recordsBytes = fs.readFileSync(path.join(siteDir, "data", "records.json"));
const records = JSON.parse(recordsBytes.toString("utf8"));
const analysis = require(path.join(siteDir, "condition-analysis.js"));
const appSource = fs.readFileSync(path.join(siteDir, "app.js"), "utf8");

function extractFunction(name) {
  const start = appSource.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`app.js: function ${name} not found`);
  const end = appSource.indexOf("\n}\n", start);
  if (end < 0) throw new Error(`app.js: end of function ${name} not found`);
  return appSource.slice(start, end + 2);
}
const appFns = vm.runInNewContext(
  `${extractFunction("countsBy")}\n${extractFunction("exactMeasurementSummary")}\n({ countsBy, exactMeasurementSummary });`
);

const uniqueExact = (field) => [...new Set(records
  .filter((r) => r.quality?.[field] === "exact" && Number.isFinite(r[field]))
  .map((r) => r[field]))].sort((a, b) => a - b);

const base = { pressureMin: 750, pressureMax: 770, oxygenMoleFraction: 0.21, coSourceMoleFraction: 0, heliumMoleFraction: 0 };
const wide = { pressureMin: 0, pressureMax: 100000, oxygenMoleFraction: null, coSourceMoleFraction: null, heliumMoleFraction: null };

const filterInputs = [
  ["baseline", base],
  ["baseline-any-oxygen", { ...base, oxygenMoleFraction: null }],
  ["everything", wide],
  ["narrow-pressure", { ...wide, pressureMin: 755, pressureMax: 760 }],
  ["no-match", { ...wide, pressureMin: 1, pressureMax: 2 }],
  ["error-min-greater-than-max", { ...base, pressureMin: 800 }],
  ["error-missing-pressure", { ...base, pressureMin: null }],
  ["error-bad-gas", { ...base, oxygenMoleFraction: "abc" }],
  ["numeric-strings", { pressureMin: "750", pressureMax: "770", oxygenMoleFraction: "0.21", coSourceMoleFraction: "0", heliumMoleFraction: "0" }],
];
for (const v of uniqueExact("oxygenMoleFraction")) {
  filterInputs.push([`oxygen=${v} all-pressures`, { ...wide, oxygenMoleFraction: v }]);
  filterInputs.push([`oxygen=${v} baseline-others`, { ...base, oxygenMoleFraction: v }]);
}
for (const v of uniqueExact("coSourceMoleFraction")) filterInputs.push([`co=${v}`, { ...wide, coSourceMoleFraction: v }]);
for (const v of uniqueExact("heliumMoleFraction")) filterInputs.push([`helium=${v}`, { ...wide, heliumMoleFraction: v }]);

const filterCases = filterInputs.map(([name, filters]) => {
  const result = analysis.filterRecords(records, filters);
  const groups = analysis.summarizeByFuel(result.rows);
  return {
    name, filters, error: result.error,
    testNumbers: result.rows.map((r) => r.testNumber),
    groups, ranking: analysis.rankOutcomeShareGaps(groups),
  };
});

// Same composition as renderOxygenSensitivity() in firelab_site/app.js (minus DOM code).
function runSensitivity(name, filters) {
  const fixedFilters = {
    pressureMin: filters.pressureMin, pressureMax: filters.pressureMax,
    coSourceMoleFraction: filters.coSourceMoleFraction, heliumMoleFraction: filters.heliumMoleFraction,
  };
  const definitions = [
    { label: "Fixed oxygen \u00b7 0.21", oxygenMoleFraction: 0.21 },
    { label: "All exact oxygen values", oxygenMoleFraction: null },
  ];
  const slices = definitions.map((d) => {
    const result = analysis.filterRecords(records, { ...fixedFilters, oxygenMoleFraction: d.oxygenMoleFraction });
    return { ...d, rows: result.rows, error: result.error, groups: analysis.summarizeByFuel(result.rows) };
  });
  const invalid = slices.find((s) => s.error);
  if (invalid) return { name, filters, status: "unavailable", message: `Sensitivity comparison unavailable: ${invalid.error}` };
  const insufficient = slices.find((s) => analysis.rankOutcomeShareGaps(s.groups).length === 0);
  if (insufficient) {
    const count = insufficient.groups.length;
    return { name, filters, status: "unavailable", message: `At least two fuel groups with matched records are needed in both slices. ${insufficient.label} has ${count} fuel group${count === 1 ? "" : "s"}.` };
  }
  const ranked = slices.map((s) => ({
    label: s.label, oxygenMoleFraction: s.oxygenMoleFraction, n: s.rows.length,
    groups: s.groups, ranked: analysis.rankOutcomeShareGaps(s.groups),
  }));
  const fixedOrder = ranked[0].ranked.map((i) => i.outcome);
  const broadOrder = ranked[1].ranked.map((i) => i.outcome);
  return { name, filters, status: "ok", message: null, slices: ranked, fixedOrder, broadOrder, orderChanged: fixedOrder.join("|") !== broadOrder.join("|") };
}
const sensitivityCases = [
  ["baseline", base],
  ["wide-pressure", { ...wide, oxygenMoleFraction: 0.21 }],
  ["error-min-greater-than-max", { ...base, pressureMin: 800 }],
  ["no-match", { ...wide, pressureMin: 1, pressureMax: 2 }],
].map(([name, filters]) => runSensitivity(name, filters));

const wilson = [];
for (let n = 1; n <= 40; n += 1) {
  for (let s = 0; s <= n; s += 1) wilson.push({ successes: s, total: n, result: analysis.wilsonInterval(s, n) });
}
for (const [s, n] of [[-1, 5], [6, 5], [1.5, 5], [1, 0], [0, 0], [2, "x"], ["2", 5]]) {
  wilson.push({ successes: s, total: n, result: analysis.wilsonInterval(s, n) });
}

const measurementKeys = ["burningRateMm2PerSec", "visibleFlameExtinctionDiameterMm", "initialDropletDiameterMm", "burnTimeSeconds", "ambientPressureMmHg"];
const fuelNames = Object.keys(appFns.countsBy(records, "fuel")).sort();
const measurements = [];
for (const key of measurementKeys) {
  measurements.push({ key, scope: "all", result: appFns.exactMeasurementSummary(records, key) });
  for (const fuel of fuelNames) {
    measurements.push({ key, scope: fuel, result: appFns.exactMeasurementSummary(records.filter((r) => r.fuel === fuel), key) });
  }
}

const output = {
  meta: {
    generator: "tools/firelab_make_golden.js",
    recordsSha256: crypto.createHash("sha256").update(recordsBytes).digest("hex"),
    recordCount: records.length,
  },
  filterCases, sensitivityCases, wilson, measurements,
  countsBy: { fuel: appFns.countsBy(records, "fuel"), testEnd: appFns.countsBy(records, "testEnd") },
};

const outPath = path.join(root, "tests", "fixtures", "firelab_golden.json");
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(output, null, 1) + "\n");

const doubleCounted = records.filter((r) => Object.keys(r.quality || {}).some((k) => r.quality[k] === "invalid" && (r[k] === null || r[k] === undefined))).length;
console.log(`golden written: ${outPath}`);
console.log(`filter cases: ${filterCases.length}, sensitivity: ${sensitivityCases.length}, wilson: ${wilson.length}, measurements: ${measurements.length}`);
console.log(`rows with an invalid value that is also null (counted as both invalid and missing by exactMeasurementSummary): ${doubleCounted}`);

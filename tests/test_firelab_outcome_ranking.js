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

function group(fuel, n, shares) {
  const outcomeNames = ["Extinction", "Disruption", "Completion"];
  return {
    fuel,
    n,
    outcomeSummaries: outcomeNames.map((outcome) => {
      const count = shares[outcome] * n;
      return { outcome, count, share: shares[outcome] };
    }),
  };
}

test("ranks default-cohort outcome gaps by full-precision absolute difference", () => {
  const filtered = analysis.filterRecords(records, baseline);
  const groups = analysis.summarizeByFuel(filtered.rows);
  const ranked = analysis.rankOutcomeShareGaps(groups);

  assert.deepEqual(ranked.map((item) => item.outcome), ["Extinction", "Disruption", "Completion"]);
  assert.ok(Math.abs(ranked[0].gapPercentagePoints - 44.23076923076923) < 1e-10);
  assert.ok(Math.abs(ranked[1].gapPercentagePoints - 28.846153846153843) < 1e-10);
  assert.ok(Math.abs(ranked[2].gapPercentagePoints - 15.384615384615385) < 1e-10);
  assert.equal(ranked[0].higherShareFuel, "Methanol");
  assert.equal(ranked[0].left.count, 4);
  assert.equal(ranked[0].left.n, 13);
  assert.equal(ranked[0].right.count, 9);
  assert.equal(ranked[0].right.n, 12);
});

test("returns no pairwise ranks when the cohort contains one fuel", () => {
  const ranked = analysis.rankOutcomeShareGaps([
    group("Methanol", 4, { Extinction: 0.5, Disruption: 0.5, Completion: 0 }),
  ]);
  assert.deepEqual(ranked, []);
});

test("retains zero-share outcomes as valid comparisons", () => {
  const ranked = analysis.rankOutcomeShareGaps([
    group("Methanol", 4, { Extinction: 0, Disruption: 0.5, Completion: 0.5 }),
    group("Heptane", 4, { Extinction: 1, Disruption: 0, Completion: 0 }),
  ]);
  const extinction = ranked.find((item) => item.outcome === "Extinction");
  assert.equal(extinction.gapPercentagePoints, 100);
  assert.equal(extinction.left.count, 4);
  assert.equal(extinction.right.count, 0);
});

test("derives shares from integer counts and denominators", () => {
  const first = group("Alpha", 4, { Extinction: 0.75, Disruption: 0.25, Completion: 0 });
  const second = group("Beta", 4, { Extinction: 0.25, Disruption: 0.5, Completion: 0.25 });
  first.outcomeSummaries.find((item) => item.outcome === "Extinction").share = 0;
  second.outcomeSummaries.find((item) => item.outcome === "Extinction").share = 1;

  const extinction = analysis.rankOutcomeShareGaps([first, second]).find((item) => item.outcome === "Extinction");
  assert.equal(extinction.left.share, 0.75);
  assert.equal(extinction.right.share, 0.25);
  assert.equal(extinction.gapPercentagePoints, 50);
});

test("keeps ranks stable when fuel groups arrive in reverse order", () => {
  const first = group("Alpha", 4, { Extinction: 0.75, Disruption: 0.25, Completion: 0 });
  const second = group("Beta", 4, { Extinction: 0.25, Disruption: 0.5, Completion: 0.25 });
  assert.deepEqual(
    analysis.rankOutcomeShareGaps([first, second]),
    analysis.rankOutcomeShareGaps([second, first]),
  );
});

test("resolves equal gaps with the declared outcome order", () => {
  const ranked = analysis.rankOutcomeShareGaps([
    group("Alpha", 4, { Extinction: 0.75, Disruption: 0.25, Completion: 0 }),
    group("Beta", 4, { Extinction: 0.5, Disruption: 0.5, Completion: 0 }),
  ]);
  assert.deepEqual(ranked.map((item) => item.outcome), ["Extinction", "Disruption", "Completion"]);
  assert.equal(ranked[0].gapPercentagePoints, ranked[1].gapPercentagePoints);
});

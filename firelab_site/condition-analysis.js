(function attachConditionAnalysis(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.FireLabConditionAnalysis = api;
})(typeof globalThis === "object" ? globalThis : this, function createConditionAnalysis() {
  "use strict";

  const OUTCOME_ORDER = ["Extinction", "Disruption", "Completion"];
  const CONDITION_FIELDS = [
    "ambientPressureMmHg",
    "oxygenMoleFraction",
    "coSourceMoleFraction",
    "heliumMoleFraction",
  ];

  function exactConditionValue(record, field) {
    if (record?.quality?.[field] !== "exact") return null;
    const value = record[field];
    return Number.isFinite(value) ? value : null;
  }

  function normalizeOptionalNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = typeof value === "number" ? value : Number(value);
    return Number.isFinite(number) ? number : NaN;
  }

  function filterRecords(records, filters = {}) {
    const pressureMin = normalizeOptionalNumber(filters.pressureMin);
    const pressureMax = normalizeOptionalNumber(filters.pressureMax);
    const oxygen = normalizeOptionalNumber(filters.oxygenMoleFraction);
    const coSource = normalizeOptionalNumber(filters.coSourceMoleFraction);
    const helium = normalizeOptionalNumber(filters.heliumMoleFraction);

    if ([pressureMin, pressureMax].some((value) => value === null || Number.isNaN(value))) {
      return { rows: [], error: "Enter valid minimum and maximum pressure values." };
    }
    if (pressureMin > pressureMax) {
      return { rows: [], error: "Minimum pressure must be less than or equal to maximum pressure." };
    }
    if ([oxygen, coSource, helium].some(Number.isNaN)) {
      return { rows: [], error: "Choose an exact numeric gas fraction or Any exact value." };
    }

    const rows = (Array.isArray(records) ? records : []).filter((record) => {
      const values = CONDITION_FIELDS.map((field) => exactConditionValue(record, field));
      if (values.some((value) => value === null)) return false;
      const [pressureValue, oxygenValue, coValue, heliumValue] = values;
      return pressureValue >= pressureMin
        && pressureValue <= pressureMax
        && (oxygen === null || oxygenValue === oxygen)
        && (coSource === null || coValue === coSource)
        && (helium === null || heliumValue === helium);
    });
    return { rows, error: null };
  }

  function wilsonInterval(successes, total, z = 1.959963984540054) {
    if (!Number.isInteger(successes) || !Number.isInteger(total) || total <= 0 || successes < 0 || successes > total) {
      return { low: null, high: null };
    }
    const proportion = successes / total;
    const zSquared = z * z;
    const denominator = 1 + zSquared / total;
    const center = (proportion + zSquared / (2 * total)) / denominator;
    const margin = z * Math.sqrt((proportion * (1 - proportion) / total) + (zSquared / (4 * total * total))) / denominator;
    return {
      low: successes === 0 ? 0 : Math.max(0, center - margin),
      high: successes === total ? 1 : Math.min(1, center + margin),
    };
  }

  function median(values) {
    if (!values.length) return null;
    const sorted = [...values].sort((left, right) => left - right);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function summarizeByFuel(rows) {
    const grouped = new Map();
    for (const record of Array.isArray(rows) ? rows : []) {
      const fuel = record?.fuel || "Unspecified fuel";
      if (!grouped.has(fuel)) grouped.set(fuel, []);
      grouped.get(fuel).push(record);
    }

    return [...grouped.entries()].map(([fuel, recordsForFuel]) => {
      const outcomes = Object.fromEntries(OUTCOME_ORDER.map((name) => [name, 0]));
      for (const record of recordsForFuel) {
        if (Object.hasOwn(outcomes, record.testEnd)) outcomes[record.testEnd] += 1;
      }
      const outcomeSummaries = OUTCOME_ORDER.map((outcome) => {
        const count = outcomes[outcome];
        const interval = wilsonInterval(count, recordsForFuel.length);
        return {
          outcome,
          count,
          share: recordsForFuel.length ? count / recordsForFuel.length : 0,
          ciLow: interval.low,
          ciHigh: interval.high,
        };
      });

      const extinctionRecords = recordsForFuel.filter((record) => record.testEnd === "Extinction");
      const diameterValues = [];
      let approximate = 0;
      let missing = 0;
      let invalid = 0;
      for (const record of extinctionRecords) {
        const quality = record.quality?.visibleFlameExtinctionDiameterMm;
        const value = record.visibleFlameExtinctionDiameterMm;
        if (quality === "exact" && Number.isFinite(value)) diameterValues.push(value);
        else if (quality === "approximate") approximate += 1;
        else if (quality === "invalid") invalid += 1;
        else missing += 1;
      }
      diameterValues.sort((left, right) => left - right);
      const extinctionDiameter = {
        exact: diameterValues.length,
        approximate,
        missing,
        invalid,
        median: median(diameterValues),
        min: diameterValues.length ? diameterValues[0] : null,
        max: diameterValues.length ? diameterValues[diameterValues.length - 1] : null,
      };

      return {
        fuel,
        n: recordsForFuel.length,
        outcomes,
        outcomeSummaries,
        extinctionDiameter,
      };
    }).sort((left, right) => right.n - left.n || left.fuel.localeCompare(right.fuel));
  }

  function rankOutcomeShareGaps(groups) {
    const validGroups = (Array.isArray(groups) ? groups : [])
      .filter((group) => Number.isInteger(group?.n) && group.n > 0 && Array.isArray(group.outcomeSummaries))
      .sort((left, right) => String(left.fuel).localeCompare(String(right.fuel)));
    const comparisons = [];

    for (let leftIndex = 0; leftIndex < validGroups.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < validGroups.length; rightIndex += 1) {
        const leftGroup = validGroups[leftIndex];
        const rightGroup = validGroups[rightIndex];
        for (const outcome of OUTCOME_ORDER) {
          const leftSummary = leftGroup.outcomeSummaries.find((item) => item.outcome === outcome);
          const rightSummary = rightGroup.outcomeSummaries.find((item) => item.outcome === outcome);
          const validSummary = (summary, groupSize) => summary
            && Number.isInteger(summary.count)
            && summary.count >= 0
            && summary.count <= groupSize;
          if (!validSummary(leftSummary, leftGroup.n) || !validSummary(rightSummary, rightGroup.n)) continue;

          const left = {
            fuel: String(leftGroup.fuel || "Unspecified fuel"),
            count: leftSummary.count,
            n: leftGroup.n,
            share: leftSummary.count / leftGroup.n,
          };
          const right = {
            fuel: String(rightGroup.fuel || "Unspecified fuel"),
            count: rightSummary.count,
            n: rightGroup.n,
            share: rightSummary.count / rightGroup.n,
          };
          const delta = left.share - right.share;
          comparisons.push({
            outcome,
            left,
            right,
            gap: Math.abs(delta),
            gapPercentagePoints: Math.abs(delta) * 100,
            higherShareFuel: delta > 0 ? left.fuel : delta < 0 ? right.fuel : null,
          });
        }
      }
    }

    const outcomeOrder = new Map(OUTCOME_ORDER.map((outcome, index) => [outcome, index]));
    return comparisons.sort((left, right) => right.gap - left.gap
      || outcomeOrder.get(left.outcome) - outcomeOrder.get(right.outcome)
      || left.left.fuel.localeCompare(right.left.fuel)
      || left.right.fuel.localeCompare(right.right.fuel));
  }

  return { filterRecords, summarizeByFuel, wilsonInterval, rankOutcomeShareGaps };
});

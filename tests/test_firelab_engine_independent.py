"""Independent validation of the FireLab engine against the original NASA CSV.

The CSV checks do not use records.json or JavaScript to calculate expected
filter membership, fuel counts, or outcome counts.
"""
import csv
import json
import math
import re
import unittest
from collections import Counter
from pathlib import Path
from statistics import NormalDist

from firelab_service import engine

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "firelab_site"

PRESSURE = "Ambient pressure; mmHg"
OXYGEN = "O initial ambient composition; mole fraction"
CO = "CO initial ambient composition; mole fraction"
HELIUM = "He initial ambient composition; mole fraction"

FIELD_TO_HEADER = {
    "ambientPressureMmHg": PRESSURE,
    "oxygenMoleFraction": OXYGEN,
    "nitrogenMoleFraction": "N initial ambient composition; mole fraction",
    "coSourceMoleFraction": CO,
    "heliumMoleFraction": HELIUM,
    "initialDropletDiameterMm": "Droplet initial diameter; mm",
    "visibleFlameExtinctionDiameterMm": "Visible flame extinction diameter; mm",
    "burningRateMm2PerSec": "Burning rate; mm",
    "burnTimeSeconds": "Burn time; s",
}


def classify_csv_value(value):
    """Classify raw CSV text without consulting the JSON quality labels."""
    text = (value or "").strip()

    if not text:
        return "other"

    if text.startswith("~"):
        return "approximate"

    try:
        number = float(text)
    except (TypeError, ValueError, OverflowError):
        return "other"

    return "exact" if math.isfinite(number) else "other"


def read_csv_rows(manifest):
    source_path = SITE / "data" / "source" / manifest["sourceFile"]

    if not source_path.is_file():
        raise FileNotFoundError(f"NASA source CSV not found: {source_path}")

    rows = []
    with open(source_path, encoding="cp1252", newline="") as handle:
        reader = csv.DictReader(handle)

        if not reader.fieldnames:
            raise AssertionError("NASA CSV has no header row")

        required = {
            "FLEX Test #",
            "Fuel",
            "Test end",
            PRESSURE,
            OXYGEN,
            CO,
            HELIUM,
        }
        missing = required - set(reader.fieldnames)

        if missing:
            raise AssertionError(
                f"NASA CSV is missing required headers: {sorted(missing)}"
            )

        for raw in reader:
            row = {
                (key or "").strip(): (value or "").strip()
                for key, value in raw.items()
            }

            if row.get("FLEX Test #"):
                rows.append(row)

    return rows


def independent_slice(rows, oxygen):
    """Recompute the baseline cohort from raw CSV text only."""
    selected = []

    for row in rows:
        texts = [
            row[PRESSURE],
            row[OXYGEN],
            row[CO],
            row[HELIUM],
        ]

        if not all(classify_csv_value(value) == "exact" for value in texts):
            continue

        pressure, oxy, co, helium = (float(value) for value in texts)

        if (
            750 <= pressure <= 770
            and co == 0
            and helium == 0
            and (oxygen is None or oxy == oxygen)
        ):
            selected.append(row)

    return selected


class IndependentCsvChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = engine.load_bundle(SITE)
        cls.records = cls.bundle["records"]
        cls.rows = read_csv_rows(cls.bundle["manifest"])

        cls.by_test = {}
        for row in cls.rows:
            test_number = int(row["FLEX Test #"])
            if test_number in cls.by_test:
                raise AssertionError(
                    f"Duplicate FLEX Test #: {test_number}"
                )
            cls.by_test[test_number] = row

    def test_same_experiments_in_csv_and_bundle(self):
        csv_numbers = set(self.by_test)
        bundle_numbers = {record["testNumber"] for record in self.records}

        self.assertEqual(len(self.rows), 274)
        self.assertEqual(len(self.by_test), 274)
        self.assertEqual(csv_numbers, bundle_numbers)

    def test_every_record_agrees_with_its_csv_row(self):
        checked = 0

        for record in self.records:
            test_number = record["testNumber"]
            self.assertIn(test_number, self.by_test)

            row = self.by_test[test_number]

            self.assertEqual(
                record["fuel"],
                row["Fuel"],
                f"Fuel mismatch for FLEX Test #{test_number}",
            )
            self.assertEqual(
                record["testEnd"],
                row["Test end"],
                f"Test end mismatch for FLEX Test #{test_number}",
            )

            quality_map = record.get("quality", {})

            for field, header in FIELD_TO_HEADER.items():
                if field not in quality_map:
                    continue

                quality = quality_map[field]
                self.assertIn(
                    quality,
                    {"exact", "approximate", "missing", "invalid"},
                    f"Unknown quality label: {quality!r}",
                )

                raw_text = row[header]
                csv_class = classify_csv_value(raw_text)
                value = record.get(field)

                with self.subTest(test=test_number, field=field):
                    if quality == "exact":
                        self.assertEqual(csv_class, "exact", raw_text)
                        self.assertTrue(
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            and math.isfinite(value)
                        )
                        self.assertEqual(float(raw_text), value)

                    elif quality == "approximate":
                        self.assertEqual(csv_class, "approximate", raw_text)

                    elif quality == "missing":
                        self.assertEqual(csv_class, "other", raw_text)

                    elif quality == "invalid":
                        self.assertEqual(csv_class, "other", raw_text)

                checked += 1

        self.assertGreater(checked, 2000)

    def test_baseline_slices_recomputed_from_csv_only(self):
        cases = (
            (0.21, 25),
            (None, 64),
        )

        for oxygen, expected_total in cases:
            with self.subTest(oxygen=oxygen):
                independent = independent_slice(self.rows, oxygen)

                self.assertEqual(len(independent), expected_total)

                filters = {
                    "pressureMin": 750,
                    "pressureMax": 770,
                    "oxygenMoleFraction": oxygen,
                    "coSourceMoleFraction": 0,
                    "heliumMoleFraction": 0,
                }

                evidence = engine.condition_evidence(
                    self.records,
                    filters,
                )

                self.assertEqual(evidence["matchedCount"], expected_total)

                csv_test_numbers = sorted(
                    int(row["FLEX Test #"]) for row in independent
                )

                self.assertEqual(
                    sorted(evidence["testNumbers"]),
                    csv_test_numbers,
                )

                expected_counts = Counter(
                    (row["Fuel"], row["Test end"])
                    for row in independent
                )

                actual_counts = Counter()

                for group in evidence["groups"]:
                    for outcome, count in group["outcomes"].items():
                        if count:
                            actual_counts[(group["fuel"], outcome)] = count

                self.assertEqual(expected_counts, actual_counts)


class IndependentWilsonCheck(unittest.TestCase):
    def test_alternative_closed_form(self):
        z = NormalDist().inv_cdf(0.975)
        worst = 0.0
        compared = 0

        for n in range(1, 41):
            for successes in range(n + 1):
                p = successes / n

                denominator = 2 * (n + z * z)
                radical = math.sqrt(
                    z * z + 4 * n * p * (1 - p)
                )

                low = (
                    2 * n * p + z * z - z * radical
                ) / denominator

                high = (
                    2 * n * p + z * z + z * radical
                ) / denominator

                expected_low = (
                    0.0 if successes == 0 else max(0.0, low)
                )
                expected_high = (
                    1.0 if successes == n else min(1.0, high)
                )

                actual = engine.wilson_interval(successes, n)

                self.assertAlmostEqual(
                    actual["low"],
                    expected_low,
                    delta=1e-12,
                    msg=f"Wilson low mismatch: successes={successes}, n={n}",
                )
                self.assertAlmostEqual(
                    actual["high"],
                    expected_high,
                    delta=1e-12,
                    msg=f"Wilson high mismatch: successes={successes}, n={n}",
                )

                worst = max(
                    worst,
                    abs(actual["low"] - expected_low),
                    abs(actual["high"] - expected_high),
                )
                compared += 1

        print(
            f"\nWilson independent formula: "
            f"{compared} comparisons, max absolute difference {worst:.3e}"
        )


class EdgeCaseTests(unittest.TestCase):
    def test_unknown_outcome_counts_in_denominator_but_no_bucket(self):
        group = engine.summarize_by_fuel([
            {"fuel": "A", "testEnd": "Extinction"},
            {"fuel": "A", "testEnd": "Mystery"},
        ])[0]

        self.assertEqual(group["n"], 2)
        self.assertEqual(
            group["outcomes"],
            {"Extinction": 1, "Disruption": 0, "Completion": 0},
        )
        self.assertEqual(
            sum(item["share"] for item in group["outcomeSummaries"]),
            0.5,
        )

    def test_missing_fuel_is_grouped_as_unspecified(self):
        groups = engine.summarize_by_fuel([
            {"testEnd": "Extinction"},
            {"fuel": "", "testEnd": "Completion"},
        ])

        self.assertEqual(
            [(group["fuel"], group["n"]) for group in groups],
            [("Unspecified fuel", 2)],
        )

    def test_equal_sized_groups_sort_by_fuel_name(self):
        groups = engine.summarize_by_fuel([
            {"fuel": "Zed", "testEnd": "Extinction"},
            {"fuel": "Alpha", "testEnd": "Extinction"},
        ])

        self.assertEqual(
            [group["fuel"] for group in groups],
            ["Alpha", "Zed"],
        )

    def test_counts_by_counts_only_non_empty_strings(self):
        rows = [
            {"fuel": "A"},
            {"fuel": ""},
            {"fuel": None},
            {"fuel": 5},
            {},
            "not a dict",
        ]

        self.assertEqual(
            engine.counts_by(rows, "fuel"),
            {"A": 1},
        )


if __name__ == "__main__":
    unittest.main()
